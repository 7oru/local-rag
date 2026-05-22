from pathlib import Path
from typing import Optional

import typer

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


def main() -> None:
    app()
