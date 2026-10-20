"""Background LLM upgrade of market jobs that enter someone's top 20 (never blocks a request)."""

from __future__ import annotations

from sqlmodel import Session

from app.config import RULES, get_settings


def enqueue_top_market_jobs(session: Session, job_ids: list[int]) -> int:
    """Queue the first RULES.llm.background_top_n market jobs of a deck for an LLM upgrade."""
    if not get_settings().llm_enabled:
        return 0
    try:
        from app.llm.queue import enqueue
    except ModuleNotFoundError:
        return 0
    return enqueue(session, job_ids[: RULES.llm.background_top_n])
