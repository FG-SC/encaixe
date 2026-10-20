"""Unbiased check of the static ranking against the simulation's oracle (no logging policy).

The replay only compares jobs that the served ranker chose to show, so it inherits that policy's selection:
inside a narrow top band, a job that made it with a lower static score did so through its history score, which
can turn the static AUC upside down. Here fresh simulated users (in memory, no database writes) are ranked
over ALL eligible open jobs, and every job is labelled by the oracle without noise.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
from sqlmodel import Session

from app import clock
from app.eval.drift import _features
from app.ranking.engine import rank
from app.ranking.index import job_index
from app.ranking.service import pairs_for_candidate
from app.synth.personas import make_personas
from app.synth.simulate import LIKE_THRESHOLD, utility

AGGREGATORS = ("rank_sum", "rrf", "weighted")


def position_auc(liked: np.ndarray) -> float | None:
    """P(a liked job is listed above a disliked one), for a list in ranking order."""
    pos = np.arange(len(liked))
    lp, dp = pos[liked], pos[~liked]
    if not len(lp) or not len(dp):
        return None
    return float(np.sum(len(dp) - np.searchsorted(dp, lp, side="right")) / (len(lp) * len(dp)))


def run_oracle_check(session: Session, users: int = 100, seed: int = 11) -> dict:
    idx = job_index(session)
    if not idx.jobs:
        return {"error": "sem vagas abertas"}
    today = clock.today()
    personas = make_personas(users, seed, today, today - timedelta(days=30), 30, revision_share=0.0)
    stats: dict[str, dict[str, list[float]]] = {a: {"auc": [], "p10": [], "base": []} for a in AGGREGATORS}
    for persona in personas:
        c = _features(persona.profile, today)
        pairs = pairs_for_candidate(c, idx.jobs, idx.emb, idx.title_emb)
        for agg in AGGREGATORS:
            result = rank(pairs, side="candidate", ranker="static-v1", aggregator=agg)
            if not result.items:
                continue
            liked = np.array(
                [utility(persona.taste.domains, c, it.extra["job"], it.req) >= LIKE_THRESHOLD for it in result.items]
            )
            a = position_auc(liked)
            if a is not None:
                stats[agg]["auc"].append(a)
            stats[agg]["p10"].append(float(liked[:10].mean()))
            stats[agg]["base"].append(float(liked.mean()))

    def mean(xs: list[float]) -> float | None:
        return float(np.mean(xs)) if xs else None

    return {
        "users": users,
        "seed": seed,
        "jobs": len(idx.jobs),
        "aggregators": {
            a: {"auc": mean(s["auc"]), "precision@10": mean(s["p10"]), "liked_share": mean(s["base"])}
            for a, s in stats.items()
        },
        "evaluated_at": clock.now().isoformat(),
    }
