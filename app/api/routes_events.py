"""POST /api/events: idempotent interaction events (one or a batch)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app import texts
from app.db import get_session
from app.events import EventError, record_event

router = APIRouter(prefix="/api", tags=["events"])


class EventIn(BaseModel):
    client_event_id: str
    actor_type: str
    actor_id: int
    item_type: str
    item_id: int
    context_job_id: int | None = None
    type: str
    reason: str | None = None
    session_id: str | None = None
    ranker_version: str | None = None
    slot: str | None = None
    propensity: float | None = None
    rank_position: int | None = None
    rank_sum: float | None = None
    rank_detail: dict[str, Any] | None = None


def _out(res) -> dict:  # type: ignore[no-untyped-def]
    ev = res.event
    return {
        "event_id": ev.id,
        "client_event_id": ev.client_event_id,
        "created": res.created,
        "type": ev.type,
        "impression_auto_created": res.impression_auto_created,
        "match": None
        if res.match is None
        else {
            "id": res.match.id,
            "job_id": res.match.job_id,
            "candidate_id": res.match.candidate_id,
            "title": texts.MATCH_TITLE,
        },
    }


@router.post("/events")
def post_events(body: EventIn | list[EventIn], session: Session = Depends(get_session)) -> dict:
    events = body if isinstance(body, list) else [body]
    results = []
    try:
        for e in events:
            results.append(_out(record_event(session, e.model_dump())))
        session.commit()
    except EventError as exc:
        session.rollback()
        raise HTTPException(exc.status, exc.message) from exc
    return {"results": results}
