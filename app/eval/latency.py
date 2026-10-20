"""Ranking latency (spec 7): p95 < 500 ms for 2,000 jobs (one candidate) and 300 candidates (one job)."""

from __future__ import annotations

import dataclasses
import time

import numpy as np
from sqlmodel import Session, select

from app.models import Candidate
from app.ranking.engine import rank
from app.ranking.index import candidate_index, job_index
from app.ranking.service import candidate_features_for, evaluate_pair, pairs_for_candidate


def run_latency(session: Session, n_jobs: int = 2000, n_candidates: int = 300, runs: int = 20) -> dict:
    base = job_index(session).jobs
    cand = session.exec(select(Candidate).where(Candidate.current_revision_id.is_not(None))).first()  # type: ignore[union-attr]
    if not base or cand is None:
        return {"error": "precisa de vagas e de um candidato"}
    rng = np.random.default_rng(0)
    jobs = []
    for i in range(n_jobs):
        j = base[i % len(base)]
        vec = j.emb + rng.normal(0, 0.05, j.emb.shape).astype(np.float32)
        vec /= np.linalg.norm(vec)
        jobs.append(dataclasses.replace(j, job_id=10_000_000 + i, emb=vec, title_emb=vec))
    matrix = np.vstack([j.emb for j in jobs])
    c = candidate_features_for(session, cand.id)  # type: ignore[arg-type]
    t_c = []
    for _ in range(runs):
        t = time.perf_counter()
        rank(pairs_for_candidate(c, jobs, matrix, matrix), side="candidate")
        t_c.append(time.perf_counter() - t)
    pool = candidate_index(session).candidates
    cands = [dataclasses.replace(pool[i % len(pool)], candidate_id=20_000_000 + i) for i in range(n_candidates)]
    j = base[0]
    t_b = []
    for _ in range(runs):
        t = time.perf_counter()
        pairs = [
            evaluate_pair(x, j, float(x.emb @ j.emb), float(x.title_emb @ j.title_emb), "recruiter", x.candidate_id)
            for x in cands
        ]  # type: ignore[arg-type]
        rank(pairs, side="recruiter")
        t_b.append(time.perf_counter() - t)
    return {
        "jobs_for_candidate": {
            "n": n_jobs,
            "p50_ms": 1000 * float(np.percentile(t_c, 50)),
            "p95_ms": 1000 * float(np.percentile(t_c, 95)),
        },
        "candidates_for_job": {
            "n": n_candidates,
            "p50_ms": 1000 * float(np.percentile(t_b, 50)),
            "p95_ms": 1000 * float(np.percentile(t_b, 95)),
        },
        "target_p95_ms": 500,
    }
