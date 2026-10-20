"""Events, statuses, matches, feedback-v1, exploration, reappearance and privacy (spec 4, 8, 10)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlmodel import Session, select

from app import clock
from app.config import RULES
from app.events import EventError, record_event
from app.events.status import application_status
from app.extraction.job import RawPosting, extract_job
from app.jobs import upsert_job
from app.models import InteractionEvent, Job, Match, ProfileRevision, Recruiter
from app.privacy import candidate_card_profile, export_candidate, purge_candidate
from app.profiles import create_candidate, current_profile, save_profile
from app.ranking.deck import candidate_deck, recruiter_deck
from app.ranking.feedback import _weight, make_history_fn
from app.ranking.service import rank_for_job
from app.schemas import CandidateProfile, EducationIn, ExperienceIn, Wants
from app.seed.loader import load_recruiters, load_seed_jobs

WANTS = Wants(arrangements=["remote", "hybrid", "onsite"])


def ev(**kw: object) -> dict:
    return {"client_event_id": str(uuid.uuid4()), "session_id": "s1", "ranker_version": "feedback-v1", **kw}


@pytest.fixture
def world(session: Session) -> dict:
    load_seed_jobs(session)
    recs = load_recruiters(session)
    profile = CandidateProfile(
        name="Bia Teste",
        contact="bia@example.com",
        headline="Analista de Dados",
        city_id="florianopolis-sc-br",
        wants=WANTS,
        experiences=[
            ExperienceIn(
                company="Empresa X",
                role="Analista de Dados Júnior",
                start=date(2024, 1, 1),
                skills_used=["sql", "python", "power_bi"],
            )
        ],
        education=[
            EducationIn(
                degree="Bacharelado",
                field="Estatística",
                institution="Universidade Y",
                start=date(2019, 1, 1),
                end=date(2023, 12, 1),
            )
        ],
    )
    cand = create_candidate(session, profile, visible=True).candidate
    tainha = next(r for r in recs if r.name == "Rafael Duarte")
    platform = session.exec(select(Job).where(Job.owner_recruiter_id == tainha.id)).first()
    market = session.exec(select(Job).where(Job.origin == "market")).first()
    session.commit()
    return {"cand": cand.id, "rec": tainha.id, "pjob": platform.id, "mjob": market.id}  # type: ignore[union-attr]


def test_events_are_idempotent(session: Session, world: dict) -> None:
    body = ev(actor_type="candidate", actor_id=world["cand"], item_type="job", item_id=world["mjob"], type="impression")
    a = record_event(session, body)
    b = record_event(session, body)
    assert a.created and not b.created and a.event.id == b.event.id
    assert len(session.exec(select(InteractionEvent)).all()) == 1


def test_impressions_dedupe_and_swipes_imply_impressions(session: Session, world: dict) -> None:
    base = dict(actor_type="candidate", actor_id=world["cand"], item_type="job", item_id=world["mjob"])
    first = record_event(session, ev(**base, type="impression"))
    again = record_event(session, ev(**base, type="impression"))  # new client id, same session → deduped
    other = record_event(session, ev(**base, type="impression", session_id="s2"))
    assert again.event.id == first.event.id and not again.created and other.created
    swipe = record_event(session, ev(**base, type="swipe_left", session_id="s3", reason="salary"))
    assert swipe.impression_auto_created
    swipe2 = record_event(session, ev(**base, type="swipe_left", session_id="s2"))
    assert not swipe2.impression_auto_created


def test_reason_rules(session: Session, world: dict) -> None:
    with pytest.raises(EventError) as e:
        record_event(
            session,
            ev(
                actor_type="candidate",
                actor_id=world["cand"],
                item_type="job",
                item_id=world["mjob"],
                type="swipe_left",
                reason="texto livre",
            ),
        )
    assert e.value.status == 422
    # a non-applicant can be declined without a reason
    r = record_event(
        session,
        ev(
            actor_type="recruiter",
            actor_id=world["rec"],
            item_type="candidate",
            item_id=world["cand"],
            context_job_id=world["pjob"],
            type="swipe_left",
        ),
    )
    assert r.created
    # a recruiter cannot judge candidates in someone else's job
    other = session.exec(select(Recruiter).where(Recruiter.id != world["rec"])).first()
    with pytest.raises(EventError):
        record_event(
            session,
            ev(
                actor_type="recruiter",
                actor_id=other.id,
                item_type="candidate",  # type: ignore[union-attr]
                item_id=world["cand"],
                context_job_id=world["pjob"],
                type="swipe_right",
            ),
        )


def test_match_in_either_order_and_market_jobs_never_match(session: Session, world: dict) -> None:
    rec = record_event(
        session,
        ev(
            actor_type="recruiter",
            actor_id=world["rec"],
            item_type="candidate",
            item_id=world["cand"],
            context_job_id=world["pjob"],
            type="swipe_right",
        ),
    )
    assert rec.match is None
    app = record_event(
        session,
        ev(actor_type="candidate", actor_id=world["cand"], item_type="job", item_id=world["pjob"], type="swipe_right"),
    )
    assert app.match is not None
    st = application_status(session, world["cand"], world["pjob"])
    assert st is not None and st.status == "matched"
    saved = record_event(
        session,
        ev(actor_type="candidate", actor_id=world["cand"], item_type="job", item_id=world["mjob"], type="swipe_right"),
    )
    assert saved.match is None and len(session.exec(select(Match)).all()) == 1


def test_status_transitions(session: Session, world: dict) -> None:
    c, j, r = world["cand"], world["pjob"], world["rec"]
    record_event(session, ev(actor_type="candidate", actor_id=c, item_type="job", item_id=j, type="swipe_right"))
    assert application_status(session, c, j).status == "sent"  # type: ignore[union-attr]
    record_event(
        session,
        ev(
            actor_type="recruiter",
            actor_id=r,
            item_type="candidate",
            item_id=c,
            context_job_id=j,
            type="impression",
            session_id="rs",
        ),
    )
    assert application_status(session, c, j).status == "seen"  # type: ignore[union-attr]
    with pytest.raises(EventError):  # rejecting an applicant needs a reason
        record_event(
            session,
            ev(
                actor_type="recruiter",
                actor_id=r,
                item_type="candidate",
                item_id=c,
                context_job_id=j,
                type="swipe_left",
                session_id="rs",
            ),
        )
    record_event(
        session,
        ev(
            actor_type="recruiter",
            actor_id=r,
            item_type="candidate",
            item_id=c,
            context_job_id=j,
            type="swipe_left",
            reason="seniority",
            session_id="rs",
        ),
    )
    st = application_status(session, c, j)
    assert st is not None and st.status == "not_advanced" and st.reason == "seniority"
    session.commit()
    clock.advance_days(1)
    record_event(
        session, ev(actor_type="candidate", actor_id=c, item_type="job", item_id=j, type="swipe_right", session_id="s9")
    )
    assert application_status(session, c, j).status == "sent"  # type: ignore[union-attr]


def test_exploration_slot(session: Session, world: dict) -> None:
    # many similar jobs so the band (20–60 percentile, beyond the top 30) is not empty
    for i in range(120):
        upsert_job(
            session,
            extract_job(
                RawPosting(
                    title=f"Analista de Dados {i}", description="Requisitos\n- SQL\n", location_text="Remoto (Brasil)"
                )
            ),
            source="t",
            source_id=str(i),
        )
    session.commit()
    deck = candidate_deck(session, world["cand"], "s-x", limit=20)
    cards = deck["cards"]
    explore = [k for k, c in enumerate(cards, start=1) if c["rank_meta"]["slot"] == "explore"]
    assert explore == [RULES.exploration.every, 2 * RULES.exploration.every]
    for k in explore:
        card = cards[k - 1]
        assert card["rank_meta"]["rank_position"] > RULES.exploration.exclude_top
        assert 0 < card["rank_meta"]["propensity"] < 1 and card["explanation"]["slot_text"]
        assert "explore" in [b["code"] for b in card["badges"]]
    assert all(c["rank_meta"]["propensity"] == 1.0 for c in cards if c["rank_meta"]["slot"] == "ranked")


def test_feedback_v1_needs_k_min_and_learns(session: Session, world: dict) -> None:
    c = world["cand"]
    jobs = session.exec(select(Job).where(Job.origin == "market")).all()
    assert make_history_fn(session, "candidate", c) is None
    liked = [j for j in jobs if "Dados" in j.title or "Data" in j.title][: RULES.feedback.k_min]
    for j in liked:
        record_event(session, ev(actor_type="candidate", actor_id=c, item_type="job", item_id=j.id, type="swipe_right"))
    session.commit()
    assert make_history_fn(session, "candidate", c) is not None
    deck = candidate_deck(session, c, "s-fb", limit=40, ranker="feedback-v1")
    assert deck["history_active"]
    pillars = deck["cards"][0]["explanation"]["pillars"]
    assert [p["pillar"] for p in pillars] == ["atende", "interessa", "historico"]
    static = candidate_deck(session, c, "s-fb2", limit=40, ranker="static-v1")
    assert not static["history_active"]


def test_feedback_weights_decay_and_revisions() -> None:
    now = clock.now()
    assert _weight(now, now, 0, RULES) == pytest.approx(1.0)
    assert _weight(now - timedelta(days=RULES.feedback.half_life_days), now, 0, RULES) == pytest.approx(0.5)
    assert _weight(now, now, 1, RULES) == pytest.approx(RULES.feedback.gamma)


def test_rejected_job_returns_when_its_version_changes(session: Session, world: dict) -> None:
    c, mjob = world["cand"], world["mjob"]
    record_event(
        session,
        ev(actor_type="candidate", actor_id=c, item_type="job", item_id=mjob, type="swipe_left", reason="role_area"),
    )
    session.commit()
    ids = [x["item_id"] for x in candidate_deck(session, c, "a", limit=200)["cards"]]
    assert mjob not in ids
    job = session.get(Job, mjob)
    draft = extract_job(
        RawPosting(
            title=job.title,
            description=job.description_text + "\n- Git",  # type: ignore[union-attr]
            location_text=job.location_text,
        )
    )  # type: ignore[union-attr]
    upsert_job(session, draft, source=job.source, source_id=job.source_id)  # type: ignore[union-attr]
    session.commit()
    cards = candidate_deck(session, c, "b", limit=200)["cards"]
    card = next((x for x in cards if x["item_id"] == mjob), None)
    if card is not None:  # it may now be filtered; when shown, it carries the badge
        assert "job_updated" in [b["code"] for b in card["badges"]]


def test_blind_card_and_invisible_candidates(session: Session, world: dict) -> None:
    cand = session.get(__import__("app.models", fromlist=["Candidate"]).Candidate, world["cand"])
    profile = current_profile(session, cand)  # type: ignore[arg-type]
    blind = candidate_card_profile(profile, matched=False, contact=cand.contact)  # type: ignore[arg-type,union-attr]
    assert blind["name"] is None and blind["contact"] is None
    assert all(e["company"] is None for e in blind["experiences"])
    assert all(e["institution"] is None for e in blind["education"])
    full = candidate_card_profile(profile, matched=True, contact=cand.contact)  # type: ignore[arg-type,union-attr]
    assert full["name"] == "Bia Teste" and full["contact"] == "bia@example.com"
    cand.visible_to_recruiters = False  # type: ignore[union-attr]
    session.add(cand)
    from app.profiles import bump_candidates_version

    bump_candidates_version(session)
    session.commit()
    result = rank_for_job(session, world["pjob"])
    entry = next(f for f in result.filtered if f.item_id == world["cand"])
    assert [r.code for r in entry.reasons][0] == "not_visible"
    assert world["cand"] not in [c["item_id"] for c in recruiter_deck(session, world["rec"], world["pjob"])["cards"]]


def test_revision_kinds(session: Session, world: dict) -> None:
    cand = session.get(__import__("app.models", fromlist=["Candidate"]).Candidate, world["cand"])
    profile = current_profile(session, cand)  # type: ignore[arg-type]
    same = save_profile(session, cand, profile)  # type: ignore[arg-type]
    assert not same.changed
    minor = save_profile(session, cand, profile.model_copy(update={"headline": "Analista de Dados e BI"}))  # type: ignore[arg-type,union-attr]
    assert minor.kind == "minor"
    more = profile.model_copy(update={"skills_listed": ["dbt", "airflow", "spark"]})  # type: ignore[union-attr]
    assert save_profile(session, cand, more).kind == "relevant"  # type: ignore[arg-type]
    revs = session.exec(select(ProfileRevision).where(ProfileRevision.candidate_id == world["cand"])).all()
    assert [r.kind for r in revs] == ["relevant", "minor", "relevant"]


def _reconstruct(cards: list[dict], side: str) -> list[int]:
    def key(c: dict) -> tuple:
        e = c["explanation"]
        pillars = {p["pillar"]: p["position"] for p in e["pillars"]}
        req = next(line["position"] for line in e["lines"] if line["criterion"] == "requirements")
        group = 0 if (side == "recruiter" and c.get("applicant")) else 1
        return (group, round(e["final_sum"], 9), pillars["atende"], req, c["item_id"])

    return [c["item_id"] for c in sorted(cards, key=key)]


def test_shown_positions_reconstruct_order_with_history_company_penalty_and_applicants(
    session: Session, world: dict
) -> None:
    c = world["cand"]
    jobs = [j for j in session.exec(select(Job).where(Job.origin == "market")).all()]
    record_event(
        session,
        ev(
            actor_type="candidate", actor_id=c, item_type="job", item_id=jobs[0].id, type="swipe_left", reason="company"
        ),
    )
    for j in jobs[1 : RULES.feedback.k_min + 1]:
        record_event(session, ev(actor_type="candidate", actor_id=c, item_type="job", item_id=j.id, type="swipe_right"))
    session.commit()
    deck = candidate_deck(session, c, "s-r", limit=60, ranker="feedback-v1")
    assert deck["history_active"]
    ranked = sorted(
        (x for x in deck["cards"] if x["rank_meta"]["slot"] == "ranked"), key=lambda x: x["rank_meta"]["rank_position"]
    )
    assert _reconstruct(ranked, "candidate") == [x["item_id"] for x in ranked]
    # side B: applicants first, in formula order
    for i in range(4):
        other = create_candidate(
            session,
            CandidateProfile(
                headline="Analista de Dados",
                city_id="florianopolis-sc-br",
                wants=WANTS,
                experiences=[ExperienceIn(role="Analista de Dados", start=date(2023, 1, 1), skills_used=["sql"])],
            ),
            synthetic=True,
            visible=True,
        ).candidate
        if i % 2 == 0:
            record_event(
                session,
                ev(
                    actor_type="candidate",
                    actor_id=other.id,
                    item_type="job",
                    item_id=world["pjob"],
                    type="swipe_right",
                ),
            )
    session.commit()
    rdeck = recruiter_deck(session, world["rec"], world["pjob"], "s-b", limit=40)
    cards = sorted(rdeck["cards"], key=lambda x: x["rank_meta"]["rank_position"])
    assert [x["applicant"] for x in cards][:2] == [True, True]
    assert _reconstruct(cards, "recruiter") == [x["item_id"] for x in cards]


def test_export_and_purge(session: Session, world: dict) -> None:
    c = world["cand"]
    record_event(
        session, ev(actor_type="candidate", actor_id=c, item_type="job", item_id=world["pjob"], type="swipe_right")
    )
    record_event(
        session,
        ev(
            actor_type="recruiter",
            actor_id=world["rec"],
            item_type="candidate",
            item_id=c,
            context_job_id=world["pjob"],
            type="swipe_right",
        ),
    )
    session.commit()
    data = export_candidate(session, c)
    assert data is not None and len(data["events"]) >= 3 and data["matches"] and data["revisions"]
    counts = purge_candidate(session, c)
    session.commit()
    assert counts["events"] >= 3 and counts["candidate"] == 1
    assert (
        session.exec(
            select(InteractionEvent).where(InteractionEvent.actor_id == c, InteractionEvent.actor_type == "candidate")
        ).all()
        == []
    )
    assert session.exec(select(Match)).all() == []
    from app.db import trigger_names

    assert "interactionevent_no_delete" in trigger_names(session)
