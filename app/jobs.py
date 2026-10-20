"""Job service: upsert from a draft, versioning, vectors, and the canonical view of a stored job."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from sqlmodel import Session, col, select

from app import clock
from app import taxonomy as tax_mod
from app.companies import get_or_create_company
from app.db import from_blob, to_blob
from app.embeddings import embed_texts, get_embedder, space_id
from app.embeddings.texts import job_embed_text, job_title_text
from app.extraction.job import role_summary
from app.models import Company, Job, JobVersion, Setting
from app.schemas import Eligibility, JobDraft, Offers, Requires
from app.textnorm import squash

log = logging.getLogger(__name__)

SPACE_KEY = "embedding_space_jobs"
JOBS_VERSION_KEY = "jobs_version"


def content_hash(title: str, description: str, location: str | None) -> str:
    raw = "\x1f".join([squash(title), squash(description), squash(location or "")])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class UpsertResult:
    job: Job
    status: str  # new | updated | unchanged | reopened


def bump_jobs_version(session: Session) -> None:
    """Invalidate in-memory indexes built from jobs."""
    row = session.get(Setting, JOBS_VERSION_KEY)
    if row is None:
        session.add(Setting(key=JOBS_VERSION_KEY, value=1))
    else:
        row.value = int(row.value or 0) + 1
        session.add(row)


def _apply(job: Job, draft: JobDraft) -> None:
    tax = tax_mod.load()
    job.title = draft.title
    job.description_text = draft.description_text
    job.location_text = draft.location_text
    job.city_id = draft.city_id
    job.country = draft.country
    job.requires = draft.requires.model_dump(mode="json")
    job.offers = draft.offers.model_dump(mode="json")
    job.eligibility = draft.eligibility.model_dump(mode="json")
    job.job_tz = draft.job_tz
    job.provenance = {k: v.model_dump(mode="json") for k, v in draft.provenance.items()}
    job.domains = tax.job_domains([*draft.requires.skills_must, *draft.requires.skills_nice])
    job.extraction_method = draft.method


def upsert_job(
    session: Session,
    draft: JobDraft,
    *,
    source: str,
    source_id: str,
    origin: str = "market",
    url: str | None = None,
    labels: list[str] | None = None,
    owner_recruiter_id: int | None = None,
) -> UpsertResult:
    now = clock.now()
    company = get_or_create_company(session, draft.company)
    h = content_hash(draft.title, draft.description_text, draft.location_text)
    job = session.exec(select(Job).where(Job.source == source, Job.source_id == source_id)).first()
    if job is None:
        job = Job(
            source=source,
            source_id=source_id,
            title=draft.title,
            origin=origin,
            url=url,
            owner_recruiter_id=owner_recruiter_id,
            company_id=company.id if company else None,
            labels=list(labels or []),
            content_hash=h,
            first_seen=now,
            last_seen=now,
            status="open",
        )
        _apply(job, draft)
        session.add(job)
        session.flush()
        session.add(JobVersion(job_id=job.id, version=1, ts=now, snapshot=draft.model_dump(mode="json")))
        bump_jobs_version(session)
        return UpsertResult(job, "new")
    status = "unchanged"
    job.last_seen = now
    job.missed_runs = 0
    if job.status == "closed":
        job.status = "open"
        status = "reopened"
    if job.content_hash != h:
        job.content_hash = h
        job.version += 1
        _apply(job, draft)
        job.labels = list(labels or job.labels)
        job.url = url or job.url
        if company:
            job.company_id = company.id
        session.add(JobVersion(job_id=job.id, version=job.version, ts=now, snapshot=draft.model_dump(mode="json")))
        status = "updated"
    session.add(job)
    if status != "unchanged":
        bump_jobs_version(session)
    return UpsertResult(job, status)


def reextract_job(session: Session, job: Job, draft: JobDraft) -> None:
    """A better extraction (e.g. LLM) of the SAME posting: fields and vectors change, the version does not."""
    _apply(job, draft)
    session.add(job)
    latest = latest_version(session, job.id)  # type: ignore[arg-type]
    if latest is not None:
        latest.snapshot = draft.model_dump(mode="json")
        latest.embedding = None
        latest.title_embedding = None
        session.add(latest)
    bump_jobs_version(session)


def latest_version(session: Session, job_id: int) -> JobVersion | None:
    return session.exec(
        select(JobVersion).where(JobVersion.job_id == job_id).order_by(col(JobVersion.version).desc())
    ).first()


def job_draft(job: Job, company_name: str | None = None) -> JobDraft:
    """Canonical view of a stored job (what extraction produced, possibly upgraded by the LLM)."""
    return JobDraft(
        title=job.title,
        company=company_name,
        description_text=job.description_text,
        location_text=job.location_text,
        city_id=job.city_id,
        country=job.country,
        requires=Requires.model_validate(job.requires or {}),
        offers=Offers.model_validate(job.offers or {}),
        eligibility=Eligibility.model_validate(job.eligibility or {}),
        job_tz=job.job_tz,
        method=job.extraction_method if job.extraction_method in ("heuristic", "llm") else "heuristic",  # type: ignore[arg-type]
    )


def job_texts(job: Job) -> tuple[str, str]:
    """(embed text, title text) of a job."""
    draft = job_draft(job)
    summary = role_summary(draft)
    return (
        job_embed_text(job.title, draft.requires.skills_must, draft.requires.skills_nice, summary),
        job_title_text(job.title),
    )


def ensure_job_vectors(session: Session, only_open: bool = False) -> int:
    """Embed the latest version of every job missing vectors (or with vectors from another space)."""
    embedder = get_embedder()
    current_space = space_id(embedder)
    row = session.get(Setting, SPACE_KEY)
    stale_space = row is None or row.value != current_space
    q = select(Job)
    if only_open:
        q = q.where(Job.status == "open")
    jobs = {j.id: j for j in session.exec(q).all()}
    versions: list[JobVersion] = []
    for jid in jobs:
        v = latest_version(session, jid)  # type: ignore[arg-type]
        if v is None:
            continue
        if stale_space or v.embedding is None or v.title_embedding is None:
            versions.append(v)
    if not versions:
        if stale_space:
            session.add(Setting(key=SPACE_KEY, value=current_space) if row is None else row)
            if row is not None:
                row.value = current_space
        return 0
    texts = [job_texts(jobs[v.job_id]) for v in versions]
    emb = embed_texts([t[0] for t in texts], embedder)
    title_emb = embed_texts([t[1] for t in texts], embedder)
    for v, e, te in zip(versions, emb, title_emb, strict=True):
        v.embedding = to_blob(e)
        v.title_embedding = to_blob(te)
        session.add(v)
    if row is None:
        session.add(Setting(key=SPACE_KEY, value=current_space))
    else:
        row.value = current_space
        session.add(row)
    bump_jobs_version(session)
    log.info("embedded %d job versions (%s)", len(versions), current_space)
    return len(versions)


def job_vector(session: Session, job_id: int, version: int | None = None):  # -> np.ndarray | None
    q = select(JobVersion).where(JobVersion.job_id == job_id)
    if version is not None:
        q = q.where(JobVersion.version == version)
    v = session.exec(q.order_by(col(JobVersion.version).desc())).first()
    return from_blob(v.embedding) if v and v.embedding else None


def company_name(session: Session, company_id: int | None) -> str | None:
    if company_id is None:
        return None
    c = session.get(Company, company_id)
    return c.name if c else None
