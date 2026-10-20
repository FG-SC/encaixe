"""Candidate profiles and their revisions (spec 4).

A save writes the current tables (Candidate, Experience, Education) and appends a ``ProfileRevision`` with
the canonical snapshot, its hash, its kind and its vectors. Identical content → no new revision.
A revision is **relevant** when an experience or education entry was added, the seniority changed, or the
symmetric difference of skill sets is ≥ RULES.revisions.relevant_skill_symdiff; otherwise **minor**.
The LLM never writes here: only the person (or the synthetic generator) saves a profile.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlmodel import Session, col, select

from app import clock
from app.companies import get_or_create_company
from app.config import RULES
from app.db import to_blob
from app.embeddings import embed_texts, get_embedder
from app.embeddings.texts import candidate_embed_text, candidate_title_texts
from app.models import Candidate, Education, Experience, ProfileRevision, Setting
from app.profiles.levels import candidate_level
from app.schemas import CandidateProfile

CANDIDATES_VERSION_KEY = "candidates_version"


@dataclass
class SaveResult:
    candidate: Candidate
    revision: ProfileRevision | None  # None when nothing changed
    kind: str | None
    changed: bool


def canonical_snapshot(profile: CandidateProfile) -> dict:
    data = profile.model_dump(mode="json")
    data["skills_listed"] = sorted(set(data["skills_listed"]))
    for exp in data["experiences"]:
        exp["skills_used"] = sorted(set(exp["skills_used"]))
    return data


def snapshot_hash(snapshot: dict) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def skill_set(profile: CandidateProfile) -> set[str]:
    return set(profile.skills_listed) | {s for e in profile.experiences for s in e.skills_used}


def _entry_keys(profile: CandidateProfile) -> tuple[set[tuple], set[tuple]]:
    exps = {(e.role.strip().lower(), e.start, (e.company or "").strip().lower()) for e in profile.experiences}
    edus = {
        ((d.degree or "").lower(), (d.field or "").lower(), (d.institution or "").lower()) for d in profile.education
    }
    return exps, edus


def classify_revision(old: CandidateProfile | None, new: CandidateProfile) -> str:
    """relevant | minor (spec 4)."""
    if old is None:
        return "relevant"
    old_exp, old_edu = _entry_keys(old)
    new_exp, new_edu = _entry_keys(new)
    if new_exp - old_exp or new_edu - old_edu:
        return "relevant"
    if candidate_level(old) != candidate_level(new):
        return "relevant"
    if len(skill_set(old) ^ skill_set(new)) >= RULES.revisions.relevant_skill_symdiff:
        return "relevant"
    return "minor"


def bump_candidates_version(session: Session) -> None:
    row = session.get(Setting, CANDIDATES_VERSION_KEY)
    if row is None:
        session.add(Setting(key=CANDIDATES_VERSION_KEY, value=1))
    else:
        row.value = int(row.value or 0) + 1
        session.add(row)


def profile_vectors(profile: CandidateProfile) -> tuple[bytes, bytes]:
    """(embedding, title embedding = mean of the experience-title vectors)."""
    import numpy as np

    emb = embed_texts([candidate_embed_text(profile)])[0]
    titles = embed_texts(candidate_title_texts(profile))
    mean = titles.mean(axis=0)
    norm = float(np.linalg.norm(mean)) or 1.0
    return to_blob(emb), to_blob(mean / norm)


def current_revision(session: Session, candidate: Candidate) -> ProfileRevision | None:
    if candidate.current_revision_id is None:
        return None
    return session.get(ProfileRevision, candidate.current_revision_id)


def current_profile(session: Session, candidate: Candidate) -> CandidateProfile | None:
    rev = current_revision(session, candidate)
    return CandidateProfile.model_validate(rev.snapshot) if rev else None


def _write_tables(session: Session, candidate: Candidate, profile: CandidateProfile) -> None:
    for row in session.exec(select(Experience).where(Experience.candidate_id == candidate.id)).all():
        session.delete(row)
    for row in session.exec(select(Education).where(Education.candidate_id == candidate.id)).all():
        session.delete(row)
    session.flush()
    for e in profile.experiences:
        company = get_or_create_company(session, e.company) if e.company else None
        session.add(
            Experience(
                candidate_id=candidate.id,  # type: ignore[arg-type]
                company_id=company.id if company else None,
                role=e.role,
                seniority=e.seniority,
                start=e.start,
                end=e.end,
                skills_used=list(e.skills_used),
                responsibilities=e.responsibilities,
                outcomes=list(e.outcomes),
            )
        )
    for d in profile.education:
        session.add(
            Education(
                candidate_id=candidate.id,
                degree=d.degree,
                field=d.field,  # type: ignore[arg-type]
                institution=d.institution,
                start=d.start,
                end=d.end,
            )
        )
    candidate.name = profile.name
    candidate.contact = profile.contact
    candidate.headline = profile.headline
    candidate.city_id = profile.city_id
    candidate.wants = profile.wants.model_dump(mode="json")
    candidate.skills_listed = list(profile.skills_listed)
    candidate.languages = [lang.model_dump(mode="json") for lang in profile.languages]


def save_profile(session: Session, candidate: Candidate, profile: CandidateProfile, ts=None) -> SaveResult:  # type: ignore[no-untyped-def]
    """Write the profile and append a revision when the content changed."""
    if type(profile) is not CandidateProfile:  # a CandidateDraft: drop provenance, warnings…
        profile = CandidateProfile.model_validate(profile.model_dump(include=set(CandidateProfile.model_fields)))
    snapshot = canonical_snapshot(profile)
    h = snapshot_hash(snapshot)
    old_rev = current_revision(session, candidate)
    if old_rev is not None and old_rev.hash == h:
        return SaveResult(candidate, None, None, False)
    old = CandidateProfile.model_validate(old_rev.snapshot) if old_rev else None
    kind = classify_revision(old, profile)
    _write_tables(session, candidate, profile)
    emb, title_emb = profile_vectors(profile)
    rev = ProfileRevision(
        candidate_id=candidate.id,
        ts=ts or clock.now(),
        hash=h,
        kind=kind,  # type: ignore[arg-type]
        snapshot=snapshot,
        seniority=candidate_level(profile),
        embedding=emb,
        title_embedding=title_emb,
    )
    session.add(rev)
    session.flush()
    candidate.current_revision_id = rev.id
    session.add(candidate)
    bump_candidates_version(session)
    session.flush()
    return SaveResult(candidate, rev, kind, True)


def create_candidate(
    session: Session,
    profile: CandidateProfile,
    *,
    synthetic: bool = False,
    visible: bool | None = None,
    llm_consent: bool = False,
    ts=None,  # type: ignore[no-untyped-def]
) -> SaveResult:
    if visible is None:
        visible = RULES.privacy.synthetic_default_visible if synthetic else RULES.privacy.candidate_default_visible
    cand = Candidate(
        name=profile.name,
        synthetic=synthetic,
        visible_to_recruiters=visible,
        llm_consent=llm_consent,
        created_at=ts or clock.now(),
    )
    session.add(cand)
    session.flush()
    return save_profile(session, cand, profile, ts=ts)


def revisions(session: Session, candidate_id: int) -> list[ProfileRevision]:
    return list(
        session.exec(
            select(ProfileRevision)
            .where(ProfileRevision.candidate_id == candidate_id)
            .order_by(col(ProfileRevision.ts))
        ).all()
    )


def ensure_candidate_vectors(session: Session) -> int:
    """Recompute revision vectors from another embedding space (e.g. after a backend switch)."""
    embedder = get_embedder()
    dim = embedder.dim
    n = 0
    for rev in session.exec(select(ProfileRevision)).all():
        if rev.embedding is None or len(rev.embedding) != dim * 4:
            emb, title_emb = profile_vectors(CandidateProfile.model_validate(rev.snapshot))
            rev.embedding, rev.title_embedding = emb, title_emb
            session.add(rev)
            n += 1
    if n:
        bump_candidates_version(session)
    return n
