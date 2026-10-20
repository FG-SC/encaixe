"""Candidate seniority (L1–L6) and years of experience. The title rules; years are only a fallback."""

from __future__ import annotations

from app import clock
from app import taxonomy as tax_mod
from app.config import RULES
from app.embeddings.texts import recent_experiences
from app.extraction.dates import union_years
from app.schemas import CandidateProfile


def years_of_experience(profile: CandidateProfile) -> float:
    return union_years([(e.start, e.end) for e in profile.experiences], clock.today())


def candidate_level(profile: CandidateProfile) -> int | None:
    """Most recent experience whose title states a level; else the headline; else years (fallback)."""
    tax = tax_mod.load()
    for exp in recent_experiences(profile.experiences):
        level = exp.seniority
        if level is None:
            m = tax.seniority_from_title(exp.role)
            level = m.level if m and m.strength == "explicit" else None
        if level is not None:
            return level
    if profile.headline:
        m = tax.seniority_from_title(profile.headline)
        if m and m.strength == "explicit":
            return m.level
    if not profile.experiences:
        studying = any(d.end is None and d.start is not None for d in profile.education)
        return RULES.seniority.student_level if studying else None
    years = years_of_experience(profile)
    for lo, hi, level in RULES.seniority.years_fallback:
        if lo <= years < hi:
            return level
    return None
