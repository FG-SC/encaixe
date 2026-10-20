"""The short strings that are embedded (spec 7): ~100 words, no personal data.

Job: title + must and nice skills + the first sentences of the role summary (no institutional text).
Candidate: headline + titles of the 3 most recent experiences + up to 20 skills (proven before listed)
+ description of the most recent experience. Never the name, contact, city or company names.
"""

from __future__ import annotations

import re
from datetime import date

from app import taxonomy as tax_mod
from app.config import RULES
from app.schemas import CandidateProfile, ExperienceIn


def _cap_words(text: str, max_words: int) -> str:
    words = re.sub(r"[•·▪◦]", " ", text).split()
    return " ".join(words[:max_words])


def job_embed_text(title: str, skills_must: list[str], skills_nice: list[str], summary: str) -> str:
    tax = tax_mod.load()
    skills = ", ".join(tax.label(s) for s in [*skills_must, *[s for s in skills_nice if s not in skills_must]])
    parts = [title.strip(), skills, summary.strip()]
    return _cap_words(". ".join(p for p in parts if p), RULES.embeddings.job_text_max_words)


def job_title_text(title: str) -> str:
    return _cap_words(title, 20)


def recent_experiences(experiences: list[ExperienceIn]) -> list[ExperienceIn]:
    """Most recent first: ongoing ones first, then by end date, then by start date."""
    return sorted(
        experiences,
        key=lambda e: (e.end is None, e.end or date.min, e.start or date.min),
        reverse=True,
    )


def candidate_skills_ordered(profile: CandidateProfile) -> list[str]:
    """Proven skills (used in a dated experience) first, then listed ones."""
    proven: dict[str, None] = {}
    for exp in recent_experiences(profile.experiences):
        if exp.start is None:
            continue
        for s in exp.skills_used:
            proven.setdefault(s, None)
    listed = [s for s in profile.skills_listed if s not in proven]
    return [*proven, *listed]


def candidate_embed_text(profile: CandidateProfile) -> str:
    tax = tax_mod.load()
    exps = recent_experiences(profile.experiences)
    titles = [e.role for e in exps[: RULES.embeddings.candidate_text_recent_titles] if e.role]
    skills = ", ".join(
        tax.label(s) for s in candidate_skills_ordered(profile)[: RULES.embeddings.candidate_text_max_skills]
    )
    latest = (exps[0].responsibilities or "") if exps else ""
    parts = [profile.headline or "", "; ".join(titles), skills, latest]
    return _cap_words(". ".join(p.strip() for p in parts if p and p.strip()), RULES.embeddings.candidate_text_max_words)


def candidate_title_texts(profile: CandidateProfile) -> list[str]:
    """Experience titles (the title criterion uses their mean vector); the headline when there are none."""
    titles = [e.role for e in profile.experiences if e.role]
    if not titles and profile.headline:
        titles = [profile.headline]
    return [_cap_words(t, 20) for t in titles] or ["sem experiência"]
