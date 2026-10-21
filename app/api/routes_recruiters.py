"""Recruiter side (lado B): platform jobs, blind deck, matches."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, col, select

from app import texts
from app.auth import current_account, dev_only, owned_job, owned_recruiter, session_recruiter
from app.companies import get_or_create_company
from app.db import get_session
from app.events import applicants
from app.extraction.job import RawPosting
from app.jobs import company_name, ensure_job_vectors, upsert_job
from app.models import Account, Candidate, Company, Job, Match, Recruiter
from app.privacy import candidate_card_profile
from app.profiles import current_profile
from app.ranking.deck import candidate_card, displayable_description, job_summary, recruiter_deck
from app.ranking.service import rank_for_job
from app.schemas import JobDraft

router = APIRouter(prefix="/api", tags=["recruiters"])


def _owned_job(session: Session, rid: int, jid: int) -> Job:
    job = session.get(Job, jid)
    if job is None or job.owner_recruiter_id != rid:
        raise HTTPException(404, "vaga não encontrada para este recrutador")
    return job


@router.get("/recruiters", dependencies=[Depends(dev_only)])
def list_recruiters(session: Session = Depends(get_session)) -> list:
    out = []
    for r in session.exec(select(Recruiter).order_by(col(Recruiter.id))).all():
        n = len(session.exec(select(Job.id).where(Job.owner_recruiter_id == r.id)).all())
        out.append(
            {
                "id": r.id,
                "name": r.name,
                "company": company_name(session, r.company_id),
                "synthetic": r.synthetic,
                "n_jobs": n,
            }
        )
    return out


class RecruiterIn(BaseModel):
    name: str
    company: str


@router.post("/recruiters")
def create_recruiter(
    body: RecruiterIn, session: Session = Depends(get_session), account: Account = Depends(current_account)
) -> dict:
    if account.recruiter_id is not None:
        raise HTTPException(409, "esta conta já tem um perfil de recrutador")
    company = get_or_create_company(session, body.company)
    if company is None:
        raise HTTPException(422, "informe a empresa")
    rec = Recruiter(name=body.name.strip(), company_id=company.id)  # type: ignore[arg-type]
    session.add(rec)
    session.flush()
    account.recruiter_id = rec.id
    session.add(account)
    session.commit()
    return {"id": rec.id, "name": rec.name, "company": company.name}


@router.get("/recruiters/{rid}/jobs")
def recruiter_jobs(
    rid: int, session: Session = Depends(get_session), rec: Recruiter = Depends(owned_recruiter)
) -> list:
    out = []
    for job in session.exec(select(Job).where(Job.owner_recruiter_id == rid).order_by(col(Job.id))).all():
        n_matches = len(session.exec(select(Match.id).where(Match.job_id == job.id)).all())
        out.append(
            {
                "job": job_summary(session, job),
                "n_applicants": len(applicants(session, job.id)),  # type: ignore[arg-type]
                "n_matches": n_matches,
            }
        )
    return out


class JobParseIn(BaseModel):
    text: str
    title: str | None = None
    location_text: str | None = None
    company: str | None = None
    use_llm: bool = True


@router.post("/jobs/parse")
def parse_job(body: JobParseIn, rec: Recruiter = Depends(session_recruiter)) -> dict:
    """Pasted job text → draft for review. Title = first line when not given."""
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "cole o texto da vaga")
    title = body.title
    if not title:
        title, _, text = text.partition("\n")
    from app.llm.jobs import extract_job_for_publishing

    draft = extract_job_for_publishing(
        RawPosting(
            title=title.strip(),
            description=text,
            company=body.company,
            location_text=body.location_text,
            source="platform",
        ),
        use_llm=body.use_llm,
    )
    out = draft.model_dump(mode="json")
    out["notice"] = texts.RECRUITER_TRANSPARENCY_NOTICE
    return out


class PublishIn(BaseModel):
    draft: dict  # the reviewed draft, as returned by /jobs/parse (extra keys such as "notice" are ignored)


@router.post("/recruiters/{rid}/jobs")
def publish_job(
    rid: int, body: PublishIn, session: Session = Depends(get_session), rec: Recruiter = Depends(owned_recruiter)
) -> dict:
    company = session.get(Company, rec.company_id)
    try:
        reviewed = JobDraft.model_validate({k: v for k, v in body.draft.items() if k in JobDraft.model_fields})
    except ValueError as exc:
        raise HTTPException(422, f"rascunho inválido: {exc}") from exc
    draft = reviewed.model_copy(update={"company": company.name if company else reviewed.company})
    res = upsert_job(
        session,
        draft,
        source="platform",
        source_id=f"r{rid}-{uuid.uuid4().hex[:10]}",
        origin="platform",
        owner_recruiter_id=rid,
    )
    ensure_job_vectors(session)
    session.commit()
    return {"job_id": res.job.id, "notice": texts.RECRUITER_TRANSPARENCY_NOTICE}


class JobStatusIn(BaseModel):
    status: str
    recruiter_id: int | None = None  # ignored: the recruiter comes from the session


@router.patch("/jobs/{jid}")
def set_job_status(
    jid: int,
    body: JobStatusIn,
    session: Session = Depends(get_session),
    rec: Recruiter = Depends(session_recruiter),
) -> dict:
    job = _owned_job(session, rec.id, jid)  # type: ignore[arg-type]
    if body.status not in ("open", "paused", "closed"):
        raise HTTPException(422, "status inválido")
    job.status = body.status
    session.add(job)
    from app.jobs import bump_jobs_version

    bump_jobs_version(session)
    session.commit()
    return {"job_id": jid, "status": job.status}


@router.get("/jobs/{jid}")
def get_job(jid: int, session: Session = Depends(get_session), account: Account = Depends(current_account)) -> dict:
    job = session.get(Job, jid)
    if job is None:
        raise HTTPException(404, "vaga não encontrada")
    return {
        "job": job_summary(session, job),
        "description_text": displayable_description(job),
        "requires": job.requires,
        "offers": job.offers,
        "eligibility": job.eligibility,
        "provenance": job.provenance,
    }


@router.get("/recruiters/{rid}/jobs/{jid}/deck")
def deck(
    rid: int,
    jid: int,
    session_id: str | None = None,
    limit: int = 20,
    ranker: str | None = None,
    aggregator: str | None = None,
    session: Session = Depends(get_session),
    job: Job = Depends(owned_job),
) -> dict:
    return recruiter_deck(session, rid, jid, session_id, limit, ranker, aggregator)


@router.get("/recruiters/{rid}/jobs/{jid}/candidates/{cid}")
def candidate_detail(
    rid: int, jid: int, cid: int, session: Session = Depends(get_session), job: Job = Depends(owned_job)
) -> dict:
    result = rank_for_job(session, jid, applicants=applicants(session, jid))
    item = next((it for it in result.items if it.item_id == cid), None)
    if item is None:
        raise HTTPException(404, "candidato fora da lista desta vaga")
    card = candidate_card(session, item, result, jid, [])
    card["rank_meta"]["slot"] = "direct"
    return card


@router.get("/recruiters/{rid}/matches")
def matches(rid: int, session: Session = Depends(get_session), rec: Recruiter = Depends(owned_recruiter)) -> list:
    out = []
    for m in session.exec(select(Match).where(Match.recruiter_id == rid).order_by(col(Match.ts).desc())).all():
        cand = session.get(Candidate, m.candidate_id)
        job = session.get(Job, m.job_id)
        profile = current_profile(session, cand) if cand else None
        out.append(
            {
                "match_id": m.id,
                "ts": m.ts.isoformat(),
                "job": job_summary(session, job) if job else None,
                "candidate": candidate_card_profile(profile, True, cand.contact) if profile and cand else None,
                "contact_released_text": texts.PRIVACY_TEXTS["contact_released"],
            }
        )
    return out


@router.get("/recruiters/{rid}/jobs/{jid}/funnel")
def job_funnel(rid: int, jid: int, session: Session = Depends(get_session), job: Job = Depends(owned_job)) -> dict:
    from app.explore.recruiter import funnel

    return funnel(session, jid)


@router.get("/recruiters/{rid}/jobs/{jid}/explore")
def job_explore(rid: int, jid: int, session: Session = Depends(get_session), job: Job = Depends(owned_job)) -> dict:
    from app.explore.recruiter import explore

    return explore(session, jid)
