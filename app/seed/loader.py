"""Load the fictional seed: 60 market jobs (offline mode, tests) and the synthetic B side."""

from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import Session, select

from app.companies import get_or_create_company
from app.extraction.job import RawPosting, extract_job
from app.jobs import upsert_job
from app.models import Job, Recruiter

SEED_DIR = Path(__file__).parent
PERSONAS_DIR = SEED_DIR / "personas"


def seed_jobs_data() -> list[dict]:
    return json.loads((SEED_DIR / "seed_jobs.json").read_text(encoding="utf-8"))


def load_seed_jobs(session: Session) -> dict[str, int]:
    counts = {"new": 0, "updated": 0, "unchanged": 0, "reopened": 0}
    for item in seed_jobs_data():
        raw = RawPosting(
            title=item["title"],
            description=item["description"],
            company=item["company"],
            location_text=item["location_text"],
            source="seed",
            source_id=item["id"],
            url=item.get("url"),
        )
        result = upsert_job(
            session, extract_job(raw), source="seed", source_id=item["id"], origin="market", url=item.get("url")
        )
        counts[result.status] += 1
    session.flush()
    return counts


def load_recruiters(session: Session) -> list[Recruiter]:
    """5 fictional companies, one recruiter each, and their platform jobs (idempotent)."""
    data = json.loads((SEED_DIR / "recruiters.json").read_text(encoding="utf-8"))
    out: list[Recruiter] = []
    for entry in data:
        company = get_or_create_company(session, entry["company"])
        assert company is not None
        rec = session.exec(
            select(Recruiter).where(Recruiter.name == entry["recruiter"], Recruiter.company_id == company.id)
        ).first()
        if rec is None:
            rec = Recruiter(name=entry["recruiter"], company_id=company.id, synthetic=True)  # type: ignore[arg-type]
            session.add(rec)
            session.flush()
        for n, job in enumerate(entry["jobs"], start=1):
            raw = RawPosting(
                title=job["title"],
                description=job["description"],
                company=entry["company"],
                location_text=job["location_text"],
                source="platform",
            )
            upsert_job(
                session,
                extract_job(raw),
                source="platform",
                source_id=f"seed-r{rec.id}-{n}",
                origin="platform",
                owner_recruiter_id=rec.id,
            )
        out.append(rec)
    session.flush()
    return out


def persona_text(name: str) -> str:
    return (PERSONAS_DIR / f"{name}.txt").read_text(encoding="utf-8")


def open_job_count(session: Session) -> int:
    return len(session.exec(select(Job.id).where(Job.status == "open")).all())
