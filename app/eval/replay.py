"""Replay (spec 13): the recorded history in chronological order, session by session.

For each candidate session, rebuild what was known BEFORE it (the candidate revision recorded on the events,
judgments strictly earlier), rank every open job with each variant and record where the judged items landed.
Approximation (stated in the report): the job set is today's open jobs, not the set open at that time.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict

import numpy as np
from sqlmodel import Session, col, select

from app.config import RULES, Rules
from app.db import from_blob
from app.eval.metrics import auc, mrr, ndcg_single, recall_at
from app.models import Candidate, InteractionEvent, Job, JobVersion, ProfileRevision
from app.ranking.engine import rank
from app.ranking.feedback import Judgment, history_values
from app.ranking.index import features_for_revision, job_index
from app.ranking.service import pairs_for_candidate


def variants() -> dict[str, tuple[str, str, Rules]]:
    """name → (ranker, aggregator, rules)."""
    fb = RULES.feedback
    no_decay = dataclasses.replace(RULES, feedback=dataclasses.replace(fb, half_life_days=1e9))
    no_rev = dataclasses.replace(RULES, feedback=dataclasses.replace(fb, gamma=1.0))
    return {
        "static-v1 (rank_sum)": ("static-v1", "rank_sum", RULES),
        "static-v1 (rrf)": ("static-v1", "rrf", RULES),
        "static-v1 (weighted)": ("static-v1", "weighted", RULES),
        "feedback-v1": ("feedback-v1", "rank_sum", RULES),
        "feedback-v1 sem decaimento": ("feedback-v1", "rank_sum", no_decay),
        "feedback-v1 sem desconto por revisão": ("feedback-v1", "rank_sum", no_rev),
    }


@dataclasses.dataclass
class _Past:
    ts: object
    liked: bool
    reason: str | None
    vector: np.ndarray
    company_id: int | None
    item_id: int


def _judgment_vectors(session: Session, events: list[InteractionEvent]) -> dict[int, tuple[np.ndarray, int | None]]:
    out: dict[int, tuple[np.ndarray, int | None]] = {}
    for e in events:
        if e.id in out:
            continue
        v = session.exec(
            select(JobVersion).where(JobVersion.job_id == e.item_id, JobVersion.version == (e.item_version or 1))
        ).first()
        if v is None or v.embedding is None:
            v = session.exec(
                select(JobVersion)
                .where(JobVersion.job_id == e.item_id, JobVersion.embedding.is_not(None))  # type: ignore[union-attr]
                .order_by(col(JobVersion.version).desc())
            ).first()
        job = session.get(Job, e.item_id)
        if v is not None and v.embedding is not None:
            out[e.id] = (from_blob(v.embedding), job.company_id if job else None)  # type: ignore[index,assignment]
    return out


def run_replay(session: Session, max_sessions: int = 400, seed: int = 42) -> dict:
    idx = job_index(session)
    events = session.exec(
        select(InteractionEvent)
        .where(
            InteractionEvent.actor_type == "candidate",
            col(InteractionEvent.type).in_(("swipe_right", "swipe_left")),
        )
        .order_by(col(InteractionEvent.ts), col(InteractionEvent.id))
    ).all()
    vectors = _judgment_vectors(session, events)
    by_actor: dict[int, list[InteractionEvent]] = defaultdict(list)
    for e in events:
        by_actor[e.actor_id].append(e)
    sessions: list[tuple[int, str, list[InteractionEvent]]] = []
    for actor, evs in by_actor.items():
        grouped: dict[str, list[InteractionEvent]] = defaultdict(list)
        for e in evs:
            grouped[e.session_id or f"t{e.ts.date()}"].append(e)
        for sid, es in grouped.items():
            sessions.append((actor, sid, es))
    sessions.sort(key=lambda x: x[2][0].ts)
    if len(sessions) > max_sessions:
        rng = np.random.default_rng(seed)
        keep = sorted(rng.choice(len(sessions), size=max_sessions, replace=False))
        sessions = [sessions[i] for i in keep]
    revs_relevant: dict[int, list] = defaultdict(list)
    for r in session.exec(select(ProfileRevision).where(ProfileRevision.kind == "relevant")).all():
        revs_relevant[r.candidate_id].append(r.ts)
    per_variant: dict[str, dict[str, list]] = {name: {"ranks": [], "auc": []} for name in variants()}
    n_used = 0
    for actor, _sid, es in sessions:
        start = es[0].ts
        rev_id = es[0].actor_revision_id
        rev = session.get(ProfileRevision, rev_id) if rev_id else None
        cand = session.get(Candidate, actor)
        if rev is None or rev.embedding is None or cand is None:
            continue
        c = features_for_revision(session, cand, rev)
        past = [e for e in by_actor[actor] if e.ts < start and e.id in vectors]
        n_used += 1
        for name, (ranker, aggregator, rules) in variants().items():
            pairs = pairs_for_candidate(c, idx.jobs, idx.emb, idx.title_emb)
            if ranker == "feedback-v1" and len(past) >= rules.feedback.k_min:
                judgments = []
                for e in past:
                    vec, company = vectors[e.id]
                    days = max(0.0, (start - e.ts).total_seconds() / 86400)
                    n_rev = sum(1 for t in revs_relevant[actor] if e.ts < t <= start)
                    w = 0.5 ** (days / rules.feedback.half_life_days) * rules.feedback.gamma**n_rev
                    liked = e.type == "swipe_right"
                    lam = 0.0 if liked else rules.feedback.lambda_candidate.get(e.reason or "none", 0.0)
                    judgments.append(
                        Judgment(liked, w, lam, vec, "", company, (not liked) and e.reason == "company", e.item_id)
                    )
                items = np.vstack([p.extra["job"].emb for p in pairs])
                values, _ = history_values(judgments, items, [p.extra["job"].company_id for p in pairs], rules)
                for i, p in enumerate(pairs):
                    p.history = float(values[i])
            result = rank(pairs, side="candidate", ranker=ranker, aggregator=aggregator, rules=rules)
            pos = {it.item_id: it.order for it in result.items}
            n = len(result.items) + 1  # filtered or missing → after the list
            liked = [pos.get(e.item_id, n) for e in es if e.type == "swipe_right"]
            disliked = [pos.get(e.item_id, n) for e in es if e.type == "swipe_left"]
            per_variant[name]["ranks"] += liked
            a = auc(liked, disliked)
            if a is not None:
                per_variant[name]["auc"].append(a)
    table = {}
    for name, d in per_variant.items():
        ranks = d["ranks"]
        table[name] = {
            "liked_items": len(ranks),
            "mrr": mrr(ranks),
            "recall@5": recall_at(ranks, 5),
            "recall@10": recall_at(ranks, 10),
            "recall@20": recall_at(ranks, 20),
            "ndcg@10": ndcg_single(ranks, 10),
            "auc": float(np.mean(d["auc"])) if d["auc"] else None,
        }
    return {
        "sessions": n_used,
        "events": len(events),
        "variants": table,
        "note": "the job set is today's open jobs (approximation) and the history is mostly synthetic",
    }
