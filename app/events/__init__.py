"""Interaction events (spec 4): append-only, idempotent, enough to rebuild what each person saw and why.

- A known ``client_event_id`` returns the original event and writes nothing.
- An impression is unique per (actor, item, session, ranker version); a swipe without a prior impression in
  that session records the impression first ("every swipe implies an impression").
- Reasons are fixed enums, no free text. Rejecting an applicant without a reason is refused (422).
- A match is born when the latest judgments of both sides are "right", in any order.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlmodel import Session, col, select

from app import clock
from app.config import RULES, rules_hash
from app.models import Candidate, InteractionEvent, Job, Match, Recruiter

JUDGMENTS = ("swipe_right", "swipe_left")
_NS = uuid.UUID("6f0f4d4e-3c1b-4c55-9a51-8c9e2f1d7a10")


class EventError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class EventResult:
    event: InteractionEvent
    created: bool
    impression_auto_created: bool = False
    match: Match | None = None


def _latest_judgment(
    session: Session, actor_type: str, actor_id: int, item_type: str, item_id: int, context_job_id: int | None = None
) -> InteractionEvent | None:
    q = select(InteractionEvent).where(
        InteractionEvent.actor_type == actor_type,
        InteractionEvent.actor_id == actor_id,
        InteractionEvent.item_type == item_type,
        InteractionEvent.item_id == item_id,
        col(InteractionEvent.type).in_(JUDGMENTS),
    )
    if context_job_id is not None:
        q = q.where(InteractionEvent.context_job_id == context_job_id)
    return session.exec(q.order_by(col(InteractionEvent.ts).desc(), col(InteractionEvent.id).desc())).first()


def candidate_latest_on_job(session: Session, candidate_id: int, job_id: int) -> InteractionEvent | None:
    return _latest_judgment(session, "candidate", candidate_id, "job", job_id)


def recruiter_latest_on_candidate(session: Session, job_id: int, candidate_id: int) -> InteractionEvent | None:
    job = session.get(Job, job_id)
    if job is None or job.owner_recruiter_id is None:
        return None
    return _latest_judgment(session, "recruiter", job.owner_recruiter_id, "candidate", candidate_id, job_id)


def is_applicant(session: Session, candidate_id: int, job_id: int) -> bool:
    """Applied = the candidate's latest judgment on this platform job is a swipe right."""
    ev = candidate_latest_on_job(session, candidate_id, job_id)
    return ev is not None and ev.type == "swipe_right"


def applicants(session: Session, job_id: int) -> set[int]:
    rows = session.exec(
        select(InteractionEvent.actor_id)
        .where(
            InteractionEvent.actor_type == "candidate",
            InteractionEvent.item_type == "job",
            InteractionEvent.item_id == job_id,
            col(InteractionEvent.type).in_(JUDGMENTS),
        )
        .distinct()
    ).all()
    return {cid for cid in rows if is_applicant(session, cid, job_id)}


def _validate(session: Session, data: dict) -> None:
    actor_type, item_type, typ = data["actor_type"], data["item_type"], data["type"]
    if typ not in ("impression", "swipe_right", "swipe_left", "open_detail"):
        raise EventError(422, f"tipo de evento inválido: {typ}")
    if data.get("slot") not in (None, "ranked", "explore", "direct"):
        raise EventError(422, "slot inválido")
    if actor_type == "candidate":
        if item_type != "job" or session.get(Candidate, data["actor_id"]) is None:
            raise EventError(422, "candidato julga vagas")
        job = session.get(Job, data["item_id"])
        if job is None:
            raise EventError(404, "vaga não encontrada")
        if data.get("reason") is not None and (typ != "swipe_left" or data["reason"] not in RULES.reasons.candidate):
            raise EventError(422, "motivo inválido para o candidato")
    elif actor_type == "recruiter":
        if item_type != "candidate" or session.get(Recruiter, data["actor_id"]) is None:
            raise EventError(422, "recrutador julga candidatos")
        job = session.get(Job, data.get("context_job_id") or -1)
        if job is None or job.owner_recruiter_id != data["actor_id"]:
            raise EventError(422, "o recrutador só avalia candidatos nas próprias vagas")
        if session.get(Candidate, data["item_id"]) is None:
            raise EventError(404, "candidato não encontrado")
        reason = data.get("reason")
        if reason is not None and (typ != "swipe_left" or reason not in RULES.reasons.recruiter):
            raise EventError(422, "motivo inválido para o recrutador")
        if (
            typ == "swipe_left"
            and reason is None
            and RULES.reasons.recruiter_required_for_applicants
            and is_applicant(session, data["item_id"], job.id)
        ):  # type: ignore[arg-type]
            raise EventError(422, "Recusar uma candidatura exige um motivo da lista.")
    else:
        raise EventError(422, "actor_type inválido")


def _fill_versions(session: Session, ev: InteractionEvent) -> None:
    if ev.actor_type == "candidate":
        cand = session.get(Candidate, ev.actor_id)
        ev.actor_revision_id = cand.current_revision_id if cand else None
        job = session.get(Job, ev.item_id)
        ev.item_version = job.version if job else None
    else:
        cand = session.get(Candidate, ev.item_id)
        ev.item_revision_id = cand.current_revision_id if cand else None
        job = session.get(Job, ev.context_job_id) if ev.context_job_id else None
        ev.item_version = job.version if job else None


_FIELDS = (
    "client_event_id",
    "actor_type",
    "actor_id",
    "item_type",
    "item_id",
    "context_job_id",
    "type",
    "reason",
    "session_id",
    "ranker_version",
    "slot",
    "propensity",
    "rank_position",
    "rank_sum",
    "rank_detail",
)


def _existing_impression(session: Session, ev: InteractionEvent) -> InteractionEvent | None:
    return session.exec(
        select(InteractionEvent).where(
            InteractionEvent.actor_type == ev.actor_type,
            InteractionEvent.actor_id == ev.actor_id,
            InteractionEvent.item_type == ev.item_type,
            InteractionEvent.item_id == ev.item_id,
            InteractionEvent.type == "impression",
            InteractionEvent.session_id == ev.session_id,
            InteractionEvent.ranker_version == ev.ranker_version,
            InteractionEvent.context_job_id == ev.context_job_id
            if ev.context_job_id is not None
            else InteractionEvent.context_job_id.is_(None),  # type: ignore[union-attr]
        )
    ).first()


def record_event(session: Session, data: dict) -> EventResult:
    """Validate, deduplicate and append one event; create a match when both sides said yes."""
    cid = data.get("client_event_id") or str(uuid.uuid4())
    existing = session.exec(select(InteractionEvent).where(InteractionEvent.client_event_id == cid)).first()
    if existing is not None:
        return EventResult(existing, created=False)
    _validate(session, data)
    ev = InteractionEvent(**{k: data.get(k) for k in _FIELDS if k != "client_event_id"}, client_event_id=cid)
    if ev.slot == "direct":
        ev.rank_position = None
        ev.propensity = None
    elif ev.slot in ("ranked", None) and ev.propensity is None and ev.type != "open_detail":
        ev.propensity = 1.0
    ev.ts = data.get("ts") or clock.now()
    ev.rules_hash = rules_hash()
    _fill_versions(session, ev)
    if ev.type == "impression":
        prior = _existing_impression(session, ev)
        if prior is not None:
            return EventResult(prior, created=False)
    auto = False
    if ev.type in JUDGMENTS and _existing_impression(session, ev) is None:
        imp = InteractionEvent(
            **{k: getattr(ev, k) for k in _FIELDS if k not in ("client_event_id", "type", "reason")},
            client_event_id=str(uuid.uuid5(_NS, cid + ":impression")),
            type="impression",
            ts=ev.ts,
            rules_hash=ev.rules_hash,
            actor_revision_id=ev.actor_revision_id,
            item_revision_id=ev.item_revision_id,
            item_version=ev.item_version,
        )
        session.add(imp)
        auto = True
    session.add(ev)
    session.flush()
    match = _maybe_match(session, ev) if ev.type == "swipe_right" else None
    return EventResult(ev, created=True, impression_auto_created=auto, match=match)


def _maybe_match(session: Session, ev: InteractionEvent) -> Match | None:
    if ev.actor_type == "candidate":
        job = session.get(Job, ev.item_id)
        if job is None or job.origin != "platform":
            return None
        candidate_id, job_id = ev.actor_id, job.id
        other = recruiter_latest_on_candidate(session, job_id, candidate_id)  # type: ignore[arg-type]
    else:
        candidate_id, job_id = ev.item_id, ev.context_job_id
        other = candidate_latest_on_job(session, candidate_id, job_id)  # type: ignore[arg-type]
        job = session.get(Job, job_id)
    if other is None or other.type != "swipe_right" or job is None:
        return None
    existing = session.exec(select(Match).where(Match.candidate_id == candidate_id, Match.job_id == job_id)).first()
    if existing is not None:
        return existing
    match = Match(candidate_id=candidate_id, job_id=job_id, recruiter_id=job.owner_recruiter_id, ts=ev.ts)
    session.add(match)
    session.flush()
    return match


def match_for(session: Session, candidate_id: int, job_id: int) -> Match | None:
    return session.exec(select(Match).where(Match.candidate_id == candidate_id, Match.job_id == job_id)).first()
