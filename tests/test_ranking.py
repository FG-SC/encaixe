"""Static ranking (spec 7, 9.2–9.5): positions, filters, good fit, explanations, counterfactuals, latency."""

from __future__ import annotations

import dataclasses
import time
from datetime import date

import numpy as np
import pytest
from sqlmodel import Session, select

from app import texts
from app.config import RULES
from app.embeddings import FakeEmbedder
from app.extraction.cv import extract_cv
from app.extraction.job import RawPosting, extract_job
from app.jobs import upsert_job
from app.models import Job
from app.profiles import create_candidate
from app.ranking.counterfactual import skills_to_full_proof, smallest_change, unlock_counts
from app.ranking.engine import rank
from app.ranking.explain import explain_item, filtered_groups
from app.ranking.features import candidate_features
from app.ranking.index import job_index
from app.ranking.positions import positions
from app.ranking.service import evaluate_pair, job_features_for, pairs_for_candidate, rank_for_candidate, rank_for_job
from app.schemas import CandidateProfile, ExperienceIn, Wants
from app.seed.loader import load_recruiters, load_seed_jobs, persona_text

ANA_WANTS = Wants(comp_min=5000, arrangements=["remote", "hybrid", "onsite"], max_distance_km=60)


def ana_profile() -> CandidateProfile:
    d = extract_cv(persona_text("ana"))
    p = CandidateProfile.model_validate(d.model_dump(include=set(CandidateProfile.model_fields)))
    return p.model_copy(update={"wants": ANA_WANTS})


@pytest.fixture
def world(session: Session) -> dict:
    load_seed_jobs(session)
    load_recruiters(session)
    ana = create_candidate(session, ana_profile()).candidate
    session.commit()
    return {"ana": ana.id}


# --------------------------------------------------------------------------- positions


def test_positions_ties_unknowns_and_tuples() -> None:
    assert list(positions([0.9, 0.5, 0.89, 0.1], "max", 0.02)) == [1.5, 3.0, 1.5, 4.0]
    assert list(positions([10.0, 3.0, 4.0], "min", 5.0)) == [3.0, 1.5, 1.5]
    # unknown = median of the known values → in the middle
    assert list(positions([1.0, None, 0.0], "max")) == [1.0, 2.0, 3.0]
    assert list(positions([None, None], "max")) == [1.5, 1.5]
    # lexicographic: proving beats listing whatever the listed share
    assert list(positions([(1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 1.0, 1.0)], "max")) == [1.0, 2.0]


def test_undisclosed_salary_counts_as_the_minimum(session: Session, world: dict) -> None:
    """Ana's minimum is R$ 5.000: above ranks better, below (but above the 70% cut) worse, undisclosed = minimum."""
    ids = {}
    for key, pay in (("above", "R$ 8.000"), ("minimum", "R$ 5.000"), ("undisclosed", None), ("below", "R$ 4.000")):
        text = "Requisitos\n- SQL\n- Python\n- Power BI" + (f"\nSalário: {pay} por mês" if pay else "")
        draft = extract_job(RawPosting(title="Analista de Dados", description=text, location_text="Florianópolis, SC"))
        ids[key] = upsert_job(session, draft, source="t", source_id=key).job.id
    session.commit()
    by_id = {it.item_id: it for it in rank_for_candidate(session, world["ana"], ranker="static-v1").items}
    pos = {k: by_id[i].criteria["salary"]["position"] for k, i in ids.items()}
    assert pos["above"] < pos["minimum"] == pos["undisclosed"] < pos["below"]
    undisclosed = by_id[ids["undisclosed"]].criteria["salary"]
    assert undisclosed["raw"] == RULES.criteria.salary_unknown_slack == 0.0
    from app.ranking.explain import raw_text

    text = raw_text("salary", undisclosed, by_id[ids["undisclosed"]].req, "candidate")
    assert text == "não informado (conta como o seu mínimo)"


# --------------------------------------------------------------------------- filters, anchors and traps


def test_eligible_plus_filtered_is_every_open_job(session: Session, world: dict) -> None:
    result = rank_for_candidate(session, world["ana"])
    open_jobs = session.exec(select(Job).where(Job.status == "open")).all()
    assert len(result.items) + len(result.filtered) == len(open_jobs)
    assert {i.item_id for i in result.items}.isdisjoint({f.item_id for f in result.filtered})


def test_trap_5_sales_manager_is_out_of_area_for_ana(session: Session, world: dict) -> None:
    result = rank_for_candidate(session, world["ana"])
    sales = session.exec(select(Job).where(Job.title == "Sales Manager")).one()
    entry = next(f for f in result.filtered if f.item_id == sales.id)
    assert [r.code for r in entry.reasons] == ["out_of_area"]
    groups = filtered_groups(result.filtered, lambda jid: {"job_id": jid})
    assert any(g["code"] == "out_of_area" for g in groups["groups"])
    assert groups["total"] == len(result.filtered) and groups["summary"].startswith("Não te mostramos")


def test_hard_filter_reasons(session: Session, world: dict) -> None:
    result = rank_for_candidate(session, world["ana"])
    codes = {r.code for f in result.filtered for r in f.reasons}
    assert {"beyond_distance", "country_eligibility", "out_of_area"} <= codes
    us_only = session.exec(select(Job).where(Job.title == "Senior Machine Learning Engineer")).one()
    entry = next(f for f in result.filtered if f.item_id == us_only.id)
    assert "country_eligibility" in [r.code for r in entry.reasons]


def test_jobs_abroad_that_do_not_say_remote_are_beyond_distance(session: Session, world: dict) -> None:
    """Real postings: no arrangement stated + a city abroad, or a country abroad without a known city."""
    reqs = "Requisitos\n- SQL\n- Python\n- Power BI"
    ids = {}
    for key, location, extra in (
        ("unknown_city_abroad", "Saskatoon, Saskatchewan, Canada", ""),  # not in cities.csv
        ("known_city_abroad", "New York, New York, United States", ""),
        ("remote_abroad", "Toronto, Ontario, Canada", "\nVaga 100% remota."),
    ):
        draft = extract_job(RawPosting(title="Analista de Dados", description=reqs + extra, location_text=location))
        ids[key] = upsert_job(session, draft, source="t", source_id=key).job.id
    session.commit()
    result = rank_for_candidate(session, world["ana"])
    reasons = {f.item_id: {r.code: r for r in f.reasons} for f in result.filtered}
    abroad = reasons[ids["unknown_city_abroad"]]["beyond_distance"]
    assert abroad.detail["other_country"] == "CA" and abroad.detail["arrangement"] is None
    assert "outro país (CA)" in texts.filter_detail("beyond_distance", **abroad.detail)
    far = reasons[ids["known_city_abroad"]]["beyond_distance"].detail
    assert far["distance_km"] > 5000 and "conta como presencial" in texts.filter_detail("beyond_distance", **far)
    assert "beyond_distance" not in reasons.get(ids["remote_abroad"], {})


def test_trap_9_keyword_stuffing_does_not_beat_proof(session: Session) -> None:
    """50 listed skills cannot beat 5 skills used recently, for a job asking for those 5."""
    must = ["python", "sql", "airflow", "spark", "docker"]
    job = upsert_job(
        session,
        extract_job(
            RawPosting(
                title="Engenheiro de Dados",
                description="Requisitos\n" + "\n".join(f"- {s}" for s in must),
                location_text="Florianópolis, SC",
            )
        ),
        source="t",
        source_id="1",
    ).job
    from app.taxonomy import load as load_tax

    many = sorted(load_tax().skills)[:50]
    wants = Wants(arrangements=["remote", "hybrid", "onsite"])
    stuffer = CandidateProfile(
        headline="Engenheiro de Dados",
        city_id="florianopolis-sc-br",
        wants=wants,
        skills_listed=list(dict.fromkeys(many + must + must)),
    )
    prover = CandidateProfile(
        headline="Engenheiro de Dados",
        city_id="florianopolis-sc-br",
        wants=wants,
        experiences=[ExperienceIn(role="Engenheiro de Dados", start=date(2024, 1, 1), end=None, skills_used=must)],
    )
    a = create_candidate(session, stuffer, synthetic=True).candidate
    b = create_candidate(session, prover, synthetic=True).candidate
    for _ in range(3):  # more candidates so positions are not trivial
        create_candidate(
            session,
            CandidateProfile(headline="Analista", city_id="florianopolis-sc-br", wants=wants, skills_listed=["excel"]),
            synthetic=True,
        )
    session.commit()
    result = rank_for_job(session, job.id, ranker="static-v1")
    order = [it.item_id for it in result.items]
    assert order.index(b.id) < order.index(a.id)
    by = {it.item_id: it for it in result.items}
    assert by[b.id].criteria["requirements"]["position"] < by[a.id].criteria["requirements"]["position"]


def test_good_fit_rule(session: Session, world: dict) -> None:
    result = rank_for_candidate(session, world["ana"])
    for it in result.items:
        g = it.good_fit
        expected = (
            g.evaluable
            and g.must_credit / g.must_total >= RULES.good_fit.must_share - 1e-9
            and (g.seniority_gap is None or g.seniority_gap <= RULES.good_fit.max_seniority_gap)
        )
        assert g.is_good_fit == expected
    assert any(it.good_fit.is_good_fit for it in result.items)


# --------------------------------------------------------------------------- explanations


def _reconstruct(items: list[dict], side: str) -> list[int]:
    """Sort using ONLY the numbers shown in "Por que estou vendo isto?" plus the published tie-break."""

    def key(e: dict) -> tuple:
        pillars = {p["pillar"]: p["position"] for p in e["explanation"]["pillars"]}
        req_pos = next(line["position"] for line in e["explanation"]["lines"] if line["criterion"] == "requirements")
        group = 0 if (side == "recruiter" and e["applicant"]) else 1
        return (group, round(e["explanation"]["final_sum"], 9), pillars["atende"], req_pos, e["item_id"])

    return [e["item_id"] for e in sorted(items, key=key)]


def test_shown_positions_reconstruct_the_order(session: Session, world: dict) -> None:
    result = rank_for_candidate(session, world["ana"], ranker="static-v1")
    n = len(result.items)
    shown = [
        {"item_id": it.item_id, "applicant": it.applicant, "explanation": explain_item(it, n, "candidate")}
        for it in result.items
    ]
    assert _reconstruct(shown, "candidate") == [it.item_id for it in result.items]
    # each pillar position is the rank of the shown pillar sum (ties averaged)
    for p in ("atende", "interessa"):
        sums = [next(x["sum"] for x in e["explanation"]["pillars"] if x["pillar"] == p) for e in shown]
        shown_pos = [next(x["position"] for x in e["explanation"]["pillars"] if x["pillar"] == p) for e in shown]
        assert list(positions(sums, "min")) == shown_pos
    # each pillar sum is the sum of the shown criterion positions
    for e in shown:
        for p in e["explanation"]["pillars"]:
            crit_sum = sum(line["position"] for line in e["explanation"]["lines"] if line["pillar"] == p["pillar"])
            assert abs(crit_sum - p["sum"]) < 1e-9


def test_explanation_texts(session: Session, world: dict) -> None:
    result = rank_for_candidate(session, world["ana"])
    it = result.items[0]
    e = explain_item(it, len(result.items), "candidate")
    req_line = next(line for line in e["lines"] if line["criterion"] == "requirements")
    assert "obrigatórios comprovados" in req_line["raw_text"] and "de" in req_line["position_text"]
    assert e["note"].startswith("A posição compara") and e["summary"].startswith("Você aparece")


# --------------------------------------------------------------------------- counterfactual (Ana × Carla)


def test_counterfactual_ana_and_carla(session: Session, world: dict) -> None:
    text = persona_text("lumen_ml_engineer_jr")
    title, _, body = text.partition("\n")
    job = upsert_job(
        session,
        extract_job(
            RawPosting(
                title=title, description=body, company="Lumen Dados", location_text="Florianópolis, SC (híbrido)"
            )
        ),
        source="platform",
        source_id="carla-1",
        origin="platform",
    ).job
    session.commit()
    c = rank_for_candidate(session, world["ana"]).meta["candidate"]
    j = job_features_for(session, job.id)
    cf = smallest_change(c, j)
    assert cf.kind == "skills" and cf.skills == ["pytorch"]  # PyTorch also gives half credit to deep learning
    gaps, credit_after, total = skills_to_full_proof(c, j)
    assert gaps == ["pytorch", "deep_learning"] and (credit_after, total) == (5.0, 5)


def test_unlock_counts(session: Session, world: dict) -> None:
    c = rank_for_candidate(session, world["ana"]).meta["candidate"]
    counts = unlock_counts(c, job_index(session).jobs)
    assert counts and all(skill not in c.proven for skill in counts)


# --------------------------------------------------------------------------- aggregators and latency


@pytest.mark.parametrize("aggregator", ["rank_sum", "rrf", "weighted"])
def test_aggregators_rank_every_eligible_job(session: Session, world: dict, aggregator: str) -> None:
    result = rank_for_candidate(session, world["ana"], aggregator=aggregator)
    assert len(result.items) == result.meta["n_eligible"] and result.meta["aggregator"] == aggregator
    assert [it.order for it in result.items] == list(range(1, len(result.items) + 1))


def test_latency_under_500ms(session: Session, world: dict) -> None:
    """2,000 jobs for one candidate and 300 candidates for one job (spec 7: p95 < 500 ms).

    In the test suite the machine is busy, so this checks the median (after warm-up) with a loose p95 bound;
    the published p95 comes from `encaixe eval latency` in a fresh process (docs/EVAL.md).
    """
    base = job_index(session).jobs
    rng = np.random.default_rng(0)
    emb = FakeEmbedder()
    jobs = []
    for i in range(2000):
        j = base[i % len(base)]
        vec = emb.embed([f"{j.title} {i}"])[0]
        jobs.append(dataclasses.replace(j, job_id=100_000 + i, emb=vec, title_emb=vec))
    matrix = np.vstack([j.emb for j in jobs])
    c = rank_for_candidate(session, world["ana"]).meta["candidate"]
    times = []
    for _ in range(12):
        t = time.perf_counter()
        rank(pairs_for_candidate(c, jobs, matrix, matrix), side="candidate")
        times.append(time.perf_counter() - t)
    times = times[2:]  # warm-up
    assert float(np.median(times)) < 0.5 and float(np.percentile(times, 95)) < 1.0, times

    profile = ana_profile()
    cands = []
    for i in range(300):
        vec = rng.standard_normal(emb.dim).astype(np.float32)
        vec /= np.linalg.norm(vec)
        cands.append(candidate_features(profile, vec, vec, date(2026, 10, 1), candidate_id=i))
    j = jobs[0]
    times = []
    for _ in range(12):
        t = time.perf_counter()
        pairs = [evaluate_pair(cf, j, float(cf.emb @ j.emb), 0.5, "recruiter", i) for i, cf in enumerate(cands)]
        rank(pairs, side="recruiter")
        times.append(time.perf_counter() - t)
    times = times[2:]  # warm-up
    assert float(np.median(times)) < 0.5 and float(np.percentile(times, 95)) < 1.0, times
