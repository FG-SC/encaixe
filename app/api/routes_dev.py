"""Dev panel: clock, served ranker, embeddings and LLM status, counts."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, func, select

from app import clock
from app.db import get_session
from app.embeddings import embedding_status
from app.models import Candidate, IngestRun, InteractionEvent, Job, Match, Recruiter
from app.ranking.deck import served, set_served

router = APIRouter(prefix="/api/dev", tags=["dev"])


def _count(session: Session, model, *where) -> int:  # type: ignore[no-untyped-def]
    q = select(func.count()).select_from(model)
    for w in where:
        q = q.where(w)
    return int(session.exec(q).one())


@router.get("/status")
def status(session: Session = Depends(get_session)) -> dict:
    ranker, aggregator = served(session)
    from app.llm.status import llm_status

    runs = session.exec(select(IngestRun).order_by(IngestRun.ts.desc()).limit(10)).all()  # type: ignore[attr-defined]
    return {
        "clock": {"now": clock.now().isoformat(), "offset_days": clock.get_offset_days()},
        "ranker": ranker,
        "aggregator": aggregator,
        "embeddings": embedding_status(),
        "llm": llm_status(session),
        "counts": {
            "jobs_open": _count(session, Job, Job.status == "open"),
            "jobs_platform": _count(session, Job, Job.origin == "platform"),
            "candidates": _count(session, Candidate),
            "candidates_real": _count(session, Candidate, Candidate.synthetic == False),  # noqa: E712
            "recruiters": _count(session, Recruiter),
            "events": _count(session, InteractionEvent),
            "matches": _count(session, Match),
        },
        "ingest_runs": [r.model_dump(mode="json") for r in runs],
    }


class ClockIn(BaseModel):
    offset_days: float | None = None
    advance_days: float | None = None


@router.post("/clock")
def set_clock(body: ClockIn) -> dict:
    try:
        if body.offset_days is not None:
            clock.set_offset_days(body.offset_days)
        if body.advance_days is not None:
            clock.advance_days(body.advance_days)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"now": clock.now().isoformat(), "offset_days": clock.get_offset_days()}


class RankerIn(BaseModel):
    ranker: str | None = None
    aggregator: str | None = None


@router.post("/ranker")
def set_ranker(body: RankerIn, session: Session = Depends(get_session)) -> dict:
    try:
        ranker, aggregator = set_served(session, body.ranker, body.aggregator)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    session.commit()
    return {"ranker": ranker, "aggregator": aggregator}
