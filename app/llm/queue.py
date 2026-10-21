"""Background LLM upgrade of jobs (spec 6): an asyncio worker; outside onboarding the LLM never blocks a request.

Market jobs entering someone's top RULES.llm.background_top_n are queued; the worker re-extracts them with the
LLM (rate-limited, cached) and updates the job and its provenance ``method``. The posting version does not
change (decision #13). Only jobs: profiles are never touched by the LLM after they are saved.
"""

from __future__ import annotations

import asyncio
import logging

from sqlmodel import Session

from app.config import RULES
from app.db import session_scope
from app.extraction.job import RawPosting
from app.jobs import company_name, job_draft, reextract_job
from app.llm.status import _load as _load_status
from app.llm.status import update_status
from app.models import Job

log = logging.getLogger(__name__)

_loop: asyncio.AbstractEventLoop | None = None
_queue: asyncio.Queue[int] | None = None
_pending: set[int] = set()


def enqueue(session: Session, job_ids: list[int]) -> int:
    """Queue market jobs for a background re-read, at most RULES.llm.background_daily_cap per day."""
    if _loop is None or _queue is None:
        return 0
    room = RULES.llm.background_daily_cap - int(_load_status(session).get("background_today", 0))
    n = 0
    for jid in job_ids:
        if n >= room:
            break
        job = session.get(Job, jid)
        if job is None or job.origin != "market" or job.extraction_method == "llm" or jid in _pending:
            continue
        _pending.add(jid)
        _loop.call_soon_threadsafe(_queue.put_nowait, jid)
        n += 1
    if n:
        update_status(queue_size=len(_pending), background_today_inc=n)
    return n


def upgrade_job(job_id: int) -> bool:
    """Blocking: one LLM re-extraction of a stored job. Returns True when the job was upgraded."""
    from app.llm.client import LlmError, llm_extract_job

    with session_scope() as s:
        job = s.get(Job, job_id)
        if job is None or job.extraction_method == "llm":
            return False
        company = company_name(s, job.company_id)
        heuristic = job_draft(job, company)
        raw = RawPosting(
            title=job.title,
            description=job.description_text,
            company=company,
            location_text=job.location_text,
            source=job.source,
            source_id=job.source_id,
            url=job.url,
        )
        try:
            draft = llm_extract_job(raw, heuristic, background=True)
        except LlmError as exc:
            log.info("background LLM upgrade of job %s skipped: %s", job_id, exc.reason)
            return False
        reextract_job(s, job, draft)
        return True


async def _worker() -> None:
    assert _queue is not None
    while True:
        jid = await _queue.get()
        try:
            await asyncio.to_thread(upgrade_job, jid)
        except Exception:  # never let the worker die
            log.exception("background LLM upgrade failed for job %s", jid)
        finally:
            _pending.discard(jid)
            update_status(queue_size=len(_pending))
            _queue.task_done()


_task: asyncio.Task | None = None


async def start_worker() -> None:
    global _loop, _queue, _task
    _loop = asyncio.get_running_loop()
    _queue = asyncio.Queue()
    _task = asyncio.create_task(_worker())


async def stop_worker() -> None:
    global _loop, _queue, _task
    if _task is not None:
        _task.cancel()
    _loop, _queue, _task = None, None, None
    _pending.clear()
