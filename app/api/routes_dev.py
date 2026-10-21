"""Dev panel: clock, served ranker, embeddings and LLM status, counts."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlmodel import Session, func, select

from app import clock
from app.db import get_session
from app.embeddings import embedding_status
from app.models import Account, Candidate, IngestRun, InteractionEvent, Job, Match, Recruiter
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


class DevLoginIn(BaseModel):
    email: str | None = None
    candidate_id: int | None = None
    recruiter_id: int | None = None


@router.post("/login")
def dev_login(body: DevLoginIn, response: Response, session: Session = Depends(get_session)) -> dict:
    """Log in as any persona of the local demo, without e-mail (this router is never mounted in production)."""
    from app.auth import account_by_email, me_payload, normalize_email, open_session, set_session_cookie
    from app.config import RULES

    account = None
    if body.candidate_id is not None:
        if session.get(Candidate, body.candidate_id) is None:
            raise HTTPException(404, "candidato não encontrado")
        account = session.exec(select(Account).where(Account.candidate_id == body.candidate_id)).first()
        email = f"candidato{body.candidate_id}@demo.invalid"
    elif body.recruiter_id is not None:
        if session.get(Recruiter, body.recruiter_id) is None:
            raise HTTPException(404, "recrutador não encontrado")
        account = session.exec(select(Account).where(Account.recruiter_id == body.recruiter_id)).first()
        email = f"recrutador{body.recruiter_id}@demo.invalid"
    elif body.email:
        email = normalize_email(body.email)
        account = account_by_email(session, email)
    else:
        raise HTTPException(422, "informe email, candidate_id ou recruiter_id")
    if account is None:
        account = account_by_email(session, email) or Account(email=email)
        account.candidate_id = body.candidate_id if body.candidate_id is not None else account.candidate_id
        account.recruiter_id = body.recruiter_id if body.recruiter_id is not None else account.recruiter_id
    account.terms_version, account.terms_accepted_at = RULES.auth.terms_version, clock.real_now()
    session.add(account)
    session.flush()
    set_session_cookie(response, open_session(session, account))
    session.commit()
    return me_payload(session, account)
