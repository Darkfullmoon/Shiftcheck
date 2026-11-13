"""Branch (location) lookups with a small in-process cache."""

import time

from flask import session

from ..db import query_all

_CACHE = {"rows": None, "at": 0.0}
TTL_SECONDS = 60


def invalidate():
    _CACHE["rows"] = None


def _rows():
    if _CACHE["rows"] is None or time.time() - _CACHE["at"] > TTL_SECONDS:
        _CACHE["rows"] = query_all(
            "SELECT id, name, code, is_active, cleaning_schedule_enabled, template_id "
            "FROM branches ORDER BY name"
        )
        _CACHE["at"] = time.time()
    return _CACHE["rows"]


def all_branches(include_archived=False):
    return [b for b in _rows() if include_archived or b["is_active"]]


def get(branch_id):
    try:
        branch_id = int(branch_id)
    except (TypeError, ValueError):
        return None
    return next((b for b in _rows() if b["id"] == branch_id), None)


def cleaning_branches():
    return [b for b in all_branches() if b["cleaning_schedule_enabled"]]


def label(branch_id):
    branch = get(branch_id)
    return branch["name"] if branch else "Unknown location"


def user_branch():
    return get(session.get("branch_id"))


def allowed_branches():
    """Branches the signed-in user may submit for: admins get all, users their own."""
    if session.get("role") == "ADMIN":
        return all_branches()
    own = user_branch()
    if own and own["is_active"]:
        return [own]
    return all_branches()


def resolve_submit_branch(raw_value):
    """Validates a branch id from a form against what the user is allowed to submit for."""
    allowed = {b["id"]: b for b in allowed_branches()}
    try:
        return allowed.get(int(raw_value))
    except (TypeError, ValueError):
        return None
