"""Command line: ``encaixe <command>``. Batch commands are heavy: run them one at a time."""

from __future__ import annotations

import logging

import typer

from app.config import get_settings

app = typer.Typer(help="Encaixe — vagas com regras abertas.", no_args_is_help=True)
clock_app = typer.Typer(help="Relógio da aplicação (o modo demo avança o tempo).", no_args_is_help=True)
app.add_typer(clock_app, name="clock")
rules_app = typer.Typer(help="Página de regras (gerada de app/config.py).", no_args_is_help=True)
app.add_typer(rules_app, name="rules")


@rules_app.command("export")
def rules_export() -> None:
    """Write docs/RULES.md from app/config.py (same template as the in-app page)."""
    from app.rules import export_rules_md

    typer.echo(f"wrote {export_rules_md()}")


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


@app.command()
def seed(
    recruiters: bool = typer.Option(True, help="Also load the synthetic B side (5 fictional companies)."),
    vectors: bool = typer.Option(True, help="Compute embeddings and the market-map projection."),
) -> None:
    """Load the 60 fictional seed jobs (offline mode) and the synthetic recruiters."""
    _setup()
    from app.db import session_scope
    from app.seed.loader import load_recruiters, load_seed_jobs, open_job_count

    with session_scope() as s:
        counts = load_seed_jobs(s)
        recs = load_recruiters(s) if recruiters else []
    typer.echo(f"seed jobs: {counts}; recruiters: {len(recs)}")
    if vectors:
        _vectors_and_projection()
    with session_scope() as s:
        typer.echo(f"open jobs: {open_job_count(s)}")


def _vectors_and_projection() -> None:
    from app.db import session_scope
    from app.embeddings import embedding_status
    from app.embeddings.projection import compute_projection
    from app.jobs import ensure_job_vectors

    with session_scope() as s:
        n = ensure_job_vectors(s)
    typer.echo(f"embedded {n} job versions ({embedding_status()})")
    with session_scope() as s:
        info = compute_projection(s)
    typer.echo(f"projection: {info.get('n', 0)} jobs, {len(info.get('clusters', []))} clusters ({info.get('method')})")


@app.command()
def embed() -> None:
    """Compute missing job vectors (all of them if the embedding backend changed)."""
    _setup()
    from app.db import session_scope
    from app.jobs import ensure_job_vectors

    with session_scope() as s:
        typer.echo(f"embedded {ensure_job_vectors(s)} job versions")


@app.command()
def project() -> None:
    """Recompute the 2D market map (PCA → t-SNE) and its clusters."""
    _setup()
    _vectors_and_projection()


@app.command()
def export(candidate: int = typer.Option(..., "--candidate", help="Candidate id.")) -> None:
    """Print, as JSON, everything Encaixe stores about a candidate (events included)."""
    import json

    _setup()
    from app.db import session_scope
    from app.privacy import export_candidate

    with session_scope() as s:
        data = export_candidate(s, candidate)
    if data is None:
        raise typer.Exit(code=1)
    typer.echo(json.dumps(data, ensure_ascii=False, indent=1))


@app.command()
def purge(
    candidate: int = typer.Option(..., "--candidate", help="Candidate id."),
    yes: bool = typer.Option(False, "--yes", help="Do not ask for confirmation."),
) -> None:
    """Delete a candidate: profile, revisions, events (as actor or item), matches and CV LLM cache."""
    _setup()
    if not yes:
        typer.confirm(f"Apagar definitivamente o candidato {candidate}?", abort=True)
    from app.db import session_scope
    from app.privacy import purge_candidate

    with session_scope() as s:
        counts = purge_candidate(s, candidate)
    if not counts:
        typer.echo("candidato não encontrado")
        raise typer.Exit(code=1)
    typer.echo(f"apagado: {counts}")


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
