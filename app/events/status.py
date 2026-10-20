"""Application status, derived only from events (spec 4, 9.4).

enviada (candidate swipe right) → vista (recruiter impression, with date) → não avançou (recruiter swipe left,
with reason) or encaixe (both sides right). A new application after a rejection reopens it as enviada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlmodel import Session, col, select

from app.events import JUDGMENTS, match_for
from app.models import InteractionEvent, Job


@dataclass
class ApplicationStatus:
    job_id: int
    status: str  # sent | seen | not_advanced | matched
    applied_at: datetime
    seen_at: datetime | None = None
    decided_at: datetime | None = None
    reason: str | None = None
    timeline: list[dict] = field(default_factory=list)


def candidate_judgments(session: Session, candidate_id: int) -> list[InteractionEvent]:
    return list(
        session.exec(
            select(InteractionEvent)
            .where(
                InteractionEvent.actor_type == "candidate",
                InteractionEvent.actor_id == candidate_id,
                col(InteractionEvent.type).in_(JUDGMENTS),
            )
            .order_by(col(InteractionEvent.ts), col(InteractionEvent.id))
        ).all()
    )


def application_status(session: Session, candidate_id: int, job_id: int) -> ApplicationStatus | None:
    job = session.get(Job, job_id)
    if job is None or job.origin != "platform":
        return None
    mine = [e for e in candidate_judgments(session, candidate_id) if e.item_id == job_id]
    if not mine or mine[-1].type != "swipe_right":
        return None
    applied = next(e for e in reversed(mine) if e.type == "swipe_right")
    timeline = [{"event": "sent", "at": applied.ts.isoformat()}]
    rec_events = session.exec(
        select(InteractionEvent)
        .where(
            InteractionEvent.actor_type == "recruiter",
            InteractionEvent.item_type == "candidate",
            InteractionEvent.item_id == candidate_id,
            InteractionEvent.context_job_id == job_id,
        )
        .order_by(col(InteractionEvent.ts), col(InteractionEvent.id))
    ).all()
    st = ApplicationStatus(job_id=job_id, status="sent", applied_at=applied.ts, timeline=timeline)
    match = match_for(session, candidate_id, job_id)
    for e in rec_events:
        if e.ts < applied.ts:
            continue
        if e.type == "impression" and st.seen_at is None:
            st.seen_at = e.ts
            st.status = "seen"
            timeline.append({"event": "seen", "at": e.ts.isoformat()})
        elif e.type == "swipe_left":
            st.status, st.decided_at, st.reason = "not_advanced", e.ts, e.reason
            timeline.append({"event": "not_advanced", "at": e.ts.isoformat(), "reason": e.reason})
        elif e.type == "swipe_right":
            st.decided_at = e.ts
    if match is not None:
        st.status = "matched"
        st.decided_at = match.ts
        timeline.append({"event": "matched", "at": match.ts.isoformat()})
    elif any(e.type == "swipe_right" for e in rec_events if e.ts < applied.ts):
        # The recruiter liked the profile before the application: the application makes it a match (handled
        # by record_event); nothing else to show here.
        pass
    return st


def not_advanced_jobs(session: Session, candidate_id: int) -> dict[int, datetime]:
    """Platform jobs where the candidate's latest application did not advance → rejection time."""
    out: dict[int, datetime] = {}
    job_ids = {e.item_id for e in candidate_judgments(session, candidate_id) if e.type == "swipe_right"}
    for jid in job_ids:
        st = application_status(session, candidate_id, jid)
        if st is not None and st.status == "not_advanced" and st.decided_at is not None:
            out[jid] = st.decided_at
    return out
