"""What the ranking needs to know about each side, computed once per candidate revision / job version."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from app import geo as geo_mod
from app import taxonomy as tax_mod
from app.config import RULES
from app.extraction.dates import overlaps_window
from app.money import convert
from app.profiles.levels import candidate_level
from app.schemas import CandidateProfile, Eligibility, Offers, Requires, Wants


@dataclass
class CandidateFeatures:
    candidate_id: int | None
    revision_id: int | None
    proven: set[str]  # used in a dated experience
    proven_recent: set[str]  # … overlapping the last RULES.requirements.recent_years
    listed: set[str]  # in the profile without a dated experience
    languages: dict[str, int]  # ISO code → level rank (1 basic … 5 native; 0 unknown level)
    level: int | None
    city_id: str | None
    country: str | None
    tz: str | None
    wants: Wants
    domains: set[str]
    emb: np.ndarray
    title_emb: np.ndarray
    visible: bool = True
    synthetic: bool = False
    headline: str | None = None


@dataclass
class JobFeatures:
    job_id: int
    version: int
    origin: str
    status: str
    source: str
    company_id: int | None
    owner_recruiter_id: int | None
    title: str
    must: list[str]
    nice: list[str]
    languages: list[tuple[str, int]]  # (code, required level rank; 0 = any level)
    level: int | None
    arrangement: str | None
    city_id: str | None
    country: str | None
    tz: str | None
    eligibility: list[str]
    offers: Offers
    domains: list[str]
    emb: np.ndarray
    title_emb: np.ndarray
    must_nontransversal: list[str] = field(default_factory=list)


def candidate_features(
    profile: CandidateProfile,
    emb: np.ndarray,
    title_emb: np.ndarray,
    today: date,
    *,
    candidate_id: int | None = None,
    revision_id: int | None = None,
    visible: bool = True,
    synthetic: bool = False,
) -> CandidateFeatures:
    tax = tax_mod.load()
    geo = geo_mod.load()
    window_start = date(today.year - RULES.requirements.recent_years, today.month, 1)
    proven: set[str] = set()
    recent: set[str] = set()
    undated: set[str] = set()
    for exp in profile.experiences:
        skills = {s for s in exp.skills_used if tax.has(s)}
        if exp.start is None:
            undated |= skills
            continue
        proven |= skills
        if overlaps_window(exp.start, exp.end, window_start, today):
            recent |= skills
    listed = ({s for s in profile.skills_listed if tax.has(s)} | undated) - proven
    langs: dict[str, int] = {}
    for lang in profile.languages:
        langs[lang.language] = max(langs.get(lang.language, 0), tax.level_rank(lang.level) or 1)
    city = geo.get_city(profile.city_id)
    domains: set[str] = set()
    for s in proven or listed:  # without proven skills, the listed ones (docs/DECISIONS.md #5)
        domains |= tax.domains(s)
    return CandidateFeatures(
        candidate_id=candidate_id,
        revision_id=revision_id,
        proven=proven,
        proven_recent=recent,
        listed=listed,
        languages=langs,
        level=candidate_level(profile),
        city_id=profile.city_id,
        country=city.country if city else None,
        tz=city.tz if city else None,
        wants=profile.wants,
        domains=domains,
        emb=emb,
        title_emb=title_emb,
        visible=visible,
        synthetic=synthetic,
        headline=profile.headline,
    )


def job_features(job, emb: np.ndarray, title_emb: np.ndarray) -> JobFeatures:  # job: app.models.Job
    tax = tax_mod.load()
    geo = geo_mod.load()
    req = Requires.model_validate(job.requires or {})
    offers = Offers.model_validate(job.offers or {})
    city = geo.get_city(job.city_id)
    must = [s for s in req.skills_must if tax.has(s)]
    return JobFeatures(
        job_id=job.id,
        version=job.version,
        origin=job.origin,
        status=job.status,
        source=job.source,
        company_id=job.company_id,
        owner_recruiter_id=job.owner_recruiter_id,
        title=job.title,
        must=must,
        nice=[s for s in req.skills_nice if tax.has(s) and s not in must],
        languages=[(lang.language, tax.level_rank(lang.level)) for lang in req.languages],
        level=req.seniority,
        arrangement=offers.arrangement,
        city_id=job.city_id,
        country=job.country or (city.country if city else None),
        tz=job.job_tz or (city.tz if city else None),
        eligibility=list(Eligibility.model_validate(job.eligibility or {}).countries),
        offers=offers,
        domains=list(job.domains or tax.job_domains([*must, *req.skills_nice])),
        emb=emb,
        title_emb=title_emb,
        must_nontransversal=[s for s in must if not tax.is_transversal(s)],
    )


def job_comp_max_for(job: JobFeatures, wants: Wants) -> tuple[float | None, bool]:
    """Job's top of range (comp_max, else comp_min) in the candidate's currency/period, and the FX flag."""
    amount = job.offers.comp_max if job.offers.comp_max is not None else job.offers.comp_min
    conv = convert(amount, job.offers.currency, job.offers.period, wants.currency, wants.period)
    return (conv.value, conv.approx_fx) if conv else (None, False)
