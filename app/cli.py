"""Command line: ``encaixe <command>``. Batch commands are heavy: run them one at a time."""

from __future__ import annotations

import logging

import typer

from app.config import get_settings

app = typer.Typer(help="Encaixe — vagas com regras abertas.", no_args_is_help=True)
clock_app = typer.Typer(help="Relógio da aplicação (o modo demo avança o tempo).", no_args_is_help=True)
app.add_typer(clock_app, name="clock")


def _setup() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")
    settings.ensure_var_dirs()
    from app.db import init_db

    init_db()


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Start the API and the production front build."""
    import uvicorn

    _setup()
    from app.api.main import create_app

    uvicorn.run(create_app(), host=host, port=port, log_level=get_settings().log_level.lower())


@app.command("init-db")
def init_db_cmd() -> None:
    """Create the database tables and the append-only triggers."""
    _setup()
    typer.echo(f"database ready: {get_settings().db_url}")


@clock_app.command("show")
def clock_show() -> None:
    _setup()
    from app import clock

    typer.echo(f"now={clock.now().isoformat()} offset_days={clock.get_offset_days():g}")


@clock_app.command("set")
def clock_set(days: float = typer.Option(..., "--days", help="Days ahead of the real clock.")) -> None:
    _setup()
    from app import clock

    clock.set_offset_days(days)
    typer.echo(f"offset_days={clock.get_offset_days():g} now={clock.now().isoformat()}")


@clock_app.command("advance")
def clock_advance(days: float = typer.Option(..., "--days")) -> None:
    _setup()
    from app import clock

    clock.advance_days(days)
    typer.echo(f"offset_days={clock.get_offset_days():g} now={clock.now().isoformat()}")


if __name__ == "__main__":
    app()
