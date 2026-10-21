"""Candidate seniority (L1–L6) and years of experience. The title rules; years are only a fallback."""

from __future__ import annotations

from datetime import date

from app import clock
from app import taxonomy as tax_mod
from app.config import RULES
from app.embeddings.texts import recent_experiences
from app.extraction.dates import union_years
from app.schemas import CandidateProfile


def years_of_experience(profile: CandidateProfile) -> float:
    return union_years([(e.start, e.end) for e in profile.experiences], clock.today())


def candidate_level(profile: CandidateProfile) -> int | None:
    """Most recent experience (ended within the title window) whose title states a level; else the headline; else
    years of experience (fallback)."""
    tax = tax_mod.load()
    today = clock.today()
    window_start = date(today.year - RULES.seniority.title_window_years, today.month, 1)
    for exp in recent_experiences(profile.experiences):
        if exp.end is not None and exp.end < window_start:
            break  # older experiences only count through the years of experience
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
