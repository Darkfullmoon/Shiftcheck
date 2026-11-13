"""Flask CLI commands: `flask --app app init-db | retention`."""

import click

from .db import init_db
from .services import retention


def register_cli(app):
    @app.cli.command("init-db")
    def init_db_command():
        """Create the database tables and the first admin account."""
        init_db()
        click.echo("Database is ready.")

    @app.cli.command("retention")
    @click.option("--months", type=int, default=None, help="Override RETENTION_MONTHS.")
    def retention_command(months):
        """Delete records (and their files) older than the retention period."""
        months = months if months is not None else app.config["RETENTION_MONTHS"]
        stats = retention.run_cleanup(months)
        click.echo(f"Retention cleanup: {stats}")

