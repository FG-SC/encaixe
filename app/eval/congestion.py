"""Congestion (spec 1.4 #2, 13): measured, not optimized.

A job hires one person. If every recruiter gets the same top 5, those five drown and the rest never show up.
For every open platform job, take its top-5 candidates and look at how exposure concentrates.
"""

from __future__ import annotations

from collections import Counter

import numpy as np
from sqlmodel import Session, select

from app.eval.metrics import gini
from app.models import Job
from app.ranking.service import rank_for_job

TOP = 5


def run_congestion(session: Session, top: int = TOP, ranker: str = "static-v1") -> dict:
    jobs = session.exec(select(Job).where(Job.origin == "platform", Job.status == "open")).all()
    exposure: Counter[int] = Counter()
    eligible_union: set[int] = set()
    lists = 0
    for job in jobs:
        result = rank_for_job(session, job.id, ranker=ranker)  # type: ignore[arg-type]
        eligible_union |= {it.item_id for it in result.items}
        for it in result.items[:top]:
            exposure[it.item_id] += 1
        lists += 1
    slots = sum(exposure.values())
    pool = len(eligible_union)
    counts = [exposure.get(c, 0) for c in eligible_union]
    # expected distinct candidates if each list drew its top-5 uniformly from the pool (independent lists)
    expected_random = pool * (1 - (1 - min(1.0, top / pool)) ** lists) if pool else 0.0
    return {
        "platform_jobs": lists,
        "top": top,
        "slots": slots,
        "distinct_candidates": len(exposure),
        "expected_distinct_if_random": round(expected_random, 1),
        "eligible_pool": pool,
        "max_exposure": max(exposure.values()) if exposure else 0,
        "share_of_slots_top1pct": _share_top(exposure, slots, pool),
        "gini": gini(counts),
        "mean_exposure_exposed": float(np.mean(list(exposure.values()))) if exposure else 0.0,
    }


def _share_top(exposure: Counter[int], slots: int, pool: int) -> float:
    if not slots or not pool:
        return 0.0
    k = max(1, round(pool * 0.01))
    return sum(n for _, n in exposure.most_common(k)) / slots
