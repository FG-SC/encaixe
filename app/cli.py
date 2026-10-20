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


synth_app = typer.Typer(help="Pessoas sintéticas (nunca dados reais).", no_args_is_help=True)
app.add_typer(synth_app, name="synth")
demo_app = typer.Typer(help="Modo demo.", no_args_is_help=True)
app.add_typer(demo_app, name="demo")


@synth_app.command("recruiters")
def synth_recruiters() -> None:
    """The synthetic B side: 5 fictional companies with one recruiter each (Lumen Dados / Carla included)."""
    _setup()
    from app.db import session_scope
    from app.seed.loader import load_recruiters

    with session_scope() as s:
        typer.echo(f"recruiters: {len(load_recruiters(s))}")


@synth_app.command("candidates")
def synth_candidates(
    n: int = typer.Option(100, "--n"),
    seed: int = typer.Option(42, "--seed"),
    days: int = typer.Option(56, "--days", help="Simulated history length (days before now)."),
) -> None:
    """Generate synthetic candidates and play their histories (swipes, applications, recruiter reviews)."""
    _setup()
    _vectors_and_projection()
    counts = _synth(n, seed, days)
    typer.echo(f"synthetic candidates: {n}; history: {counts}")


def _synth(n: int, seed: int, days: int) -> dict:
    from app import clock
    from app.db import session_scope
    from app.synth.personas import make_personas
    from app.synth.simulate import sim_start_for, simulate

    start = sim_start_for(days, clock.today())
    personas = make_personas(n, seed, clock.today(), start.date(), days)
    with session_scope() as s:
        return simulate(s, personas, start, days, seed)


@demo_app.command("reset")
def demo_reset(
    snapshot: str | None = typer.Option(None, "--snapshot", help="Load this snapshot instead of the seed jobs."),
    n: int = typer.Option(100, "--n"),
    seed: int = typer.Option(42, "--seed"),
    days: int = typer.Option(56, "--days"),
) -> None:
    """Fresh demo world: jobs (seed or snapshot), synthetic B side, 100 synthetic candidates with histories."""
    import shutil

    settings = get_settings()
    db = settings.var_dir / "encaixe.db"
    for suffix in ("", "-wal", "-shm"):
        p = db.with_name(db.name + suffix)
        if p.exists():
            p.unlink()
    shutil.rmtree(settings.var_dir / "eval", ignore_errors=True)
    _setup()
    from app import clock
    from app.db import session_scope
    from app.seed.loader import load_recruiters, load_seed_jobs

    clock.set_offset_days(0)
    with session_scope() as s:
        if snapshot:
            from app.ingest.snapshot import load_snapshot

            typer.echo(f"snapshot: {load_snapshot(s, snapshot)}")
        else:
            typer.echo(f"seed jobs: {load_seed_jobs(s)}")
        typer.echo(f"recruiters: {len(load_recruiters(s))}")
    _vectors_and_projection()
    typer.echo(f"history: {_synth(n, seed, days)}")
    typer.echo("demo pronta: encaixe serve  (roteiro em docs/DEMO.md)")


eval_app = typer.Typer(help="Avaliação (resultados em var/eval, relatório em docs/EVAL.md).", no_args_is_help=True)
app.add_typer(eval_app, name="eval")


@eval_app.command("replay")
def eval_replay(max_sessions: int = typer.Option(400, "--max-sessions")) -> None:
    _setup()
    from app.db import session_scope
    from app.eval.replay import run_replay
    from app.eval.report import save_result

    with session_scope() as s:
        res = run_replay(s, max_sessions=max_sessions)
    save_result("replay", res)
    for name, m in res["variants"].items():
        typer.echo(f"{name:40} MRR={m['mrr']:.3f} R@10={m['recall@10']:.3f} AUC={m['auc'] or 0:.3f}")


@eval_app.command("drift")
def eval_drift(
    users: int = typer.Option(30, "--users"),
    days: int = typer.Option(40, "--days"),
    seed: int = typer.Option(7, "--seed"),
) -> None:
    _setup()
    from app.db import session_scope
    from app.eval.drift import run_drift
    from app.eval.report import save_result

    with session_scope() as s:
        res = run_drift(s, users=users, days=days, seed=seed)
    save_result("drift", res)
    for name, v in res.get("curves", {}).items():
        typer.echo(f"{name:40} recovery={v['recovery_days']} days")


@eval_app.command("oracle")
def eval_oracle(users: int = typer.Option(100, "--users"), seed: int = typer.Option(11, "--seed")) -> None:
    """Static ranking vs the simulation's oracle over all eligible jobs (no logging policy)."""
    _setup()
    from app.db import session_scope
    from app.eval.oracle import run_oracle_check
    from app.eval.report import save_result

    with session_scope() as s:
        res = run_oracle_check(s, users=users, seed=seed)
    save_result("oracle", res)
    for name, m in res.get("aggregators", {}).items():
        typer.echo(
            f"{name:10} AUC={m['auc'] or 0:.3f} P@10={m['precision@10'] or 0:.3f} base={m['liked_share'] or 0:.3f}"
        )


@eval_app.command("congestion")
def eval_congestion() -> None:
    _setup()
    from app.db import session_scope
    from app.eval.congestion import run_congestion
    from app.eval.report import save_result

    with session_scope() as s:
        res = run_congestion(s)
    save_result("congestion", res)
    typer.echo(res)


@eval_app.command("latency")
def eval_latency() -> None:
    _setup()
    from app.db import session_scope
    from app.eval.latency import run_latency
    from app.eval.report import save_result

    with session_scope() as s:
        res = run_latency(s)
    save_result("latency", res)
    typer.echo(res)


@eval_app.command("report")
def eval_report() -> None:
    _setup()
    from app.db import session_scope
    from app.eval.report import write_report

    with session_scope() as s:
        typer.echo(f"wrote {write_report(s)}")


@app.command()
def bench() -> None:
    """Peak RSS of five steps, one subprocess at a time (spec 3)."""
    _setup()
    from app.bench import run_bench
    from app.eval.report import save_result

    res = run_bench()
    save_result("bench", res)
    for step in res["steps"]:
        flag = "ok " if step["within_budget"] and step["ok"] else "!! "
        failed = "" if step["ok"] else f"  FALHOU (código {step['returncode']}): {step['output_tail'][-200:]}"
        typer.echo(
            f"{flag}{step['name']:50} pico {step['peak_mb']:6.0f} MB  (orçamento {step['budget_mb']} MB)"
            f"  {step['seconds']} s{failed}"
        )


@eval_app.command("all")
def eval_all() -> None:
    """replay + oracle check + drift + congestion + latency + report (one at a time)."""
    eval_replay(400)
    eval_oracle(100, 11)
    eval_drift(30, 40, 7)
    eval_congestion()
    eval_latency()
    eval_report()


snapshot_app = typer.Typer(help="Congela e restaura as vagas (demo e avaliação reproduzíveis).", no_args_is_help=True)
app.add_typer(snapshot_app, name="snapshot")


@app.command()
def ingest(
    all_sources: bool = typer.Option(False, "--all", help="Every source with a connector."),
    source: list[str] = typer.Option([], "--source", help="greenhouse | lever | github (repeatable)."),
    board: list[str] = typer.Option([], "--board", help="Only these boards/repos (repeatable)."),
    accept_terms: bool = typer.Option(
        False, "--accept-terms", help="Run a source that is disabled because its terms are ambiguous."
    ),
    offline: bool = typer.Option(False, "--offline", help="Use only the local HTTP cache (no network)."),
    force: bool = typer.Option(False, "--force", help="Ignore the once-per-24h limit per board."),
) -> None:
    """Fetch real jobs from public sources (heuristic extraction). Cron-friendly: `encaixe ingest --all`."""
    _setup()
    if not all_sources and not source:
        typer.echo("use --all or --source")
        raise typer.Exit(code=2)
    from app.db import session_scope
    from app.ingest.run import ingest as run_ingest

    with session_scope() as s:
        reports = run_ingest(
            s,
            None if all_sources else list(source),
            list(board) or None,
            accept_terms=accept_terms,
            offline=offline,
            force=force,
        )
    for r in reports:
        run = r.run
        out = sum((r.details.get("out_of_scope") or {}).values())
        counts = (
            f" seen={run.n_seen} new={run.n_new} updated={run.n_updated} closed={run.n_closed} out_of_scope={out}"
            if run
            else ""
        )
        typer.echo(f"{r.source:10} {r.board:24} {r.status:7}{counts} {r.message}")
    if any(r.status == "ok" for r in reports):
        _vectors_and_projection()


@app.command()
def sources() -> None:
    """List job sources, whether they are on, and why."""
    from app.config import RULES

    for key, s in RULES.ingest.sources.items():
        state = "ligada" if s.enabled else "desligada"
        typer.echo(f"{key:15} {state:9} {s.disabled_reason or ''}")


@snapshot_app.command("save")
def snapshot_save(name: str) -> None:
    _setup()
    from app.db import session_scope
    from app.ingest.snapshot import save_snapshot

    with session_scope() as s:
        typer.echo(f"saved {save_snapshot(s, name)}")


@snapshot_app.command("load")
def snapshot_load(name: str) -> None:
    _setup()
    from app.db import session_scope
    from app.ingest.snapshot import load_snapshot

    with session_scope() as s:
        typer.echo(f"loaded: {load_snapshot(s, name)}")
    _vectors_and_projection()


@snapshot_app.command("list")
def snapshot_list() -> None:
    _setup()
    from app.ingest.snapshot import list_snapshots

    for name in list_snapshots():
        typer.echo(name)


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
