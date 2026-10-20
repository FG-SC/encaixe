"""In-memory indexes of open jobs and of candidates (numpy matrices + features), rebuilt on change.

The busca vetorial is a numpy matrix (spec 2): with a few thousand jobs a vector database is dead weight.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np
from sqlmodel import Session, select

from app import clock
from app.db import from_blob
from app.jobs import JOBS_VERSION_KEY, ensure_job_vectors, latest_version
from app.models import Candidate, Job, ProfileRevision, Setting
from app.profiles import CANDIDATES_VERSION_KEY, ensure_candidate_vectors
from app.ranking.features import CandidateFeatures, JobFeatures, candidate_features, job_features
from app.schemas import CandidateProfile


@dataclass
class JobIndex:
    version: object
    jobs: list[JobFeatures]
    by_id: dict[int, int]
    emb: np.ndarray  # (n, d)
    title_emb: np.ndarray


@dataclass
class CandidateIndex:
    version: object
    candidates: list[CandidateFeatures]
    by_id: dict[int, int]
    emb: np.ndarray
    title_emb: np.ndarray


_lock = threading.Lock()
_job_index: JobIndex | None = None
_cand_index: CandidateIndex | None = None


def _setting(session: Session, key: str) -> object:
    row = session.get(Setting, key)
    return row.value if row else None


def job_index(session: Session) -> JobIndex:
    """Open jobs with vectors (computes missing vectors first)."""
    global _job_index
    if ensure_job_vectors(session, only_open=True):
        session.flush()
    version = _setting(session, JOBS_VERSION_KEY)
    with _lock:
        if _job_index is not None and _job_index.version == version:
            return _job_index
    feats: list[JobFeatures] = []
    for job in session.exec(select(Job).where(Job.status == "open")).all():
        v = latest_version(session, job.id)  # type: ignore[arg-type]
        if v is None or v.embedding is None or v.title_embedding is None:
            continue
        feats.append(job_features(job, from_blob(v.embedding), from_blob(v.title_embedding)))  # type: ignore[arg-type]
    dim = feats[0].emb.shape[0] if feats else 1
    idx = JobIndex(
        version=version,
        jobs=feats,
        by_id={f.job_id: i for i, f in enumerate(feats)},
        emb=np.vstack([f.emb for f in feats]) if feats else np.zeros((0, dim), dtype=np.float32),
        title_emb=np.vstack([f.title_emb for f in feats]) if feats else np.zeros((0, dim), dtype=np.float32),
    )
    with _lock:
        _job_index = idx
    return idx


def features_for_revision(session: Session, candidate: Candidate, rev: ProfileRevision) -> CandidateFeatures:
    profile = CandidateProfile.model_validate(rev.snapshot)
    return candidate_features(
        profile,
        from_blob(rev.embedding),
        from_blob(rev.title_embedding),
        clock.today(),  # type: ignore[arg-type]
        candidate_id=candidate.id,
        revision_id=rev.id,
        visible=candidate.visible_to_recruiters,
        synthetic=candidate.synthetic,
    )


def candidate_index(session: Session) -> CandidateIndex:
    """Every candidate with a current revision (visibility is a filter, applied by the ranking)."""
    global _cand_index
    if ensure_candidate_vectors(session):
        session.flush()
    version = (_setting(session, CANDIDATES_VERSION_KEY), clock.today().isoformat())
    with _lock:
        if _cand_index is not None and _cand_index.version == version:
            return _cand_index
    feats: list[CandidateFeatures] = []
    for cand in session.exec(select(Candidate).where(Candidate.current_revision_id.is_not(None))).all():  # type: ignore[union-attr]
        rev = session.get(ProfileRevision, cand.current_revision_id)
        if rev is None or rev.embedding is None:
            continue
        feats.append(features_for_revision(session, cand, rev))
    dim = feats[0].emb.shape[0] if feats else 1
    idx = CandidateIndex(
        version=version,
        candidates=feats,
        by_id={f.candidate_id: i for i, f in enumerate(feats)},  # type: ignore[misc]
        emb=np.vstack([f.emb for f in feats]) if feats else np.zeros((0, dim), dtype=np.float32),
        title_emb=np.vstack([f.title_emb for f in feats]) if feats else np.zeros((0, dim), dtype=np.float32),
    )
    with _lock:
        _cand_index = idx
    return idx


def reset_caches() -> None:
    global _job_index, _cand_index
    with _lock:
        _job_index = None
        _cand_index = None
