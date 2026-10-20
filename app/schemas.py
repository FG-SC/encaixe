"""Canonical Pydantic types (ARCHITECTURE section 5) and API DTOs.

The schema is symmetric: a job says what it requires and what it offers; a candidate says what they
have and what they want. Dates have month precision (day = 1); an ongoing experience has
``end = None``. Provenance keys are field paths (``requires.skills_must.pytorch``, ``offers.comp_max``,
``experiences.0.start``).

The ``Literal`` enums mirror ``RULES`` where RULES lists the same values (reasons); a test keeps them in
sync. pt-BR labels live in ``app.texts``.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.config import RULES

# --------------------------------------------------------------------------- enums

Arrangement = Literal["remote", "hybrid", "onsite"]
Period = Literal["hour", "day", "week", "month", "year"]
Regime = Literal["clt", "pj", "internship", "contractor", "other"]
LanguageLevelName = Literal["basic", "intermediate", "advanced", "fluent", "native"]
ProvenanceMethod = Literal["heuristic", "llm", "label", "user"]
ExtractionMethod = Literal["heuristic", "llm"]
CandidateReason = Literal["role_area", "company", "salary", "arrangement", "seniority"]
RecruiterReason = Literal["skills", "seniority", "salary", "location", "language", "job_filled"]
EventType = Literal["impression", "swipe_right", "swipe_left", "open_detail"]
Slot = Literal["ranked", "explore", "direct"]
ActorType = Literal["candidate", "recruiter"]
ItemType = Literal["job", "candidate"]
JobOrigin = Literal["market", "platform"]
JobStatus = Literal["open", "closed", "paused"]
RevisionKind = Literal["relevant", "minor"]
RankerVersion = Literal["static-v1", "feedback-v1"]
AggregatorName = Literal["rank_sum", "rrf", "weighted"]
FilterCode = Literal[
    "closed",
    "not_visible",
    "arrangement_not_accepted",
    "beyond_distance",
    "country_eligibility",
    "salary_below_min",
    "seniority_gap",
    "out_of_area",
]
# Application status, derived from events (labels: enviada, vista, não avançou, encaixe).
ApplicationStatus = Literal["sent", "seen", "not_advanced", "matched"]

ALL_ARRANGEMENTS: tuple[str, ...] = ("remote", "hybrid", "onsite")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- building blocks


class Provenance(_Model):
    source_span: str | None = None
    stated: bool = False  # True = declared in the text; False = inferred
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    method: ProvenanceMethod = "heuristic"


class LanguageLevel(_Model):
    language: str  # e.g. "en", "es", "pt"
    level: LanguageLevelName | None = None


class Requires(_Model):
    skills_must: list[str] = Field(default_factory=list)  # taxonomy skill ids
    skills_nice: list[str] = Field(default_factory=list)
    seniority: int | None = Field(default=None, ge=1, le=6)
    years_min: float | None = Field(default=None, ge=0)
    languages: list[LanguageLevel] = Field(default_factory=list)


class Offers(_Model):
    arrangement: Arrangement | None = None
    comp_min: float | None = Field(default=None, ge=0)
    comp_max: float | None = Field(default=None, ge=0)
    currency: str | None = None  # ISO 4217
    period: Period | None = None
    regime: Regime | None = None


class Eligibility(_Model):
    countries: list[str] = Field(default_factory=list)  # ISO 3166-1 alpha-2; empty = no restriction


class Wants(_Model):
    comp_min: float | None = Field(default=None, ge=0)
    currency: str = RULES.currency.base
    period: Period = "month"
    # Default: every arrangement accepted (an empty list would filter every job).
    arrangements: list[Arrangement] = Field(default_factory=lambda: list(ALL_ARRANGEMENTS))
    max_distance_km: float | None = Field(default=None, ge=0)
    languages: list[LanguageLevel] = Field(default_factory=list)


class ExperienceIn(_Model):
    company: str | None = None
    role: str = ""
    seniority: int | None = Field(default=None, ge=1, le=6)
    start: date | None = None
    end: date | None = None  # None = current
    skills_used: list[str] = Field(default_factory=list)
    responsibilities: str | None = None
    outcomes: list[str] = Field(default_factory=list)


class EducationIn(_Model):
    degree: str | None = None
    field: str | None = None
    institution: str | None = None
    start: date | None = None
    end: date | None = None


class CandidateProfile(_Model):
    name: str = ""
    contact: str | None = None
    headline: str | None = None
    city_id: str | None = None
    experiences: list[ExperienceIn] = Field(default_factory=list)
    education: list[EducationIn] = Field(default_factory=list)
    skills_listed: list[str] = Field(default_factory=list)
    languages: list[LanguageLevel] = Field(default_factory=list)
    wants: Wants = Field(default_factory=Wants)


class CandidateDraft(CandidateProfile):
    """What onboarding shows for review: the profile plus where each value came from."""

    provenance: dict[str, Provenance] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    method: ExtractionMethod = "heuristic"
    llm_status: str | None = None  # e.g. "off", "ok", "fallback: timeout"
    llm_cache_key: str | None = None  # links the CV's LLM cache entry to the candidate (purged with them)


class JobDraft(_Model):
    title: str
    company: str | None = None
    description_text: str = ""
    location_text: str | None = None
    city_id: str | None = None
    country: str | None = None
    requires: Requires = Field(default_factory=Requires)
    offers: Offers = Field(default_factory=Offers)
    eligibility: Eligibility = Field(default_factory=Eligibility)
    job_tz: str | None = None
    provenance: dict[str, Provenance] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    method: ExtractionMethod = "heuristic"


# --------------------------------------------------------------------------- API DTOs


class Health(BaseModel):
    ok: bool
    version: str
    rules_hash: str


class LabeledOption(BaseModel):
    code: str
    label: str


class SeniorityLevelOut(BaseModel):
    level: int
    label: str


class EventTimings(BaseModel):
    impression_min_ms: int
    session_idle_minutes: int
    reason_chips_seconds: int


class ExplorationPublic(BaseModel):
    every: int


class ReasonsPublic(BaseModel):
    candidate: list[LabeledOption]
    recruiter: list[LabeledOption]
    recruiter_required_for_applicants: bool


class PrivacyPublic(BaseModel):
    k_anon: int
    below_k_label: str  # how counts below k_anon are shown, e.g. "<5"
    candidate_default_visible: bool
    blind_hidden: list[LabeledOption]
    texts: dict[str, str]


class RulesPublic(BaseModel):
    """Front-facing rule values and pt-BR labels; built only from RULES and app.texts."""

    rules_hash: str
    events: EventTimings
    exploration: ExplorationPublic
    reasons: ReasonsPublic
    arrangements: list[LabeledOption]
    regimes: list[LabeledOption]
    periods: list[LabeledOption]
    language_levels: list[LabeledOption]
    seniority: list[SeniorityLevelOut]
    privacy: PrivacyPublic
