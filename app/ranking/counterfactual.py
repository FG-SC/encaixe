"""What would change the result (spec 9.5): the smallest change that makes a job a good fit.

Always phrased as "bom encaixe", never "sobe N posições" (positions depend on the other jobs). A skill is
simulated as used in a recent experience; preferences are the candidate's own filters.
"""

from __future__ import annotations

import dataclasses
import math
from collections import Counter
from dataclasses import dataclass, field

from app.config import RULES
from app.ranking.features import CandidateFeatures, JobFeatures, job_comp_max_for
from app.ranking.pair import FilterReason, distance_km, evaluate_requirements, good_fit, hard_filters, out_of_area

PREFERENCE_FILTERS = {"arrangement_not_accepted", "beyond_distance", "salary_below_min"}


@dataclass
class Counterfactual:
    kind: str  # none | skills | preference | preference_and_skills | not_small
    skills: list[str] = field(default_factory=list)
    preferences: list[dict] = field(default_factory=list)
    must_credit_after: float | None = None
    must_total: int = 0
    reason: str | None = None  # why there is no small change


def with_skills(c: CandidateFeatures, skills: list[str]) -> CandidateFeatures:
    """The candidate as if these skills were used in a recent experience."""
    proven = c.proven | set(skills)
    domains = set(c.domains)
    from app import taxonomy as tax_mod

    tax = tax_mod.load()
    for s in skills:
        domains |= tax.domains(s)
    return dataclasses.replace(
        c, proven=proven, proven_recent=c.proven_recent | set(skills), listed=c.listed - set(skills), domains=domains
    )


def _depth(skill: str) -> int:
    from app import taxonomy as tax_mod

    tax = tax_mod.load()
    depth, current = 0, tax.parent(skill)
    while current and depth < 10:
        depth, current = depth + 1, tax.parent(current)
    return depth


def _preference_change(c: CandidateFeatures, j: JobFeatures, f: FilterReason) -> dict | None:
    w = c.wants
    if f.code == "arrangement_not_accepted" and j.arrangement:
        return {"field": "arrangements", "value": sorted({*w.arrangements, j.arrangement}), "add": j.arrangement}
    if f.code == "beyond_distance":
        d = distance_km(c, j)
        return {"field": "max_distance_km", "value": int(math.ceil((d or 0) / 10.0) * 10)} if d else None
    if f.code == "salary_below_min":
        job_max, _ = job_comp_max_for(j, w)
        if job_max is None:
            return None
        return {"field": "comp_min", "value": int(math.floor(job_max / RULES.filters.comp_min_ratio / 100) * 100)}
    return None


def _apply_preferences(c: CandidateFeatures, prefs: list[dict]) -> CandidateFeatures:
    wants = c.wants.model_copy()
    for p in prefs:
        setattr(wants, p["field"], p["value"])
    return dataclasses.replace(c, wants=wants)


def smallest_change(
    c: CandidateFeatures, j: JobFeatures, side: str = "candidate", unlock_value: dict[str, int] | None = None
) -> Counterfactual:
    req = evaluate_requirements(c, j)
    filters = hard_filters(c, j, req, side)
    if good_fit(c, j, req, not filters).is_good_fit:
        return Counterfactual("none", must_credit_after=req.must_credit, must_total=req.must_total)
    if req.must_total == 0:
        return Counterfactual("not_small", reason="not_evaluable")
    prefs: list[dict] = []
    blocking = [f for f in filters if f.code != "out_of_area"]
    if any(f.code not in PREFERENCE_FILTERS for f in blocking):
        code = next(f.code for f in blocking if f.code not in PREFERENCE_FILTERS)
        return Counterfactual("not_small", must_total=req.must_total, reason=code)
    for f in blocking:
        change = _preference_change(c, j, f)
        if change is None:
            return Counterfactual("not_small", must_total=req.must_total, reason=f.code)
        prefs.append(change)
    base = _apply_preferences(c, prefs) if prefs else c
    gap = abs(j.level - c.level) if j.level is not None and c.level is not None else None
    if gap is not None and gap > RULES.good_fit.max_seniority_gap:
        return Counterfactual("not_small", preferences=prefs, must_total=req.must_total, reason="seniority_gap")
    unlock_value = unlock_value or {}
    missing = [st for st in req.must_status if st.credit < 1.0]
    # Zero-credit skills first, then the ones unlocking most jobs, then the more specific (deeper in the
    # taxonomy: "PyTorch" is more actionable than "deep learning"), then alphabetical.
    missing.sort(key=lambda st: (st.credit, -unlock_value.get(st.skill, 0), -_depth(st.skill), st.skill))
    chosen: list[str] = []
    current = base
    for st in [None, *missing]:
        if st is not None:
            chosen.append(st.skill)
            current = with_skills(base, chosen)
        r = evaluate_requirements(current, j)
        if good_fit(current, j, r, not hard_filters(current, j, r, side)).is_good_fit:
            kind = "preference_and_skills" if prefs and chosen else "preference" if prefs else "skills"
            return Counterfactual(
                kind, skills=chosen, preferences=prefs, must_credit_after=r.must_credit, must_total=r.must_total
            )
    return Counterfactual("not_small", preferences=prefs, must_total=req.must_total, reason="languages")


def skills_to_full_proof(c: CandidateFeatures, j: JobFeatures) -> tuple[list[str], float, int]:
    """Every must the candidate does not fully prove, and the credit after adding all of them."""
    req = evaluate_requirements(c, j)
    gaps = [st.skill for st in req.must_status if st.credit < 1.0]
    after = evaluate_requirements(with_skills(c, gaps), j)
    return gaps, after.must_credit, after.must_total


def unlock_counts(
    c: CandidateFeatures, jobs: list[JobFeatures], side: str = "candidate", candidates_skills: list[str] | None = None
) -> Counter[str]:
    """For each skill the candidate does not prove: open jobs of their area that become a good fit if it is added.

    Jobs out of the candidate's area today are left out: one generic skill ("Vendas") would otherwise "unlock" a
    whole other career (a sales profile still sees sales skills, since sales jobs are in its area).
    """
    from app import taxonomy as tax_mod

    tax = tax_mod.load()
    base_good: dict[int, bool] = {}
    for j in jobs:
        r = evaluate_requirements(c, j)
        if out_of_area(c, j, r):
            base_good[j.job_id] = True  # skipped below, like a job that is already a good fit
            continue
        base_good[j.job_id] = good_fit(c, j, r, not hard_filters(c, j, r, side)).is_good_fit
    skills = candidates_skills or sorted({s for j in jobs for s in j.must} - c.proven)
    counts: Counter[str] = Counter()
    for s in skills:
        related = {s, *(x for x in tax.skills if tax.related(s, x))}
        cs = with_skills(c, [s])
        for j in jobs:
            if base_good[j.job_id] or not (related & set(j.must)):
                continue
            r = evaluate_requirements(cs, j)
            if good_fit(cs, j, r, not hard_filters(cs, j, r, side)).is_good_fit:
                counts[s] += 1
    return counts
