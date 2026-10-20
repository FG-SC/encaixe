"""Explorar (spec 12) and its privacy rules (spec 10): k-anonymity, invisible candidates excluded."""

from __future__ import annotations

from sqlmodel import Session, select

from app import clock
from app.config import RULES
from app.explore.candidate import explore_data, xray_data
from app.explore.recruiter import explore, funnel
from app.models import Candidate, Job
from app.profiles import bump_candidates_version
from app.seed.loader import load_recruiters, load_seed_jobs
from app.synth.personas import make_personas
from app.synth.simulate import sim_start_for, simulate

BELOW_K = f"<{RULES.privacy.k_anon}"


def _world(session: Session) -> tuple[int, int]:
    load_seed_jobs(session)
    recs = load_recruiters(session)
    session.commit()
    days = 14
    start = sim_start_for(days, clock.today())
    simulate(session, make_personas(30, 11, clock.today(), start.date(), days), start, days, seed=11)
    session.commit()
    rec = next(r for r in recs if r.name == "Rafael Duarte")
    job = session.exec(select(Job).where(Job.owner_recruiter_id == rec.id)).first()
    return rec.id, job.id  # type: ignore[return-value,union-attr]


def _is_count(value: str) -> bool:
    return value == BELOW_K or (value.isdigit() and int(value) >= RULES.privacy.k_anon)


def test_funnel_counts_are_k_anonymous_and_ignore_invisible(session: Session) -> None:
    _, job_id = _world(session)
    f = funnel(session, job_id)
    assert all(_is_count(s["count"]) for s in f["stages"])
    assert all(_is_count(r["proving"]) and _is_count(r["good_fit_without_it"]) for r in f["requirements"])
    visible_before = f["stages"][0]["count"]
    for cand in session.exec(select(Candidate)).all():
        cand.visible_to_recruiters = False
        session.add(cand)
    bump_candidates_version(session)
    session.commit()
    f2 = funnel(session, job_id)
    assert visible_before != BELOW_K and f2["stages"][0]["count"] == BELOW_K


def test_recruiter_explore_hides_small_cells_and_reasons(session: Session) -> None:
    _, job_id = _world(session)
    e = explore(session, job_id)
    assert all(c["count"] >= RULES.privacy.k_anon for c in e["pool_map"]["cells"])
    assert all(c["count"] >= RULES.privacy.k_anon for c in e["cities"])
    total = e["candidate_reasons"]["total"]
    if total == BELOW_K:
        assert e["candidate_reasons"]["rows"] == []
    assert e["benchmark"]["jobs"] and "congestion" in e


def test_candidate_explore_and_xray(session: Session) -> None:
    _world(session)
    cid = session.exec(select(Candidate.id)).first()
    x = xray_data(session, cid)  # type: ignore[arg-type]
    assert x["share_card"]["personal_data"] is False and x["star"] is not None
    assert "name" not in x["share_card"] and "contact" not in x["share_card"]
    e = explore_data(session, cid)  # type: ignore[arg-type]
    assert len(e["unlock"]) <= 10 and e["timeline"] and {"cities", "remote", "salaries", "revealed"} <= set(e)
