from pathlib import Path
from typing import Optional

import typer

from app.config import ConfigError, load_settings
from app.db import DatabaseError, init_db

app = typer.Typer(
    add_completion=False,
    help="Local-first RAG reference CLI.",
    no_args_is_help=True,
)
db_app = typer.Typer(help="Database management commands.", no_args_is_help=True)
app.add_typer(db_app, name="db")


@app.callback()
def callback(
    ctx: typer.Context,
    env_file: Optional[Path] = typer.Option(
        None,
        "--env-file",
        help="Path to an explicit .env file.",
        exists=False,
        dir_okay=False,
        resolve_path=True,
    ),
) -> None:
    ctx.obj = {"env_file": env_file}


@app.command("config")
def config_command(ctx: typer.Context) -> None:
    """Print a redacted configuration summary."""
    try:
        settings = load_settings(ctx.obj.get("env_file") if ctx.obj else None)
    except ConfigError as exc:
        typer.echo(f"configuration error: {exc}", err=True)
        raise typer.Exit(1) from exc

    for line in settings.summary_lines():
        typer.echo(line)


@db_app.command("init")
def db_init_command(ctx: typer.Context) -> None:
    """Initialize or update the Postgres schema."""
    try:
        settings = load_settings(ctx.obj.get("env_file") if ctx.obj else None)
        init_db(settings)
    except (ConfigError, DatabaseError) as exc:
        typer.echo(f"database error: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo("database schema initialized")


def main() -> None:
    app()
