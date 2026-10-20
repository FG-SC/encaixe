"""Synthetic people, simulated histories and the evaluation pipeline (small sizes, fake embeddings)."""

from __future__ import annotations

from datetime import date, timedelta

from sqlmodel import Session, select

from app import clock
from app.eval.congestion import run_congestion
from app.eval.drift import run_drift
from app.eval.latency import run_latency
from app.eval.metrics import auc, gini, mrr, ndcg_gains, recall_at
from app.eval.oracle import position_auc, run_oracle_check
from app.eval.replay import run_replay
from app.eval.report import save_result, write_report
from app.models import Candidate, InteractionEvent, ProfileRevision
from app.seed.loader import load_recruiters, load_seed_jobs
from app.synth.personas import make_personas
from app.synth.simulate import sim_start_for, simulate


def test_personas_are_deterministic_and_consistent() -> None:
    today = date(2026, 10, 20)
    a = make_personas(20, 42, today, today - timedelta(days=30), 30)
    b = make_personas(20, 42, today, today - timedelta(days=30), 30)
    assert [p.profile.model_dump() for p in a] == [p.profile.model_dump() for p in b]
    assert sum(p.revision_day is not None for p in a) == 2  # ~10%
    for p in a:
        exps = p.profile.experiences
        assert exps[0].end is None and all(e.start is not None for e in exps)
        assert all(e.end is None or e.start <= e.end for e in exps)  # type: ignore[operator]
        assert "sintético" in p.profile.name and p.profile.contact.endswith(".invalid")  # type: ignore[union-attr]
        if p.revised_profile is not None:
            assert len(p.revised_profile.experiences) == len(exps) + 1


def test_simulation_writes_a_consistent_history(session: Session, tmp_path) -> None:  # type: ignore[no-untyped-def]
    load_seed_jobs(session)
    load_recruiters(session)
    session.commit()
    days = 21
    start = sim_start_for(days, clock.today())
    personas = make_personas(12, 3, clock.today(), start.date(), days)
    counts = simulate(session, personas, start, days, seed=3)
    session.commit()
    assert counts["sessions"] > 0 and counts["impressions"] >= counts["likes"] + counts["dislikes"] > 0
    assert len(session.exec(select(Candidate).where(Candidate.synthetic == True)).all()) == 12  # noqa: E712
    revs = session.exec(select(ProfileRevision).where(ProfileRevision.kind == "relevant")).all()
    assert len(revs) == 12 + counts["revisions"]
    judgments = session.exec(select(InteractionEvent).where(InteractionEvent.type == "swipe_left")).all()
    assert all(e.reason in (None, "role_area", "salary", "seniority", "skills", "location") for e in judgments)
    assert all(e.ts <= clock.now() for e in judgments)

    replay = run_replay(session, max_sessions=60)
    assert replay["sessions"] > 0 and "feedback-v1" in replay["variants"]
    assert 0 <= replay["variants"]["static-v1 (rank_sum)"]["mrr"] <= 1
    drift = run_drift(session, users=6, days=8, drift_day=4)
    assert drift["drifters"] == 3 and len(drift["curves"]["static-v1"]["precision@10"]) == 8
    oracle = run_oracle_check(session, users=6, seed=5)
    assert set(oracle["aggregators"]) == {"rank_sum", "rrf", "weighted"}
    assert all(m["auc"] is None or 0 <= m["auc"] <= 1 for m in oracle["aggregators"].values())
    cong = run_congestion(session)
    assert cong["platform_jobs"] == 8 and cong["slots"] <= 8 * 5
    lat = run_latency(session, n_jobs=200, n_candidates=30, runs=3)
    assert lat["jobs_for_candidate"]["p95_ms"] < 500
    results = (("replay", replay), ("oracle", oracle), ("drift", drift), ("congestion", cong), ("latency", lat))
    for name, data in results:
        save_result(name, data)
    path = write_report(session, tmp_path / "EVAL.md")
    assert (tmp_path / "eval" / "drift_precision_all.svg").exists()
    text = path.read_text(encoding="utf-8")
    assert "## 1. Replay" in text and "## 2. Drift" in text and "## 3. Congestion" in text and "## 4. Latency" in text
    assert "### 1b. Unbiased check" in text


def test_position_auc() -> None:
    import numpy as np

    assert position_auc(np.array([True, True, False])) == 1.0
    assert position_auc(np.array([False, True])) == 0.0
    assert position_auc(np.array([True, False, True, False])) == 0.75
    assert position_auc(np.array([True, True])) is None


def test_metrics() -> None:
    assert mrr([1, 2, 4]) == (1 + 0.5 + 0.25) / 3
    assert recall_at([1, 5, 11], 10) == 2 / 3
    assert auc([1, 2], [3, 4]) == 1.0 and auc([3], [1]) == 0.0 and auc([], [1]) is None
    assert gini([1, 1, 1, 1]) == 0.0 and gini([0, 0, 0, 4]) > 0.7
    assert ndcg_gains([1.0, 0.0], [1.0, 0.0]) == 1.0
