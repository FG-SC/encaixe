"""Configuration: ``RULES`` (every public rule) and ``Settings`` (environment).

``RULES`` holds every number that affects filtering, ranking, exploration, privacy or LLM use. The
rules page, ``docs/RULES.md`` and the front read it from here; no rule number is written by hand
anywhere else. It is a tree of frozen dataclasses whose mappings are read-only (``FrozenDict``), so
nothing can change a rule at runtime. ``rules_hash()`` identifies the rule set stored on every event.

``Settings`` come from the environment, plus an optional ``.env`` file at the repository root read
by a tiny standard-library parser (real environment variables win).

This module imports only the standard library.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app import __version__

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VAR_DIR = REPO_ROOT / "var"
DEFAULT_ENV_FILE = REPO_ROOT / ".env"

ENVIRONMENTS = ("dev", "prod")
DEFAULT_SOURCE_URL = "https://github.com/FG-SC/encaixe"
EMBEDDING_BACKENDS = ("onnx", "tfidf", "fake")
EMBEDDING_ALIASES = {"fastembed": "onnx"}  # the first backend; same model and vectors
LOG_LEVELS = ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG")


class FrozenDict(dict):
    """A read-only dict. JSON-serializable, hashable and picklable; mutation raises TypeError."""

    __slots__ = ()

    def _readonly(self, *args: Any, **kwargs: Any) -> Any:
        raise TypeError("RULES are read-only; change app/config.py instead")

    __setitem__ = _readonly
    __delitem__ = _readonly
    __ior__ = _readonly
    clear = _readonly
    pop = _readonly
    popitem = _readonly
    setdefault = _readonly
    update = _readonly

    def __hash__(self) -> int:  # type: ignore[override]
        return hash(frozenset(self.items()))

    def __copy__(self) -> FrozenDict:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> FrozenDict:
        return self

    def __reduce__(self) -> tuple[Any, ...]:
        return (FrozenDict, (dict(self),))

    def __repr__(self) -> str:
        return f"FrozenDict({dict.__repr__(self)})"


# --------------------------------------------------------------------------- RULES sections


@dataclass(frozen=True)
class FilterRules:
    """Hard filters (spec 7.1). Every failing filter is recorded with its code."""

    comp_min_ratio: float = 0.70  # filtered when job comp_max < 70% of the candidate's comp_min
    seniority_gap_exclude: int = 3  # filtered when the ladder distance is >= 3
    # Filter codes in display order ("Vagas que não te mostramos" groups follow this order).
    codes: tuple[str, ...] = (
        "closed",
        "not_visible",
        "arrangement_not_accepted",
        "beyond_distance",
        "country_eligibility",
        "salary_below_min",
        "seniority_gap",
        "out_of_area",
    )


@dataclass(frozen=True)
class CriteriaRules:
    """Pillars and their criteria, in display order (spec 7.2)."""

    pillars: tuple[str, ...] = ("atende", "interessa", "historico")
    atende: tuple[str, ...] = ("requirements", "semantic", "title", "seniority")
    interessa: tuple[str, ...] = ("salary", "distance", "timezone")
    historico: tuple[str, ...] = ("history",)  # third pillar, feedback-v1 only
    # An undisclosed salary counts as paying exactly the candidate's minimum (slack 0), not the median of the disclosed
    # ones: the conservative assumption (owner's decision, 2026-10-20). Other unknown values still get the median.
    salary_unknown_slack: float = 0.0
    # Which raw values are better: "max" = higher is better, "min" = lower is better.
    better: FrozenDict = FrozenDict(
        {
            "requirements": "max",
            "semantic": "max",
            "title": "max",
            "seniority": "min",
            "salary": "max",
            "distance": "min",
            "timezone": "max",
            "history": "max",
        }
    )


@dataclass(frozen=True)
class PrecisionRules:
    """Values within the precision count as ties and share the mean position (spec 7.3)."""

    cosine: float = 0.02
    salary: float = 0.05
    distance_km: float = 5.0
    tz_hours: float = 1.0
    history: float = 0.02


@dataclass(frozen=True)
class RequirementRules:
    recent_years: int = 3  # "proven in the last 3 years" window
    partial_credit: float = 0.5  # a direct parent/child in the taxonomy counts as half a requirement


@dataclass(frozen=True)
class GoodFitRules:
    """Absolute "bom encaixe" rule (spec 7.4)."""

    must_share: float = 0.8
    max_seniority_gap: int = 1


@dataclass(frozen=True)
class WeightedRules:
    """Weighted-sum baseline (evaluation only, spec 7.5)."""

    atende: FrozenDict = FrozenDict({"requirements": 0.45, "semantic": 0.25, "title": 0.15, "seniority": 0.15})
    interessa: FrozenDict = FrozenDict({"salary": 1 / 3, "distance": 1 / 3, "timezone": 1 / 3})
    pillars: FrozenDict = FrozenDict({"atende": 0.7, "interessa": 0.3})
    pillars_with_history: FrozenDict = FrozenDict({"atende": 0.6, "interessa": 0.25, "historico": 0.15})
    # Requirements tuple -> scalar: k1 + k2/10 + k3/100 + k4/1000 (before min-max normalization).
    requirements_scalar: tuple[float, ...] = (1.0, 0.1, 0.01, 0.001)
    unknown_value: float = 0.5  # normalized value of an unknown criterion
    constant_value: float = 0.5  # normalized value when a criterion is constant over the list


@dataclass(frozen=True)
class AggregationRules:
    aggregator: str = "rank_sum"
    available: tuple[str, ...] = ("rank_sum", "rrf", "weighted")
    rrf_k: int = 60
    weighted: WeightedRules = field(default_factory=WeightedRules)
    # Deterministic total order: final sum, then Atende position, then Requirements position, then item id.
    tie_break: tuple[str, ...] = ("sum", "atende", "requirements", "item_id")


@dataclass(frozen=True)
class FeedbackRules:
    """History pillar of feedback-v1 (spec 8)."""

    half_life_days: float = 21
    gamma: float = 0.5  # discount per relevant profile revision since the swipe
    k_min: int = 5  # judgments needed before the history pillar counts
    company_penalty: float = 0.15  # C side: jobs of a company the candidate rejected for "company"
    lambda_candidate: FrozenDict = FrozenDict(
        {"role_area": 1.0, "none": 0.5, "company": 0.0, "salary": 0.0, "arrangement": 0.0, "seniority": 0.0}
    )
    lambda_recruiter: FrozenDict = FrozenDict(
        {"skills": 1.0, "none": 0.5, "seniority": 0.0, "salary": 0.0, "location": 0.0, "language": 0.0}
    )
    # Ignored reasons have no effect at all (they say nothing about the candidate).
    ignored_recruiter: tuple[str, ...] = ("job_filled",)


@dataclass(frozen=True)
class ExplorationRules:
    every: int = 10  # every 10th card of a page is drawn
    band_low_pct: int = 20
    band_high_pct: int = 60
    exclude_top: int = 30


@dataclass(frozen=True)
class RankerRules:
    default: str = "feedback-v1"
    available: tuple[str, ...] = ("static-v1", "feedback-v1")


@dataclass(frozen=True)
class ReasonRules:
    """Fixed swipe-left reasons (no free text anywhere). pt-BR labels live in app/texts.py."""

    candidate: tuple[str, ...] = ("role_area", "company", "salary", "arrangement", "seniority")
    recruiter: tuple[str, ...] = ("skills", "seniority", "salary", "location", "language", "job_filled")
    recruiter_required_for_applicants: bool = True  # the API answers 422 without a reason


@dataclass(frozen=True)
class EventRules:
    """Front behaviour, served to the front through GET /api/rules/public."""

    impression_min_ms: int = 500
    session_idle_minutes: int = 30
    reason_chips_seconds: int = 3


@dataclass(frozen=True)
class RevisionRules:
    relevant_skill_symdiff: int = 3  # symmetric difference of skill sets that makes a revision relevant


@dataclass(frozen=True)
class PrivacyRules:
    k_anon: int = 5  # aggregates below this count render as "<5"
    candidate_default_visible: bool = False  # real candidates start invisible
    synthetic_default_visible: bool = True  # synthetic candidates start visible
    # Hidden on the blind card until a match. Company and institution names stay visible (owner's decision,
    # 2026-10-20: recruiters want to know which ones); add "company_names" / "institution_names" to hide them.
    blind_hidden: tuple[str, ...] = ("name", "contact", "photo", "age")


@dataclass(frozen=True)
class WorkdayRules:
    start_hour: int = 9
    end_hour: int = 18


@dataclass(frozen=True)
class SeniorityRules:
    """Seniority ladder L1-L6. Title rules first; years of experience only as a fallback."""

    ladder: FrozenDict = FrozenDict({1: "Estágio", 2: "Júnior", 3: "Pleno", 4: "Sênior", 5: "Staff", 6: "Principal"})
    # (min_years inclusive, max_years exclusive, level), used only when the title says nothing.
    years_fallback: tuple[tuple[int, int, int], ...] = (
        (0, 2, 2),
        (2, 5, 3),
        (5, 9, 4),
        (9, 13, 5),
        (13, 99, 6),
    )
    student_level: int = 1  # students and interns
    # A title only sets the level if its experience ended within this window: an internship that ended years ago
    # does not make an experienced person "Estágio" today (then the headline, then years of experience decide).
    title_window_years: int = 3


@dataclass(frozen=True)
class CurrencyRules:
    """Approximate FX, always flagged as "câmbio aproximado" in explanations."""

    base: str = "BRL"
    # BRL per 1 unit, rounded to 3 significant figures. Reference rates of 2026-10-19: ECB (via
    # frankfurter.dev) for USD, EUR, GBP, CAD, AUD, CHF, INR, JPY and MXN; ExchangeRate-API
    # (open.er-api.com) for ARS, CLP, COP, PEN and UYU. Refresh by hand; never fetched at runtime.
    rates_to_brl: FrozenDict = FrozenDict(
        {
            "BRL": 1.0,
            "USD": 5.05,
            "EUR": 5.66,
            "GBP": 6.73,
            "CAD": 3.58,
            "AUD": 3.52,
            "ARS": 0.00335,
            "CLP": 0.00517,
            "COP": 0.0016,
            "MXN": 0.273,
            "PEN": 1.48,
            "UYU": 0.126,
            "CHF": 6.12,
            "INR": 0.0531,
            "JPY": 0.0319,
        }
    )
    rates_as_of: str = "2026-10"
    rates_source: str = "BCE (frankfurter.dev) e ExchangeRate-API (open.er-api.com), 19/10/2026, arredondado"
    # Multiply an amount per period by this factor to get an amount per month.
    period_to_month: FrozenDict = FrozenDict({"hour": 168, "day": 21, "week": 4.33, "month": 1, "year": 1 / 12})


@dataclass(frozen=True)
class ProjectionRules:
    """Market map: PCA -> t-SNE (umap is forbidden by the spec), KMeans clusters."""

    method: str = "tsne"
    knn_star: int = 10  # the candidate's star = similarity-weighted mean of the 10 most similar open jobs
    clusters: int = 12
    perplexity: float = 30
    random_state: int = 42
    pca_dim: int = 50
    min_points_tsne: int = 50  # below this, PCA to 2 dimensions instead of t-SNE


@dataclass(frozen=True)
class EmbeddingRules:
    """Local embeddings: the multilingual MiniLM on ONNX Runtime (no torch), tokenized with sentencepiece.

    Files are pinned by commit and downloaded once into var/models (Hugging Face cache layout): the
    quantized ONNX export that fastembed 0.8.1 uses, and the model's own sentencepiece vocabulary. Same
    vectors as fastembed (mean pooling, 128-token truncation), without the 249 MB `tokenizers` vocabulary.
    """

    model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    onnx_repo: str = "qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q"
    onnx_revision: str = "faf4aa4225822f3bc6376869cb1164e8e3feedd0"
    onnx_file: str = "model_optimized.onnx"
    tokenizer_repo: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    tokenizer_revision: str = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
    tokenizer_file: str = "sentencepiece.bpe.model"
    dim: int = 384
    max_tokens: int = 128
    batch_size: int = 32  # spec says 64; lowered for the ~1.4 GB-free dev machine (docs/DECISIONS.md)
    threads: int = 2  # default for EMBED_THREADS
    job_text_max_words: int = 100
    candidate_text_max_words: int = 100
    candidate_text_max_skills: int = 20
    candidate_text_recent_titles: int = 3


@dataclass(frozen=True)
class LlmRules:
    """Optional LLM (Groq). Enabled only with GROQ_API_KEY; outside onboarding it never blocks."""

    provider: str = "groq"
    model: str = "openai/gpt-oss-20b"  # default; LLM_MODEL overrides it at runtime
    # Free-plan limits for openai/gpt-oss-20b, Groq docs (console.groq.com/docs/rate-limits, "Free Plan
    # Limits"), read and independently re-checked on 2026-10-19. Per-org values may differ (account settings).
    rpm: int = 30
    rpd: int = 1000
    tpm: int = 8000
    tpd: int | None = 200_000
    limits_as_of: str = "documentação do Groq, plano gratuito, lida em 19/10/2026"
    reasoning_effort: str = "low"  # gpt-oss accepts low/medium/high; reasoning tokens count toward the budget
    max_completion_tokens: int = 2048
    background_timeout_s: int = 60
    onboarding_timeout_s: int = 20  # one synchronous call at onboarding, then heuristic fallback
    background_top_n: int = 20  # market jobs entering someone's top 20 get a background upgrade
    # At most this many background re-reads per day: the free tier's ~200k tokens/day go to people's CVs first.
    background_daily_cap: int = 20
    prompt_versions: FrozenDict = FrozenDict({"cv_extraction": "cv-v1", "job_extraction": "job-v1"})
    # What is sent to the provider, per use (pt-BR descriptions in app/texts.py).
    sends: FrozenDict = FrozenDict({"cv_extraction": ("cv_text",), "job_extraction": ("job_text",)})
    consent_required: tuple[str, ...] = ("cv_extraction",)  # only with the candidate's llm_consent


@dataclass(frozen=True)
class SourceRules:
    """One job source of spec 5.1. Disabled sources are listed, without connectors."""

    enabled: bool
    kind: str  # "ats" | "remote_board" | "github"
    label: str  # shown in the attribution ("via Greenhouse")
    endpoint: str
    terms_url: str | None = None
    terms_note: str = ""
    terms_checked_on: str | None = None  # None = terms check pending
    disabled_reason: str | None = None
    boards: tuple[str, ...] = ()  # ATS board tokens / company slugs
    board_names: FrozenDict = FrozenDict()  # token → company name shown in the attribution
    repos: tuple[str, ...] = ()  # GitHub "owner/repo"
    requests_per_minute: float | None = None
    requests_per_hour: float | None = None
    min_interval_s: float = 0.0  # between two requests to the same source
    max_runs_per_day: int | None = None
    attribution: str = ""  # "Ver vaga original … (via X)"


_DISABLED_MVP = "disabled in the MVP (spec 5.1): no connector; enabling a source is Felipe's decision"
# Terms check of 2026-10-19 (research notes, verified independently): none of the three sources that the
# spec turns on by default grants clear permission to aggregate and redisplay postings (public APIs, no
# prohibition). They first shipped disabled; Felipe, the owner, turned them on on 2026-10-20 (DECISIONS #24).
_OWNER_ENABLED = (
    " Ligada por decisão do dono do projeto em 2026-10-20: os termos (verificados em 2026-10-19) não proíbem, "
    "mas também não dão permissão explícita para agregar e reexibir vagas de terceiros."
)

_GREENHOUSE_BOARDS = FrozenDict(
    {
        "stone": "Stone",
        "btgpactual": "BTG Pactual",
        "inter": "Inter",
        "c6bank": "C6 Bank",
        "xpinc": "XP Inc.",
        "quintoandar": "QuintoAndar",
        "agibank": "Agibank",
        "gympass": "Wellhub (Gympass)",
        "ifoodcarreiras": "iFood",
        "abinbev": "AB InBev",
        "ebanx": "EBANX",
        "vtex": "VTEX",
        "wildlifestudios": "Wildlife Studios",
        "doordashinternational": "DoorDash",
        "rdstation": "RD Station",
        "arenaim": "Arena IM",
        "coderoad": "CodeRoad",
        "turing": "Turing",
        "airbnb": "Airbnb",
        "brex": "Brex",
        "coinbase": "Coinbase",
    }
)
_LEVER_COMPANIES = FrozenDict({"ciandt": "CI&T", "dlocal": "dLocal", "swile": "Swile", "toptal": "Toptal"})

_SOURCES = FrozenDict(
    {
        "greenhouse": SourceRules(
            enabled=True,
            kind="ats",
            label="Greenhouse",
            endpoint="https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true",
            terms_url="https://developers.greenhouse.io/job-board.html",
            terms_note="API pública de job board, documentada para a página de carreiras da própria empresa."
            + _OWNER_ENABLED,
            terms_checked_on="2026-10-19",
            boards=tuple(_GREENHOUSE_BOARDS),
            board_names=_GREENHOUSE_BOARDS,
            requests_per_minute=30,
            min_interval_s=1.0,
            max_runs_per_day=1,
            attribution="Ver vaga original no site da empresa (via Greenhouse)",
        ),
        "lever": SourceRules(
            enabled=True,
            kind="ats",
            label="Lever",
            endpoint="https://api.lever.co/v0/postings/{company}?mode=json",
            terms_url="https://github.com/lever/postings-api",
            terms_note="API pública de vagas; robots.txt pede 1 s entre requisições." + _OWNER_ENABLED,
            terms_checked_on="2026-10-19",
            boards=tuple(_LEVER_COMPANIES),
            board_names=_LEVER_COMPANIES,
            requests_per_minute=30,
            min_interval_s=1.0,
            max_runs_per_day=1,
            attribution="Ver vaga original na página da empresa (via Lever)",
        ),
        "github": SourceRules(
            enabled=True,
            kind="github",
            label="GitHub",
            endpoint="https://api.github.com/repos/{repo}/issues?state=open&per_page=100",
            terms_url="https://docs.github.com/en/site-policy/github-terms/github-terms-of-service",
            terms_note=(
                "Issues de repositórios brasileiros de vagas. API sem token: 60 requisições/hora. Link para a "
                "issue original; labels viram campos declarados; contatos (e-mails, telefones) não são guardados "
                "e o corpo da issue não é reexibido."
            )
            + _OWNER_ENABLED,
            terms_checked_on="2026-10-19",
            repos=("backend-br/vagas", "frontendbr/vagas"),
            requests_per_hour=60,
            min_interval_s=1.0,
            max_runs_per_day=1,
            attribution="Ver a issue original no GitHub",
        ),
        "ashby": SourceRules(
            enabled=False,
            kind="ats",
            label="Ashby",
            endpoint="https://api.ashbyhq.com/posting-api/job-board/{org}",
            terms_url="https://developers.ashbyhq.com/docs/public-job-posting-api",
            terms_note="Public job posting API.",
            disabled_reason=_DISABLED_MVP,
        ),
        "remotive": SourceRules(
            enabled=False,
            kind="remote_board",
            label="Remotive",
            endpoint="https://remotive.com/api/remote-jobs",
            terms_url="https://github.com/remotive-com/remote-jobs-api",
            terms_note=(
                "Link to the job and credit Remotive; at most 4 fetches per day and 2 requests per "
                "minute; do not resubmit jobs to other sites; jobs arrive with a 24 h delay."
            ),
            disabled_reason=_DISABLED_MVP,
            requests_per_minute=2,
            max_runs_per_day=4,
        ),
        "remoteok": SourceRules(
            enabled=False,
            kind="remote_board",
            label="RemoteOK",
            endpoint="https://remoteok.com/api",
            terms_url="https://remoteok.com/api",
            terms_note="Attribution with a link; the first JSON item is a legal notice, not a job.",
            disabled_reason=_DISABLED_MVP,
        ),
        "himalayas": SourceRules(
            enabled=False,
            kind="remote_board",
            label="Himalayas",
            endpoint="https://himalayas.app/jobs/api?limit=100&offset=0",
            terms_url="https://himalayas.app/api",
            terms_note="Structured salary (min, max, currency, period). Check the terms before use.",
            disabled_reason=_DISABLED_MVP,
        ),
        "weworkremotely": SourceRules(
            enabled=False,
            kind="remote_board",
            label="We Work Remotely",
            endpoint="https://weworkremotely.com/remote-jobs.rss",
            terms_url="https://weworkremotely.com/api",
            terms_note="RSS; the company comes in the title ('Company: Role').",
            terms_checked_on="2026-10-19",
            disabled_reason=(
                "proibido pelos termos: a API não pode ser usada para construir 'a job advertising or job search "
                "service'; nunca ligar sem autorização por escrito"
            ),
        ),
    }
)


@dataclass(frozen=True)
class IngestRules:
    sources: FrozenDict = _SOURCES
    close_after_missed_runs: int = 2  # a job missing from 2 consecutive runs of its source is closed
    user_agent: str = f"Encaixe/{__version__} (+{DEFAULT_SOURCE_URL}; open-rules job matching; non-commercial)"
    backoff_s: tuple[float, ...] = (2.0, 8.0, 30.0)  # waits after 429/5xx before giving up on a board
    timeout_s: float = 20.0
    dedup_keys: tuple[str, ...] = ("company", "title", "city")  # cross-source dedup (normalized)


@dataclass(frozen=True)
class AuthRules:
    """Magic-link login: no passwords; a one-time link by e-mail, then an HttpOnly session cookie."""

    login_link_minutes: int = 15
    session_days: int = 30
    min_seconds_between_links: int = 60  # per e-mail
    max_links_per_hour: int = 5  # per e-mail
    max_links_per_day: int = 300  # all e-mails together: protects the sender's daily quota
    terms_version: str = "2026-10-21"  # accepting a newer version is asked at the next login


@dataclass(frozen=True)
class LimitRules:
    """Input limits of a public service (uploads and page sizes)."""

    cv_max_bytes: int = 5 * 1024 * 1024
    cv_max_pdf_pages: int = 10
    cv_max_chars: int = 30_000
    deck_max_limit: int = 200


@dataclass(frozen=True)
class ScopeRules:
    """The MVP is a sample of one region (owner's decision, 2026-10-20): onsite/hybrid jobs in Santa Catarina and
    remote jobs open to people in Brazil. Applied to market postings at ingestion (app/ingest/scope.py): out-of-scope
    postings are not stored, only counted.
    """

    country: str = "BR"
    region: str = "SC"  # state code of the onsite/hybrid sample


@dataclass(frozen=True)
class Rules:
    filters: FilterRules = field(default_factory=FilterRules)
    criteria: CriteriaRules = field(default_factory=CriteriaRules)
    precision: PrecisionRules = field(default_factory=PrecisionRules)
    requirements: RequirementRules = field(default_factory=RequirementRules)
    good_fit: GoodFitRules = field(default_factory=GoodFitRules)
    aggregation: AggregationRules = field(default_factory=AggregationRules)
    feedback: FeedbackRules = field(default_factory=FeedbackRules)
    exploration: ExplorationRules = field(default_factory=ExplorationRules)
    rankers: RankerRules = field(default_factory=RankerRules)
    reasons: ReasonRules = field(default_factory=ReasonRules)
    events: EventRules = field(default_factory=EventRules)
    revisions: RevisionRules = field(default_factory=RevisionRules)
    privacy: PrivacyRules = field(default_factory=PrivacyRules)
    workday: WorkdayRules = field(default_factory=WorkdayRules)
    seniority: SeniorityRules = field(default_factory=SeniorityRules)
    currency: CurrencyRules = field(default_factory=CurrencyRules)
    projection: ProjectionRules = field(default_factory=ProjectionRules)
    embeddings: EmbeddingRules = field(default_factory=EmbeddingRules)
    llm: LlmRules = field(default_factory=LlmRules)
    ingest: IngestRules = field(default_factory=IngestRules)
    scope: ScopeRules = field(default_factory=ScopeRules)
    limits: LimitRules = field(default_factory=LimitRules)
    auth: AuthRules = field(default_factory=AuthRules)


RULES = Rules()


def _plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"unsupported value in RULES: {value!r}")


def rules_as_dict(rules: Rules | None = None) -> dict[str, Any]:
    """Plain JSON-ready copy of the rules (tuples become lists, mapping keys become strings)."""
    return _plain(RULES if rules is None else rules)


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _hash_rules(rules: Rules) -> str:
    return hashlib.sha256(canonical_json(rules_as_dict(rules)).encode("utf-8")).hexdigest()[:12]


@lru_cache(maxsize=1)
def _default_rules_hash() -> str:
    return _hash_rules(RULES)


def rules_hash(rules: Rules | None = None) -> str:
    """First 12 hex chars of the sha256 of the rules' canonical JSON."""
    if rules is None or rules is RULES:
        return _default_rules_hash()
    return _hash_rules(rules)


# --------------------------------------------------------------------------- Settings


def read_env_file(path: Path | None) -> dict[str, str]:
    """Tiny .env parser: KEY=VALUE lines, '#' comments, optional 'export ' and optional quotes."""
    values: dict[str, str] = {}
    if path is None:
        return values
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key or not key.replace("_", "").isalnum():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        else:
            comment = value.find(" #")
            if comment != -1:
                value = value[:comment].rstrip()
        values[key] = value
    return values


@dataclass(frozen=True)
class Settings:
    var_dir: Path
    db_url: str
    embeddings: str  # onnx | tfidf | fake
    groq_api_key: str | None = field(default=None, repr=False)
    llm_model: str = RULES.llm.model
    embed_threads: int = RULES.embeddings.threads
    log_level: str = "INFO"
    env: str = "dev"  # dev | prod (prod: no demo data, no dev routes, no clock offset, fail fast)
    base_url: str = "http://127.0.0.1:8000"  # public address, used in the e-mailed login links
    source_url: str = DEFAULT_SOURCE_URL  # the AGPL source offered to users (site footer, rules page)
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = field(default=None, repr=False)
    smtp_from: str | None = None
    allowed_emails: tuple[str, ...] = ()  # ALLOWED_EMAILS: invite-only beta when set; empty = open sign-up

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None, env_file: Path | None = DEFAULT_ENV_FILE) -> Settings:
        env: dict[str, str] = read_env_file(env_file)
        env.update(os.environ if environ is None else environ)

        var_dir = Path(env.get("ENCAIXE_VAR_DIR") or DEFAULT_VAR_DIR).expanduser().resolve()
        default_db_url = f"sqlite:///{(var_dir / 'encaixe.db').as_posix()}"
        db_url = (env.get("ENCAIXE_DB_URL") or "").strip() or default_db_url

        embeddings = (env.get("EMBEDDINGS") or "onnx").strip().lower()
        embeddings = EMBEDDING_ALIASES.get(embeddings, embeddings)
        if embeddings not in EMBEDDING_BACKENDS:
            raise ValueError(f"EMBEDDINGS must be one of {EMBEDDING_BACKENDS}, got {embeddings!r}")

        raw_threads = (env.get("EMBED_THREADS") or "").strip()
        try:
            embed_threads = int(raw_threads) if raw_threads else RULES.embeddings.threads
        except ValueError:
            raise ValueError(f"EMBED_THREADS must be an integer, got {raw_threads!r}") from None
        if embed_threads < 1:
            raise ValueError(f"EMBED_THREADS must be >= 1, got {embed_threads}")

        log_level = (env.get("LOG_LEVEL") or "INFO").strip().upper()
        if log_level == "WARN":
            log_level = "WARNING"
        if log_level not in LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of {LOG_LEVELS}, got {log_level!r}")

        app_env = (env.get("ENCAIXE_ENV") or "dev").strip().lower()
        if app_env not in ENVIRONMENTS:
            raise ValueError(f"ENCAIXE_ENV must be one of {ENVIRONMENTS}, got {app_env!r}")
        raw_port = (env.get("SMTP_PORT") or "587").strip()
        if not raw_port.isdigit():
            raise ValueError(f"SMTP_PORT must be an integer, got {raw_port!r}")

        def opt(key: str) -> str | None:
            return (env.get(key) or "").strip() or None

        return cls(
            var_dir=var_dir,
            db_url=db_url,
            embeddings=embeddings,
            groq_api_key=opt("GROQ_API_KEY"),
            llm_model=opt("LLM_MODEL") or RULES.llm.model,
            embed_threads=embed_threads,
            log_level=log_level,
            env=app_env,
            base_url=(opt("BASE_URL") or cls.base_url).rstrip("/"),
            source_url=opt("ENCAIXE_SOURCE_URL") or DEFAULT_SOURCE_URL,
            smtp_host=opt("SMTP_HOST"),
            smtp_port=int(raw_port),
            smtp_user=opt("SMTP_USER"),
            smtp_password=opt("SMTP_PASSWORD"),
            smtp_from=opt("SMTP_FROM"),
            allowed_emails=tuple(e.strip().lower() for e in (opt("ALLOWED_EMAILS") or "").split(",") if e.strip()),
        )

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    def prod_problems(self) -> list[str]:
        """What keeps this configuration from running in production (empty = fine)."""
        problems = []
        if not self.base_url.startswith("https://"):
            problems.append("BASE_URL must be the public https address")
        if not (self.smtp_host and self.smtp_from):
            problems.append("SMTP_HOST and SMTP_FROM are required (login links go by e-mail)")
        if self.embeddings != "onnx":
            problems.append("EMBEDDINGS must be onnx in production")
        return problems

    @property
    def llm_enabled(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def models_dir(self) -> Path:
        return self.var_dir / "models"

    @property
    def cache_dir(self) -> Path:
        return self.var_dir / "cache"

    @property
    def http_cache_dir(self) -> Path:
        return self.cache_dir / "http"

    @property
    def snapshots_dir(self) -> Path:
        return self.var_dir / "snapshots"

    @property
    def uploads_dir(self) -> Path:
        return self.var_dir / "uploads"

    @property
    def eval_dir(self) -> Path:
        return self.var_dir / "eval"

    def ensure_var_dirs(self) -> list[Path]:
        dirs = [
            self.var_dir,
            self.models_dir,
            self.cache_dir,
            self.http_cache_dir,
            self.snapshots_dir,
            self.uploads_dir,
            self.eval_dir,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
        return dirs


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()


def reset_settings() -> None:
    """Forget the cached settings (tests change the environment between cases)."""
    get_settings.cache_clear()
