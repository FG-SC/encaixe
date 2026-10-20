"""Ingestion runs (spec 5.1): fetch → heuristic extraction → upsert, dedup, last_seen, IngestRun, closing.

- Dedup by (source, source_id) and, across sources, by normalized company + normalized title + city.
- A job missing from RULES.ingest.close_after_missed_runs consecutive runs of its board is closed.
- Batch ingestion is always heuristic; the LLM upgrade happens later, in the background (spec 6).
- A disabled source runs only when the operator explicitly accepts its terms (``accept_terms``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from sqlmodel import Session, col, select

from app import clock
from app.companies import normalize
from app.config import RULES
from app.extraction.job import RawPosting, extract_job, normalized_title
from app.ingest.connectors import github_postings, greenhouse_postings, lever_postings
from app.ingest.http import HttpClient, SourceUnavailable
from app.jobs import bump_jobs_version, upsert_job
from app.models import Company, IngestRun, Job

log = logging.getLogger(__name__)


@dataclass
class RunReport:
    source: str
    board: str
    status: str  # ok | skipped | error
    message: str = ""
    run: IngestRun | None = None
    details: dict = field(default_factory=dict)


def fetch_board(client: HttpClient, source: str, board: str) -> list[RawPosting]:
    rules = RULES.ingest.sources[source]
    if source == "greenhouse":
        url = rules.endpoint.format(token=board)
        return greenhouse_postings(board, client.get_json(url))  # type: ignore[arg-type]
    if source == "lever":
        url = rules.endpoint.format(company=board)
        return lever_postings(board, client.get_json(url))  # type: ignore[arg-type]
    if source == "github":
        postings: list[RawPosting] = []
        for page in range(1, 4):  # at most 300 open issues per repo per run (60 req/h budget)
            url = rules.endpoint.format(repo=board) + f"&page={page}"
            batch = client.get_json(url, {"Accept": "application/vnd.github+json"})
            postings += github_postings(board, batch)  # type: ignore[arg-type]
            if not isinstance(batch, list) or len(batch) < 100:
                break
        return postings
    raise ValueError(f"no connector for {source}")


def board_prefix(source: str, board: str) -> str:
    return f"{board}#" if source == "github" else f"{board}:"


def _dedup_key(session: Session, company_id: int | None, title: str, city_id: str | None) -> tuple:
    name = ""
    if company_id is not None:
        c = session.get(Company, company_id)
        name = c.name_normalized if c else ""
    return (name, normalized_title(title), city_id or "")


def ingest_board(session: Session, source: str, board: str, client: HttpClient) -> RunReport:
    try:
        postings = fetch_board(client, source, board)
    except SourceUnavailable as exc:
        run = IngestRun(source=source, board=board, ts=clock.now(), error=str(exc)[:500])
        session.add(run)
        return RunReport(source, board, "error", str(exc), run)
    prefix = board_prefix(source, board)
    others: dict[tuple, int] = {}
    for j in session.exec(select(Job).where(Job.status == "open", Job.source != source, Job.origin == "market")):
        others[_dedup_key(session, j.company_id, j.title, j.city_id)] = j.id  # type: ignore[assignment]
    seen: set[str] = set()
    n_new = n_updated = n_dup = 0
    for raw in postings:
        sid = raw.source_id or ""
        seen.add(sid)
        draft = extract_job(raw)
        existing = session.exec(select(Job).where(Job.source == source, Job.source_id == sid)).first()
        if existing is None:
            company = normalize(draft.company)
            key = (company, normalized_title(draft.title), draft.city_id or "")
            if company and key in others:
                n_dup += 1
                continue
        res = upsert_job(session, draft, source=source, source_id=sid, origin="market", url=raw.url, labels=raw.labels)
        n_new += res.status == "new"
        n_updated += res.status in ("updated", "reopened")
    n_closed = 0
    for job in session.exec(
        select(Job).where(Job.source == source, col(Job.source_id).startswith(prefix), Job.status == "open")
    ).all():
        if job.source_id in seen:
            continue
        job.missed_runs += 1
        if job.missed_runs >= RULES.ingest.close_after_missed_runs:
            job.status = "closed"
            n_closed += 1
        session.add(job)
    if n_closed:
        bump_jobs_version(session)
    run = IngestRun(
        source=source,
        board=board,
        ts=clock.now(),
        n_seen=len(postings),
        n_new=n_new,
        n_updated=n_updated,
        n_closed=n_closed,
    )
    session.add(run)
    session.flush()
    return RunReport(source, board, "ok", run=run, details={"duplicates_across_sources": n_dup})


def ran_recently(session: Session, source: str, board: str) -> bool:
    limit = RULES.ingest.sources[source].max_runs_per_day
    if not limit:
        return False
    since = clock.now() - timedelta(days=1)
    n = len(
        session.exec(
            select(IngestRun.id).where(
                IngestRun.source == source, IngestRun.board == board, IngestRun.ts > since, IngestRun.error.is_(None)
            )
        ).all()
    )  # type: ignore[union-attr]
    return n >= limit


def ingest(
    session: Session,
    sources: list[str] | None = None,
    boards: list[str] | None = None,
    *,
    accept_terms: bool = False,
    offline: bool = False,
    force: bool = False,
    transport=None,  # type: ignore[no-untyped-def]
    cache_dir=None,
) -> list[RunReport]:  # type: ignore[no-untyped-def]
    reports: list[RunReport] = []
    with_connector = ("greenhouse", "lever", "github")
    for source in sources or list(with_connector):
        rules = RULES.ingest.sources.get(source)
        if rules is None or source not in with_connector:
            reports.append(RunReport(source, "-", "skipped", "fonte sem conector no MVP"))
            continue
        if not rules.enabled and not accept_terms:
            reports.append(RunReport(source, "-", "skipped", f"fonte desligada: {rules.disabled_reason}"))
            continue
        client = HttpClient(source, offline=offline, transport=transport, cache_dir=cache_dir)
        try:
            for board in boards or list(rules.repos if source == "github" else rules.boards):
                if not force and not offline and ran_recently(session, source, board):
                    reports.append(RunReport(source, board, "skipped", "já sincronizado nas últimas 24 h"))
                    continue
                reports.append(ingest_board(session, source, board, client))
                session.commit()
        finally:
            client.close()
    return reports
