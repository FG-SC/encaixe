"""The Histórico pillar of feedback-v1 (spec 8).

    w(e)  = 0.5^(Δt_days / HALF_LIFE) · GAMMA^(n_rev(e))
    fb(i) = [Σ_likes w·sim(i, item_e) − Σ_dislikes λ(e)·w·sim(i, item_e)] / Σ_{likes ∪ dislikes} w
    histórico(i) = fb(i) − company penalty (side C only)

``sim`` uses the item's vector AT EVENT TIME (the job version / candidate revision recorded on the event):
a candidate who evolved escapes an old rejection, because it penalizes whoever looks like the old profile.
``n_rev`` counts relevant revisions since the event: of the candidate actor (side C) or of the judged
candidate (side B). With fewer than K_MIN judgments the pillar does not exist for the actor.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from sqlmodel import Session, col, select

from app import clock
from app.config import RULES, Rules
from app.db import from_blob
from app.events import JUDGMENTS
from app.models import InteractionEvent, Job, JobVersion, ProfileRevision
from app.ranking.engine import PairEval


@dataclass
class Judgment:
    liked: bool
    weight: float
    lam: float  # λ for dislikes (0 for likes)
    vector: np.ndarray
    title: str
    company_id: int | None
    company_reason: bool
    item_id: int


def _relevant_revision_times(session: Session, candidate_id: int) -> list:
    return [
        r.ts
        for r in session.exec(
            select(ProfileRevision).where(
                ProfileRevision.candidate_id == candidate_id,
                ProfileRevision.kind == "relevant",
            )
        ).all()
    ]


def _weight(ts, now, n_rev: int, rules: Rules) -> float:  # type: ignore[no-untyped-def]
    days = max(0.0, (now - ts).total_seconds() / 86400)
    return float(0.5 ** (days / rules.feedback.half_life_days) * rules.feedback.gamma**n_rev)


def load_judgments(
    session: Session,
    actor_type: str,
    actor_id: int,
    context_job_id: int | None = None,
    rules: Rules = RULES,
    until=None,
) -> list[Judgment]:  # type: ignore[no-untyped-def]
    q = select(InteractionEvent).where(
        InteractionEvent.actor_type == actor_type,
        InteractionEvent.actor_id == actor_id,
        col(InteractionEvent.type).in_(JUDGMENTS),
    )
    if context_job_id is not None:
        q = q.where(InteractionEvent.context_job_id == context_job_id)
    if until is not None:
        q = q.where(InteractionEvent.ts < until)
    events = session.exec(q.order_by(col(InteractionEvent.ts))).all()
    now = until or clock.now()
    actor_revs = _relevant_revision_times(session, actor_id) if actor_type == "candidate" else []
    out: list[Judgment] = []
    for e in events:
        if e.type == "swipe_left" and e.reason in rules.feedback.ignored_recruiter and actor_type == "recruiter":
            continue  # "vaga preenchida ou pausada": says nothing about the candidate
        if actor_type == "candidate":
            n_rev = sum(1 for t in actor_revs if e.ts < t <= now)
            v = session.exec(
                select(JobVersion).where(JobVersion.job_id == e.item_id, JobVersion.version == (e.item_version or 1))
            ).first()
            if v is None or v.embedding is None:  # that version was never embedded: closest available
                v = session.exec(
                    select(JobVersion)
                    .where(JobVersion.job_id == e.item_id, JobVersion.embedding.is_not(None))  # type: ignore[union-attr]
                    .order_by(col(JobVersion.version).desc())
                ).first()
            job = session.get(Job, e.item_id)
            vec = from_blob(v.embedding) if v and v.embedding else None
            title, company_id = (job.title, job.company_id) if job else ("", None)
            lam = rules.feedback.lambda_candidate.get(e.reason or "none", 0.0)
        else:
            n_rev = sum(1 for t in _relevant_revision_times(session, e.item_id) if e.ts < t <= now)
            rev = session.get(ProfileRevision, e.item_revision_id) if e.item_revision_id else None
            vec = from_blob(rev.embedding) if rev and rev.embedding else None
            title = ((rev.snapshot or {}).get("headline") or "perfil") if rev else "perfil"
            company_id = None
            lam = rules.feedback.lambda_recruiter.get(e.reason or "none", 0.0)
        if vec is None:
            continue
        liked = e.type == "swipe_right"
        out.append(
            Judgment(
                liked,
                _weight(e.ts, now, n_rev, rules),
                0.0 if liked else lam,
                vec,
                title,
                company_id,
                (not liked) and e.reason == "company",
                e.item_id,
            )
        )
    return out


def history_values(
    judgments: list[Judgment], items: np.ndarray, item_company: list[int | None], rules: Rules = RULES
) -> tuple[np.ndarray, np.ndarray]:
    """(values (n,), contributions (n, m)) for item vectors ``items`` (n, d)."""
    m = len(judgments)
    if m == 0:
        return np.zeros(items.shape[0]), np.zeros((items.shape[0], 0))
    vecs = np.vstack([j.vector for j in judgments])
    if vecs.shape[1] != items.shape[1]:  # another embedding space: no comparable history
        return np.zeros(items.shape[0]), np.zeros((items.shape[0], 0))
    w = np.array([j.weight for j in judgments])
    coef = np.array([j.weight if j.liked else -j.lam * j.weight for j in judgments])
    total = w.sum() or 1.0
    sims = items @ vecs.T  # (n, m)
    contrib = sims * coef / total
    values = contrib.sum(axis=1)
    penalties = [(j.company_id, j.weight) for j in judgments if j.company_reason and j.company_id is not None]
    if penalties:
        for i, cid in enumerate(item_company):
            if cid is None:
                continue
            values[i] -= sum(rules.feedback.company_penalty * wt for c, wt in penalties if c == cid)
    return values, contrib


def make_history_fn(
    session: Session,
    actor_type: str,
    actor_id: int,
    context_job_id: int | None = None,
    rules: Rules = RULES,
    until=None,
) -> Callable[[list[PairEval]], None] | None:  # type: ignore[no-untyped-def]
    """None when the actor has fewer than K_MIN judgments (the pillar does not exist yet)."""
    if actor_type == "candidate":
        from app.jobs import ensure_job_vectors

        ensure_job_vectors(session)
    judgments = load_judgments(session, actor_type, actor_id, context_job_id, rules, until)
    if len(judgments) < rules.feedback.k_min:
        return None

    def apply(pairs: list[PairEval]) -> None:
        if not pairs:
            return
        if actor_type == "candidate":
            items = np.vstack([p.extra["job"].emb for p in pairs])
            companies = [p.extra["job"].company_id for p in pairs]
        else:
            items = np.vstack([p.extra["candidate"].emb for p in pairs])
            companies = [None for _ in pairs]
        values, contrib = history_values(judgments, items, companies, rules)
        for i, p in enumerate(pairs):
            p.history = float(values[i])
            if contrib.shape[1]:
                top = np.argsort(-np.abs(contrib[i]))[:2]
                p.history_top = [
                    {
                        "item_id": judgments[k].item_id,
                        "title": judgments[k].title,
                        "liked": judgments[k].liked,
                        "weight": round(float(judgments[k].weight), 3),
                        "text": (
                            f"parecida com {judgments[k].title}, que você "
                            if actor_type == "candidate"
                            else f"parecido com um perfil ({judgments[k].title}) que você "
                        )
                        + ("curtiu" if judgments[k].liked else "recusou"),
                    }
                    for k in top
                    if abs(contrib[i][k]) > 1e-6
                ]

    return apply
