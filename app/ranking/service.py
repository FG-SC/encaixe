"""Ranking entry points backed by the database (both sides share the engine)."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from sqlmodel import Session

from app.config import RULES
from app.db import from_blob
from app.jobs import latest_version
from app.models import Candidate, Job, ProfileRevision
from app.ranking.engine import PairEval, RankResult, rank
from app.ranking.features import CandidateFeatures, JobFeatures, job_features
from app.ranking.index import candidate_index, features_for_revision, job_index
from app.ranking.pair import evaluate_requirements, good_fit, hard_filters, raw_criteria

HistoryFn = Callable[[list[PairEval]], None]


def evaluate_pair(
    c: CandidateFeatures, j: JobFeatures, sem: float, title: float, side: str, item_id: int, applicant: bool = False
) -> PairEval:
    req = evaluate_requirements(c, j)
    filters = hard_filters(c, j, req, side)
    raw = raw_criteria(c, j, req, sem, title)
    return PairEval(
        item_id=item_id, req=req, raw=raw, filters=filters, good=good_fit(c, j, req, not filters), applicant=applicant
    )


def candidate_features_for(session: Session, candidate_id: int) -> CandidateFeatures:
    cand = session.get(Candidate, candidate_id)
    if cand is None or cand.current_revision_id is None:
        raise LookupError(f"candidate {candidate_id} has no profile")
    rev = session.get(ProfileRevision, cand.current_revision_id)
    assert rev is not None
    return features_for_revision(session, cand, rev)


def pairs_for_candidate(
    c: CandidateFeatures, jobs: list[JobFeatures], emb: np.ndarray, title_emb: np.ndarray
) -> list[PairEval]:
    sem = emb @ c.emb if len(jobs) else np.zeros(0)
    tit = title_emb @ c.title_emb if len(jobs) else np.zeros(0)
    out = []
    for i, j in enumerate(jobs):
        p = evaluate_pair(c, j, float(sem[i]), float(tit[i]), "candidate", j.job_id)
        p.extra.update(job=j)
        out.append(p)
    return out


def rank_for_candidate(
    session: Session,
    candidate_id: int,
    *,
    ranker: str | None = None,
    aggregator: str | None = None,
    history_fn: HistoryFn | None = None,
    features: CandidateFeatures | None = None,
) -> RankResult:
    c = features or candidate_features_for(session, candidate_id)
    idx = job_index(session)
    pairs = pairs_for_candidate(c, idx.jobs, idx.emb, idx.title_emb)
    if history_fn is not None and (ranker or RULES.rankers.default) == "feedback-v1":
        history_fn(pairs)
    result = rank(pairs, side="candidate", ranker=ranker, aggregator=aggregator)
    result.meta["candidate"] = c
    return result


def job_features_for(session: Session, job_id: int) -> JobFeatures:
    job = session.get(Job, job_id)
    if job is None:
        raise LookupError(f"job {job_id} not found")
    idx = job_index(session)
    if job_id in idx.by_id:
        return idx.jobs[idx.by_id[job_id]]
    v = latest_version(session, job_id)
    if v is None or v.embedding is None:
        from app.jobs import ensure_job_vectors

        ensure_job_vectors(session)
        v = latest_version(session, job_id)
    assert v is not None and v.embedding is not None and v.title_embedding is not None
    return job_features(job, from_blob(v.embedding), from_blob(v.title_embedding))  # type: ignore[arg-type]


def rank_for_job(
    session: Session,
    job_id: int,
    *,
    ranker: str | None = None,
    aggregator: str | None = None,
    applicants: set[int] | None = None,
    history_fn: HistoryFn | None = None,
) -> RankResult:
    j = job_features_for(session, job_id)
    cidx = candidate_index(session)
    applicants = applicants or set()
    sem = cidx.emb @ j.emb if cidx.candidates else np.zeros(0)
    tit = cidx.title_emb @ j.title_emb if cidx.candidates else np.zeros(0)
    pairs = []
    for i, c in enumerate(cidx.candidates):
        p = evaluate_pair(
            c,
            j,
            float(sem[i]),
            float(tit[i]),
            "recruiter",
            c.candidate_id,  # type: ignore[arg-type]
            applicant=c.candidate_id in applicants,
        )
        p.extra.update(candidate=c)
        pairs.append(p)
    if history_fn is not None and (ranker or RULES.rankers.default) == "feedback-v1":
        history_fn(pairs)
    result = rank(pairs, side="recruiter", ranker=ranker, aggregator=aggregator)
    result.meta["job"] = j
    return result
