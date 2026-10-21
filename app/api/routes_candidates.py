"""Candidate side (lado C)."""

from __future__ import annotations

import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import Session, col, select

from app import texts
from app.config import RULES, get_settings
from app.db import get_session
from app.events import match_for
from app.events.feedback import rejection_feedback
from app.events.status import application_status, candidate_judgments
from app.models import Candidate, Job
from app.privacy import export_candidate, purge_candidate
from app.profiles import create_candidate, current_profile, revisions, save_profile
from app.ranking.deck import candidate_deck, candidate_filtered, displayable_description, job_card, job_summary
from app.ranking.service import job_features_for, rank_for_candidate
from app.schemas import CandidateProfile

router = APIRouter(prefix="/api/candidates", tags=["candidates"])


def _candidate(session: Session, candidate_id: int) -> Candidate:
    cand = session.get(Candidate, candidate_id)
    if cand is None:
        raise HTTPException(404, "candidato não encontrado")
    return cand


def pdf_to_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if len(reader.pages) > RULES.limits.cv_max_pdf_pages:
        raise HTTPException(413, f"o PDF tem mais de {RULES.limits.cv_max_pdf_pages} páginas")
    return "\n".join((page.extract_text() or "") for page in reader.pages)


@router.post("/parse")
async def parse_cv(
    text: str | None = Form(None),
    file: UploadFile | None = File(None),
    llm_consent: bool = Form(False),
) -> dict:
    """CV text or PDF → draft for review (declared × inferred chips). Nothing is saved yet."""
    limits = RULES.limits
    if file is not None:
        raw = await file.read(limits.cv_max_bytes + 1)
        if len(raw) > limits.cv_max_bytes:
            raise HTTPException(413, f"o arquivo passa de {limits.cv_max_bytes // (1024 * 1024)} MB")
        cv_text = pdf_to_text(raw) if (file.filename or "").lower().endswith(".pdf") else raw.decode("utf-8", "ignore")
    else:
        cv_text = text or ""
    if len(cv_text) > limits.cv_max_chars:
        raise HTTPException(413, f"o texto do CV passa de {limits.cv_max_chars} caracteres")
    if not cv_text.strip():
        raise HTTPException(422, "cole o texto do CV ou envie um PDF")
    from app.llm.onboarding import extract_cv_for_onboarding

    draft = extract_cv_for_onboarding(cv_text, llm_consent)
    return draft.model_dump(mode="json")


class CreateCandidateIn(BaseModel):
    profile: CandidateProfile
    visible_to_recruiters: bool | None = None
    llm_consent: bool = False
    llm_cache_key: str | None = None  # from the parsed draft: purged together with the candidate


@router.post("")
def create(body: CreateCandidateIn, session: Session = Depends(get_session)) -> dict:
    from app.models import Setting

    res = create_candidate(session, body.profile, visible=body.visible_to_recruiters, llm_consent=body.llm_consent)
    if body.llm_cache_key:
        session.add(Setting(key=f"llm_cv_cache:{res.candidate.id}:{body.llm_cache_key}", value=body.llm_cache_key))
    session.commit()
    return {
        "candidate_id": res.candidate.id,
        "revision_id": res.revision.id if res.revision else None,
        "kind": res.kind,
    }


@router.get("")
def list_candidates(synthetic: bool | None = None, limit: int = 200, session: Session = Depends(get_session)) -> list:
    q = select(Candidate).order_by(col(Candidate.synthetic), col(Candidate.id).desc())
    if synthetic is not None:
        q = q.where(Candidate.synthetic == synthetic)
    return [
        {"id": c.id, "name": c.name, "headline": c.headline, "synthetic": c.synthetic}
        for c in session.exec(q.limit(limit)).all()
    ]


@router.get("/{candidate_id}")
def get_candidate(candidate_id: int, session: Session = Depends(get_session)) -> dict:
    cand = _candidate(session, candidate_id)
    profile = current_profile(session, cand)
    return {
        "id": cand.id,
        "synthetic": cand.synthetic,
        "visible_to_recruiters": cand.visible_to_recruiters,
        "llm_consent": cand.llm_consent,
        "current_revision_id": cand.current_revision_id,
        "profile": profile.model_dump(mode="json") if profile else None,
        "revisions": [{"id": r.id, "ts": r.ts.isoformat(), "kind": r.kind} for r in revisions(session, candidate_id)],
    }


@router.put("/{candidate_id}/profile")
def update_profile(candidate_id: int, profile: CandidateProfile, session: Session = Depends(get_session)) -> dict:
    cand = _candidate(session, candidate_id)
    res = save_profile(session, cand, profile)
    session.commit()
    return {"changed": res.changed, "revision_id": res.revision.id if res.revision else None, "kind": res.kind}


class SettingsIn(BaseModel):
    visible_to_recruiters: bool | None = None
    llm_consent: bool | None = None


@router.patch("/{candidate_id}/settings")
def update_settings(candidate_id: int, body: SettingsIn, session: Session = Depends(get_session)) -> dict:
    cand = _candidate(session, candidate_id)
    if body.visible_to_recruiters is not None:
        cand.visible_to_recruiters = body.visible_to_recruiters
    if body.llm_consent is not None:
        cand.llm_consent = body.llm_consent
    session.add(cand)
    from app.profiles import bump_candidates_version

    bump_candidates_version(session)
    session.commit()
    return {"visible_to_recruiters": cand.visible_to_recruiters, "llm_consent": cand.llm_consent}


@router.get("/{candidate_id}/deck")
def deck(
    candidate_id: int,
    session_id: str | None = None,
    limit: int = 20,
    ranker: str | None = None,
    aggregator: str | None = None,
    session: Session = Depends(get_session),
) -> dict:
    _candidate(session, candidate_id)
    limit = max(1, min(limit, RULES.limits.deck_max_limit))
    if get_settings().is_prod:  # ranker overrides are a dev-panel tool: production serves the public default
        ranker = aggregator = None
    out = candidate_deck(session, candidate_id, session_id, limit, ranker, aggregator)
    from app.llm.worker import enqueue_top_market_jobs

    enqueue_top_market_jobs(session, [c["item_id"] for c in out["cards"]])
    session.commit()
    return out


@router.get("/{candidate_id}/filtered")
def filtered(candidate_id: int, session: Session = Depends(get_session)) -> dict:
    _candidate(session, candidate_id)
    return candidate_filtered(session, candidate_id)


@router.get("/{candidate_id}/jobs/{job_id}")
def job_detail(candidate_id: int, job_id: int, session: Session = Depends(get_session)) -> dict:
    """A job seen outside the deck (map, saved list): same explanation; actions use slot "direct"."""
    _candidate(session, candidate_id)
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "vaga não encontrada")
    result = rank_for_candidate(session, candidate_id)
    item = next((it for it in result.items if it.item_id == job_id), None)
    detail = {"job": job_summary(session, job), "description_text": displayable_description(job)}
    if item is not None:
        card = job_card(session, item, result, [])
        card["rank_meta"]["slot"] = "direct"
        detail["card"] = card
    else:
        f = next((f for f in result.filtered if f.item_id == job_id), None)
        detail["filtered_reasons"] = [
            {"code": r.code, "title": texts.FILTER_TITLES.get(r.code, r.code)} for r in (f.reasons if f else [])
        ]
    return detail


@router.get("/{candidate_id}/applications")
def applications(candidate_id: int, session: Session = Depends(get_session)) -> list:
    _candidate(session, candidate_id)
    result = None
    out = []
    job_ids = list(
        dict.fromkeys(e.item_id for e in candidate_judgments(session, candidate_id) if e.type == "swipe_right")
    )
    for jid in job_ids:
        st = application_status(session, candidate_id, jid)
        if st is None:
            continue
        job = session.get(Job, jid)
        entry = {
            "job": job_summary(session, job),
            "status": st.status,
            "status_label": texts.STATUS_LABELS[st.status],
            "applied_at": st.applied_at.isoformat(),
            "seen_at": st.seen_at.isoformat() if st.seen_at else None,
            "decided_at": st.decided_at.isoformat() if st.decided_at else None,
            "timeline": st.timeline,
        }
        if st.status == "not_advanced":
            if result is None:
                result = rank_for_candidate(session, candidate_id, ranker="static-v1")
            c = result.meta["candidate"]
            entry["feedback"] = rejection_feedback(session, st, c, job_features_for(session, jid))
        if st.status == "matched":
            m = match_for(session, candidate_id, jid)
            entry["match"] = {"id": m.id, "ts": m.ts.isoformat()} if m else None
        out.append(entry)
    return out


@router.get("/{candidate_id}/saved")
def saved(candidate_id: int, session: Session = Depends(get_session)) -> list:
    _candidate(session, candidate_id)
    latest: dict[int, str] = {}
    for e in candidate_judgments(session, candidate_id):
        latest[e.item_id] = e.type
    out = []
    for jid, typ in latest.items():
        job = session.get(Job, jid)
        if typ == "swipe_right" and job is not None and job.origin == "market":
            out.append(
                {
                    "job": job_summary(session, job),
                    "apply_url": job.url,
                    "apply_text": "candidatar-se no site da empresa",
                }
            )
    return out


@router.get("/{candidate_id}/xray")
def xray(candidate_id: int, session: Session = Depends(get_session)) -> dict:
    from app.explore.candidate import xray_data

    _candidate(session, candidate_id)
    return xray_data(session, candidate_id)


@router.get("/{candidate_id}/export")
def export(candidate_id: int, session: Session = Depends(get_session)) -> dict:
    data = export_candidate(session, candidate_id)
    if data is None:
        raise HTTPException(404, "candidato não encontrado")
    return data


@router.delete("/{candidate_id}")
def purge(candidate_id: int, session: Session = Depends(get_session)) -> dict:
    counts = purge_candidate(session, candidate_id)
    if not counts:
        raise HTTPException(404, "candidato não encontrado")
    session.commit()
    return {"deleted": counts}


def candidate_profile_or_404(session: Session, candidate_id: int) -> CandidateProfile:
    profile = current_profile(session, _candidate(session, candidate_id))
    if profile is None:
        raise HTTPException(404, "perfil não encontrado")
    return profile


@router.get("/{candidate_id}/explore")
def explore(candidate_id: int, session: Session = Depends(get_session)) -> dict:
    from app.explore.candidate import explore_data

    _candidate(session, candidate_id)
    return explore_data(session, candidate_id)
