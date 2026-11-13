"""MySQL access helpers and schema bootstrap."""

import json
import os
import secrets
from contextlib import contextmanager
from datetime import datetime

import pymysql
import pymysql.cursors
from flask import current_app
from werkzeug.security import generate_password_hash

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")


def local_utc_offset():
    """The server's UTC offset as '+07:00', so MySQL timestamps match Python's local time."""
    raw = datetime.now().astimezone().strftime("%z")
    return f"{raw[:3]}:{raw[3:]}"


def _settings(cfg=None):
    cfg = cfg or current_app.config
    tz = cfg.get("DB_TIMEZONE") or local_utc_offset()
    return dict(
        host=cfg["DB_HOST"],
        port=int(cfg["DB_PORT"]),
        user=cfg["DB_USER"],
        password=cfg["DB_PASSWORD"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        # NOW()/CURRENT_TIMESTAMP must use the same clock as the deadline checks in Python.
        init_command=f"SET time_zone = '{tz}'",
    )


def connect(cfg=None, autocommit=True, with_database=True):
    cfg = cfg or current_app.config
    params = _settings(cfg)
    if with_database:
        params["database"] = cfg["DB_NAME"]
    return pymysql.connect(autocommit=autocommit, **params)


def query_all(sql, params=None):
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()
    finally:
        conn.close()


def query_one(sql, params=None):
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchone()
    finally:
        conn.close()


def execute(sql, params=None):
    """Runs a write statement and returns the new row id (or affected row count)."""
    conn = connect()
    try:
        with conn.cursor() as cur:
            affected = cur.execute(sql, params or ())
            return cur.lastrowid or affected
    finally:
        conn.close()


@contextmanager
def transaction():
    """Yields a cursor inside a transaction that commits on success and rolls back on error."""
    conn = connect(autocommit=False)
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def to_json(value):
    return json.dumps(value, ensure_ascii=False)


def from_json(value, default=None):
    """Parses a JSON column value; returns `default` for empty or corrupt data."""
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _schema_statements():
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        lines = [ln for ln in fh.read().splitlines() if not ln.strip().startswith("--")]
    return [stmt.strip() for stmt in "\n".join(lines).split(";") if stmt.strip()]


def init_db(cfg=None, create_admin=True, log=print):
    """Creates the database and tables if needed, and the first admin account."""
    cfg = cfg or current_app.config
    conn = connect(cfg, with_database=False)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{cfg['DB_NAME']}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    except pymysql.err.OperationalError:
        pass  # The account may not be allowed to create databases; it may already exist.
    finally:
        conn.close()

    conn = connect(cfg)
    try:
        with conn.cursor() as cur:
            for stmt in _schema_statements():
                cur.execute(stmt)
            if create_admin:
                cur.execute("SELECT COUNT(*) AS n FROM users WHERE role = 'ADMIN'")
                if cur.fetchone()["n"] == 0:
                    username = cfg.get("ADMIN_USERNAME") or "admin"
                    password = cfg.get("ADMIN_PASSWORD") or secrets.token_urlsafe(12)
                    cur.execute(
                        "INSERT INTO users (username, full_name, password_hash, role, must_change_password) "
                        "VALUES (%s, %s, %s, 'ADMIN', %s)",
                        (username, "Administrator", generate_password_hash(password),
                         0 if cfg.get("ADMIN_PASSWORD") else 1),
                    )
                    if cfg.get("ADMIN_PASSWORD"):
                        log(f"[shiftcheck] Created admin account '{username}' (password from ADMIN_PASSWORD).")
                    else:
                        log(f"[shiftcheck] Created admin account '{username}' with temporary password: {password}")
    finally:
        conn.close()
