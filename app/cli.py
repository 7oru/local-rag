from pathlib import Path
from typing import Optional

import typer

from app.config import ConfigError, load_settings

app = typer.Typer(
    add_completion=False,
    help="Local-first RAG reference CLI.",
    no_args_is_help=True,
)


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
        raise typer.BadParameter(str(exc)) from exc

    for line in settings.summary_lines():
        typer.echo(line)


def main() -> None:
    app()
