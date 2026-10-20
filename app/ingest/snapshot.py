"""Snapshots (spec 5.1): freeze the jobs (with provenance and method) and the LLM cache entries they used.

Real jobs change every day; the demo and the replay evaluation run on a snapshot, so they are reproducible.
Snapshots live in var/snapshots (never in git). Loading recomputes vectors and the market map afterwards.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from sqlmodel import Session, col, select

from app import clock
from app.companies import get_or_create_company
from app.config import get_settings, rules_hash
from app.jobs import bump_jobs_version
from app.models import Company, Job, JobVersion, LlmCache

JOB_FIELDS = (
    "origin",
    "source",
    "source_id",
    "url",
    "title",
    "description_text",
    "location_text",
    "city_id",
    "country",
    "requires",
    "offers",
    "eligibility",
    "job_tz",
    "domains",
    "provenance",
    "labels",
    "version",
    "extraction_method",
    "content_hash",
    "status",
    "missed_runs",
)


def snapshot_path(name: str) -> Path:
    return get_settings().snapshots_dir / f"{name}.json.gz"


def _llm_keys(job: Job) -> set[str]:
    return {v.get("cache_key") for v in (job.provenance or {}).values() if isinstance(v, dict) and v.get("cache_key")}  # type: ignore[misc]


def save_snapshot(session: Session, name: str) -> Path:
    jobs = session.exec(select(Job).where(Job.origin == "market")).all()
    keys: set[str] = set()
    out_jobs = []
    for job in jobs:
        company = session.get(Company, job.company_id) if job.company_id else None
        versions = session.exec(
            select(JobVersion).where(JobVersion.job_id == job.id).order_by(col(JobVersion.version))
        ).all()
        out_jobs.append(
            {
                **{f: getattr(job, f) for f in JOB_FIELDS},
                "company": company.name if company else None,
                "first_seen": job.first_seen.isoformat(),
                "last_seen": job.last_seen.isoformat(),
                "versions": [{"version": v.version, "ts": v.ts.isoformat(), "snapshot": v.snapshot} for v in versions],
            }
        )
        keys |= _llm_keys(job)
    cache = (
        [c.model_dump(mode="json") for c in session.exec(select(LlmCache).where(col(LlmCache.key).in_(keys)))]
        if keys
        else []
    )
    data = {
        "name": name,
        "saved_at": clock.now().isoformat(),
        "rules_hash": rules_hash(),
        "jobs": out_jobs,
        "llm_cache": cache,
    }
    path = snapshot_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    return path


def load_snapshot(session: Session, name: str) -> dict[str, int]:
    """Restore the market jobs of a snapshot; market jobs absent from it are closed. Vectors are recomputed."""
    from datetime import datetime

    with gzip.open(snapshot_path(name), "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    restored, created = set(), 0
    for item in data["jobs"]:
        company = get_or_create_company(session, item.get("company"))
        job = session.exec(select(Job).where(Job.source == item["source"], Job.source_id == item["source_id"])).first()
        if job is None:
            job = Job(source=item["source"], source_id=item["source_id"], title=item["title"])
            created += 1
        for f in JOB_FIELDS:
            setattr(job, f, item[f])
        job.company_id = company.id if company else None
        job.first_seen = datetime.fromisoformat(item["first_seen"])
        job.last_seen = datetime.fromisoformat(item["last_seen"])
        session.add(job)
        session.flush()
        have = {v.version for v in session.exec(select(JobVersion).where(JobVersion.job_id == job.id))}
        for v in item["versions"]:
            if v["version"] not in have:
                session.add(
                    JobVersion(
                        job_id=job.id,
                        version=v["version"],  # type: ignore[arg-type]
                        ts=datetime.fromisoformat(v["ts"]),
                        snapshot=v["snapshot"],
                    )
                )
        restored.add(job.id)
    closed = 0
    for job in session.exec(select(Job).where(Job.origin == "market", Job.status == "open")).all():
        if job.id not in restored:
            job.status = "closed"
            session.add(job)
            closed += 1
    for entry in data.get("llm_cache", []):
        if session.get(LlmCache, entry["key"]) is None:
            entry = dict(entry)
            entry["created_at"] = datetime.fromisoformat(entry["created_at"])
            session.add(LlmCache(**entry))
    bump_jobs_version(session)
    session.flush()
    return {
        "jobs": len(restored),
        "created": created,
        "closed_not_in_snapshot": closed,
        "llm_cache": len(data.get("llm_cache", [])),
    }


def list_snapshots() -> list[str]:
    d = get_settings().snapshots_dir
    return sorted(p.name.removesuffix(".json.gz") for p in d.glob("*.json.gz")) if d.exists() else []
