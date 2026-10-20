"""The encaixe formula (spec 7–8): positions per criterion → pillar positions → final order.

Side-agnostic: it ranks jobs for a candidate (side C) or candidates for a job (side B) from the same
pair evaluations. Aggregators: ``rank_sum`` (default, Greenblatt-style), ``rrf`` and ``weighted`` (baseline).
Order of ``rank_sum``: (applicant group on side B) → final sum ↑ → Atende position ↑ → Requirements
position ↑ → item id ↑ — exactly what "Por que estou vendo isto?" publishes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.config import RULES, Rules, rules_hash
from app.ranking.pair import FilterReason, GoodFit, Raw, RequirementEval
from app.ranking.positions import imputed_values, positions

PRECISION_OF = {
    "requirements": None,
    "semantic": "cosine",
    "title": "cosine",
    "seniority": None,
    "salary": "salary",
    "distance": "distance_km",
    "timezone": "tz_hours",
    "history": "history",
}


@dataclass
class PairEval:
    item_id: int
    req: RequirementEval
    raw: dict[str, Raw]
    filters: list[FilterReason]
    good: GoodFit
    applicant: bool = False
    history: float | None = None  # feedback-v1 value (None = pillar inactive for the actor)
    history_top: list[dict] = field(default_factory=list)
    extra: dict = field(default_factory=dict)  # side-specific data (badges, versions…)


@dataclass
class RankedItem:
    item_id: int
    order: int
    final_sum: float  # rank_sum: sum of pillar positions; rrf/weighted: score
    pillars: dict[str, dict[str, float]]
    criteria: dict[str, dict]
    good_fit: GoodFit
    req: RequirementEval
    applicant: bool = False
    history_top: list[dict] = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    slot: str = "ranked"
    propensity: float = 1.0


@dataclass
class FilteredItem:
    item_id: int
    reasons: list[FilterReason]
    req: RequirementEval
    extra: dict = field(default_factory=dict)


@dataclass
class RankResult:
    items: list[RankedItem]
    filtered: list[FilteredItem]
    meta: dict


def ranker_version(ranker: str, history_active: bool) -> str:
    return ranker


def rank(
    pairs: list[PairEval],
    *,
    side: str,
    ranker: str | None = None,
    aggregator: str | None = None,
    rules: Rules = RULES,
) -> RankResult:
    ranker = ranker or rules.rankers.default
    aggregator = aggregator or rules.aggregation.aggregator
    eligible = [p for p in pairs if not p.filters]
    filtered = [FilteredItem(p.item_id, p.filters, p.req, p.extra) for p in pairs if p.filters]
    history_active = ranker == "feedback-v1" and any(p.history is not None for p in eligible)
    pillars: dict[str, tuple[str, ...]] = {"atende": rules.criteria.atende, "interessa": rules.criteria.interessa}
    if history_active:
        pillars["historico"] = rules.criteria.historico
    meta = {
        "n_total": len(pairs),
        "n_eligible": len(eligible),
        "n_filtered": len(filtered),
        "ranker_version": ranker,
        "aggregator": aggregator,
        "history_active": history_active,
        "rules_hash": rules_hash(rules),
        "side": side,
    }
    if not eligible:
        return RankResult([], filtered, meta)

    n = len(eligible)
    crit_values: dict[str, list] = {}
    crit_unknown: dict[str, list[bool]] = {}
    crit_na: dict[str, list[bool]] = {}
    for crit in [c for cs in pillars.values() for c in cs]:
        if crit == "history":
            vals = [p.history for p in eligible]
            na = [False] * n
        else:
            vals = [p.raw[crit].value for p in eligible]
            na = [p.raw[crit].na for p in eligible]
        crit_values[crit] = vals
        crit_unknown[crit] = [v is None for v in vals]
        crit_na[crit] = na

    crit_pos: dict[str, np.ndarray] = {}
    for crit, vals in crit_values.items():
        prec_name = PRECISION_OF[crit]
        precision = getattr(rules.precision, prec_name) if prec_name else None
        crit_pos[crit] = positions(vals, rules.criteria.better[crit], precision)

    pillar_sum: dict[str, np.ndarray] = {}
    pillar_pos: dict[str, np.ndarray] = {}
    if aggregator == "rank_sum":
        for p_name, crits in pillars.items():
            pillar_sum[p_name] = np.sum([crit_pos[c] for c in crits], axis=0)
            pillar_pos[p_name] = positions(list(pillar_sum[p_name]), "min", None)
        final = np.sum([pillar_pos[p] for p in pillars], axis=0)
        sort_final = final
    elif aggregator == "rrf":
        k = rules.aggregation.rrf_k
        for p_name, crits in pillars.items():
            pillar_sum[p_name] = np.sum([1.0 / (k + crit_pos[c]) for c in crits], axis=0)
            pillar_pos[p_name] = positions(list(pillar_sum[p_name]), "max", None)
        final = np.sum([1.0 / (k + pillar_pos[p]) for p in pillars], axis=0)
        sort_final = -final
    elif aggregator == "weighted":
        w = rules.aggregation.weighted
        norm = {c: _normalized(crit_values[c], rules.criteria.better[c], w) for c in crit_values}
        weights = {"atende": w.atende, "interessa": w.interessa, "historico": {"history": 1.0}}
        pw = w.pillars_with_history if history_active else w.pillars
        for p_name, crits in pillars.items():
            pillar_sum[p_name] = np.sum([weights[p_name][c] * norm[c] for c in crits], axis=0)
            pillar_pos[p_name] = positions(list(pillar_sum[p_name]), "max", None)
        final = np.sum([pw[p] * pillar_sum[p] for p in pillars], axis=0)
        sort_final = -final
    else:
        raise ValueError(f"unknown aggregator {aggregator!r}")

    group = [0 if (side == "recruiter" and p.applicant) else 1 for p in eligible]
    order = sorted(
        range(n),
        key=lambda i: (
            group[i],
            round(float(sort_final[i]), 9),
            pillar_pos["atende"][i],
            crit_pos["requirements"][i],
            eligible[i].item_id,
        ),
    )
    items: list[RankedItem] = []
    for rank_idx, i in enumerate(order, start=1):
        p = eligible[i]
        criteria = {}
        for crit in crit_values:
            raw = p.raw.get(crit) if crit != "history" else Raw(p.history)
            criteria[crit] = {
                "raw": crit_values[crit][i],
                "position": float(crit_pos[crit][i]),
                "unknown": crit_unknown[crit][i] and not crit_na[crit][i],
                "not_applicable": crit_na[crit][i],
                "flags": list(raw.flags) if raw else [],
                "info": dict(raw.info) if raw else {},
            }
        items.append(
            RankedItem(
                item_id=p.item_id,
                order=rank_idx,
                final_sum=float(final[i]),
                pillars={
                    name: {"sum": float(pillar_sum[name][i]), "position": float(pillar_pos[name][i])}
                    for name in pillars
                },
                criteria=criteria,
                good_fit=p.good,
                req=p.req,
                applicant=p.applicant,
                history_top=p.history_top,
                extra=p.extra,
            )
        )
    meta["n_items"] = n
    return RankResult(items, filtered, meta)


def _normalized(values: list, better: str, w) -> np.ndarray:  # type: ignore[no-untyped-def]
    """Min–max within the list (weighted baseline); unknown → w.unknown_value; constant → w.constant_value."""
    scal: list[float | None] = []
    for v in values:
        if v is None:
            scal.append(None)
        elif isinstance(v, tuple):
            scal.append(float(sum(c * x for c, x in zip(w.requirements_scalar, v, strict=False))))
        else:
            scal.append(float(v))
    known = [s for s in scal if s is not None]
    out = np.full(len(scal), w.unknown_value, dtype=float)
    if not known:
        return out
    lo, hi = min(known), max(known)
    for i, s in enumerate(scal):
        if s is None:
            continue
        if hi == lo:
            out[i] = w.constant_value
        else:
            x = (s - lo) / (hi - lo)
            out[i] = x if better == "max" else 1.0 - x
    return out


__all__ = ["PairEval", "RankResult", "RankedItem", "FilteredItem", "rank", "imputed_values"]
