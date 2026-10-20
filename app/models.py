"""SQLModel tables (ARCHITECTURE section 4). Field names are binding.

Nested shapes are JSON columns holding plain ``dict``/``list`` values; validate them with the canonical
Pydantic types of ``app.schemas`` (e.g. ``Wants.model_validate(candidate.wants)``) and store
``model_dump(mode="json")``. Reassign a JSON attribute to change it (in-place mutation is not tracked).
Embeddings are float32 bytes (``app.db.to_blob`` / ``from_blob``). Datetimes are timezone-aware UTC
and default to ``app.clock.now()``. ``City`` is static (``app/geo/cities.csv``), not a table.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Column, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.config import RULES, rules_hash


def _now() -> datetime:
    from app.clock import now  # lazy: app.clock imports this module

    return now()


def _current_rules_hash() -> str:
    return rules_hash()


def _json(nullable: bool = False) -> Column:
    return Column(JSON, nullable=nullable)


class Company(SQLModel, table=True):
    """Identity only: no size or prestige score. Matched exactly on the normalized name."""

    id: int | None = Field(default=None, primary_key=True)
    name: str
    name_normalized: str = Field(unique=True, index=True)
    aliases: list[str] = Field(default_factory=list, sa_column=_json())


class Recruiter(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    company_id: int = Field(foreign_key="company.id", index=True)
    synthetic: bool = False


class Candidate(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = ""
    contact: str | None = None
    headline: str | None = None
    city_id: str | None = Field(default=None, index=True)
    wants: dict[str, Any] = Field(default_factory=dict, sa_column=_json())  # schemas.Wants
    skills_listed: list[str] = Field(default_factory=list, sa_column=_json())
    languages: list[dict[str, Any]] = Field(default_factory=list, sa_column=_json())  # [schemas.LanguageLevel]
    visible_to_recruiters: bool = RULES.privacy.candidate_default_visible
    llm_consent: bool = False
    synthetic: bool = False
    # Logical reference to profilerevision.id, kept without a FK constraint: with one, candidate and
    # profilerevision would reference each other (a cycle SQLite cannot create or drop cleanly).
    current_revision_id: int | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=_now)


class Experience(SQLModel, table=True):
    """A dated experience; a promotion is two consecutive experiences at the same company_id."""

    id: int | None = Field(default=None, primary_key=True)
    candidate_id: int = Field(foreign_key="candidate.id", ondelete="CASCADE", index=True)
    company_id: int | None = Field(default=None, foreign_key="company.id", index=True)
    role: str = ""
    seniority: int | None = None
    start: date | None = None  # month precision (day = 1)
    end: date | None = None  # None = current ("atual" / "present")
    skills_used: list[str] = Field(default_factory=list, sa_column=_json())
    responsibilities: str | None = None
    outcomes: list[str] = Field(default_factory=list, sa_column=_json())
    provenance: dict[str, Any] = Field(default_factory=dict, sa_column=_json())  # {path: Provenance}


class Education(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    candidate_id: int = Field(foreign_key="candidate.id", ondelete="CASCADE", index=True)
    degree: str | None = None
    field: str | None = None
    institution: str | None = None
    start: date | None = None
    end: date | None = None


class ProfileRevision(SQLModel, table=True):
    """Saved profile version, append-only by convention (only its vectors may be recomputed)."""

    id: int | None = Field(default=None, primary_key=True)
    candidate_id: int = Field(foreign_key="candidate.id", ondelete="CASCADE", index=True)
    ts: datetime = Field(default_factory=_now, index=True)
    hash: str = Field(index=True)
    kind: str = "minor"  # relevant | minor
    snapshot: dict[str, Any] = Field(default_factory=dict, sa_column=_json())  # schemas.CandidateProfile
    seniority: int | None = None
    embedding: bytes | None = None
    title_embedding: bytes | None = None


class Job(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_job_source_source_id"),)

    id: int | None = Field(default=None, primary_key=True)
    origin: str = Field(default="market", index=True)  # market | platform
    owner_recruiter_id: int | None = Field(default=None, foreign_key="recruiter.id", index=True)
    source: str  # greenhouse | lever | github | platform | seed | ...
    source_id: str
    url: str | None = None
    company_id: int | None = Field(default=None, foreign_key="company.id", index=True)
    title: str
    description_text: str = ""
    location_text: str | None = None
    city_id: str | None = Field(default=None, index=True)
    country: str | None = None  # ISO 3166-1 alpha-2
    requires: dict[str, Any] = Field(default_factory=dict, sa_column=_json())  # schemas.Requires
    offers: dict[str, Any] = Field(default_factory=dict, sa_column=_json())  # schemas.Offers
    eligibility: dict[str, Any] = Field(default_factory=dict, sa_column=_json())  # schemas.Eligibility
    job_tz: str | None = None
    domains: list[str] = Field(default_factory=list, sa_column=_json())
    provenance: dict[str, Any] = Field(default_factory=dict, sa_column=_json())  # {path: Provenance}
    labels: list[str] = Field(default_factory=list, sa_column=_json())
    version: int = 1  # bumps only when the posting content changes
    extraction_method: str = "heuristic"  # heuristic | llm | label
    content_hash: str | None = None
    first_seen: datetime = Field(default_factory=_now)
    last_seen: datetime = Field(default_factory=_now)
    status: str = Field(default="open", index=True)  # open | closed | paused
    missed_runs: int = 0
    x: float | None = None  # market-map projection
    y: float | None = None
    cluster: int | None = None


class JobVersion(SQLModel, table=True):
    """The job's current vectors are its latest version (LLM re-extraction updates the same version)."""

    __table_args__ = (UniqueConstraint("job_id", "version", name="uq_jobversion_job_version"),)

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", ondelete="CASCADE", index=True)
    version: int = 1
    ts: datetime = Field(default_factory=_now)
    snapshot: dict[str, Any] = Field(default_factory=dict, sa_column=_json())  # schemas.JobDraft
    embedding: bytes | None = None
    title_embedding: bytes | None = None


class InteractionEvent(SQLModel, table=True):
    """Exactly the spec's event fields plus ``rules_hash``. Append-only (triggers from init_db)."""

    __table_args__ = (
        Index("ix_interactionevent_actor", "actor_type", "actor_id"),
        Index("ix_interactionevent_item", "item_type", "item_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    client_event_id: str = Field(unique=True, index=True)  # UUID generated by the front
    actor_type: str  # candidate | recruiter
    actor_id: int
    item_type: str  # job | candidate
    item_id: int
    context_job_id: int | None = Field(default=None, index=True)  # recruiter events: the job in context
    type: str  # impression | swipe_right | swipe_left | open_detail
    reason: str | None = None  # fixed enum (RULES.reasons), never free text
    ts: datetime = Field(default_factory=_now, index=True)
    session_id: str | None = Field(default=None, index=True)
    actor_revision_id: int | None = None
    item_revision_id: int | None = None
    item_version: int | None = None
    ranker_version: str | None = None
    slot: str | None = None  # ranked | explore | direct
    propensity: float | None = None
    rank_position: int | None = None
    rank_sum: float | None = None
    rank_detail: dict[str, Any] | None = Field(default=None, sa_column=_json(nullable=True))
    rules_hash: str = Field(default_factory=_current_rules_hash)


class Match(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("candidate_id", "job_id", name="uq_match_candidate_job"),)

    id: int | None = Field(default=None, primary_key=True)
    candidate_id: int = Field(foreign_key="candidate.id", ondelete="CASCADE", index=True)
    job_id: int = Field(foreign_key="job.id", ondelete="CASCADE", index=True)
    recruiter_id: int | None = Field(default=None, foreign_key="recruiter.id", index=True)
    ts: datetime = Field(default_factory=_now)


class LlmCache(SQLModel, table=True):
    key: str = Field(primary_key=True)  # sha256(task + model + prompt_version + content)
    task: str = Field(index=True)
    model: str
    prompt_version: str
    output_json: dict[str, Any] = Field(default_factory=dict, sa_column=_json())
    created_at: datetime = Field(default_factory=_now)


class IngestRun(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    board: str | None = None
    ts: datetime = Field(default_factory=_now, index=True)
    n_seen: int = 0
    n_new: int = 0
    n_updated: int = 0
    n_closed: int = 0
    error: str | None = None


class Setting(SQLModel, table=True):
    """Key/value store: clock offset, dev-panel ranker/aggregator override, LLM counters, index versions."""

    key: str = Field(primary_key=True)
    value: Any = Field(default=None, sa_column=_json(nullable=True))
