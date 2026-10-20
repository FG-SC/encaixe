"""Phase 0: config, clock, database guarantees, health and the public rules."""

from __future__ import annotations

import dataclasses
import json
import re
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlmodel import Session, select

from app import clock
from app.config import RULES, Rules, rules_as_dict, rules_hash
from app.db import allow_event_delete, from_blob, get_engine, to_blob, trigger_names
from app.models import Candidate, Experience, InteractionEvent, Job

APP_DIR = Path(__file__).resolve().parents[1] / "app"


# --------------------------------------------------------------------------- config


def test_rules_hash_is_stable_and_tracks_changes() -> None:
    assert rules_hash() == rules_hash(Rules())
    changed = dataclasses.replace(
        RULES, feedback=dataclasses.replace(RULES.feedback, half_life_days=30)
    )
    assert rules_hash(changed) != rules_hash()


def test_rules_are_json_serializable_and_read_only() -> None:
    json.dumps(rules_as_dict())
    with pytest.raises(TypeError):
        RULES.feedback.lambda_candidate["role_area"] = 2.0  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        RULES.good_fit.must_share = 0.5  # type: ignore[misc]


def test_spec_thresholds() -> None:
    assert RULES.good_fit.must_share == 0.8 and RULES.good_fit.max_seniority_gap == 1
    assert RULES.filters.comp_min_ratio == 0.7 and RULES.filters.seniority_gap_exclude == 3
    assert RULES.feedback.half_life_days == 21 and RULES.feedback.gamma == 0.5 and RULES.feedback.k_min == 5
    assert RULES.feedback.company_penalty == 0.15
    assert RULES.exploration.every == 10 and RULES.exploration.exclude_top == 30
    assert (RULES.exploration.band_low_pct, RULES.exploration.band_high_pct) == (20, 60)
    assert RULES.aggregation.aggregator == "rank_sum" and RULES.aggregation.rrf_k == 60
    assert RULES.precision.cosine == 0.02 and RULES.precision.distance_km == 5
    assert RULES.events.impression_min_ms == 500 and RULES.events.session_idle_minutes == 30
    assert RULES.privacy.k_anon == 5 and RULES.revisions.relevant_skill_symdiff == 3
    assert RULES.rankers.default == "feedback-v1"


# --------------------------------------------------------------------------- clock


def test_clock_offset_moves_now() -> None:
    before = clock.now()
    clock.set_offset_days(10)
    assert clock.get_offset_days() == 10
    assert clock.now() - before >= timedelta(days=10)
    clock.advance_days(2.5)
    assert clock.get_offset_days() == 12.5
    assert clock.today() >= date.today()  # noqa: DTZ011 - test-only reference
    with pytest.raises(ValueError):
        clock.set_offset_days(-1)


def test_no_direct_system_clock_outside_clock_module() -> None:
    pattern = re.compile(r"datetime\.now\(|datetime\.utcnow\(|date\.today\(")
    offenders = [
        str(p.relative_to(APP_DIR))
        for p in APP_DIR.rglob("*.py")
        if p.name != "clock.py" and pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


# --------------------------------------------------------------------------- database


def _event(**kw: object) -> InteractionEvent:
    base: dict[str, object] = dict(
        client_event_id="e-1", actor_type="candidate", actor_id=1, item_type="job", item_id=1,
        type="impression", session_id="s",
    )
    base.update(kw)
    return InteractionEvent(**base)  # type: ignore[arg-type]


def test_events_are_append_only() -> None:
    engine = get_engine()
    with Session(engine) as s:
        s.add(_event())
        s.commit()
        assert {"interactionevent_no_update", "interactionevent_no_delete"} <= trigger_names(s)
    with engine.connect() as conn, pytest.raises(DatabaseError, match="append-only"):
        conn.execute(text("UPDATE interactionevent SET reason = 'salary'"))
    with engine.connect() as conn, pytest.raises(DatabaseError, match="append-only"):
        conn.execute(text("DELETE FROM interactionevent"))


def test_purge_path_can_delete_and_restores_trigger() -> None:
    engine = get_engine()
    with Session(engine) as s:
        s.add(_event())
        s.commit()
    with Session(engine) as s:
        with allow_event_delete(s):
            s.execute(text("DELETE FROM interactionevent"))
        s.commit()
        assert s.exec(select(InteractionEvent)).all() == []
        assert "interactionevent_no_delete" in trigger_names(s)


def test_client_event_id_is_unique() -> None:
    with Session(get_engine()) as s:
        s.add(_event())
        s.commit()
        s.add(_event(item_id=2))
        with pytest.raises(IntegrityError):
            s.commit()


def test_json_columns_and_vectors_round_trip() -> None:
    vec = np.arange(384, dtype=np.float32) / 384
    with Session(get_engine()) as s:
        wants = {"comp_min": 5000, "arrangements": ["remote"]}
        c = Candidate(name="Fulana", wants=wants, skills_listed=["sql"])
        s.add(c)
        s.commit()
        s.add(Experience(candidate_id=c.id, role="Analista", start=date(2023, 1, 1), skills_used=["sql"]))
        s.add(Job(source="seed", source_id="1", title="Analista", requires={"skills_must": ["sql"]}))
        s.commit()
        cid = c.id
    with Session(get_engine()) as s:
        c2 = s.get(Candidate, cid)
        assert c2 is not None and c2.wants["arrangements"] == ["remote"] and c2.created_at.tzinfo is not None
    assert np.allclose(from_blob(to_blob(vec)), vec)


# --------------------------------------------------------------------------- API


def test_health(client) -> None:  # type: ignore[no-untyped-def]
    body = client.get("/api/health").json()
    assert body["ok"] is True and body["rules_hash"] == rules_hash()


def test_rules_public_numbers_come_from_rules(client) -> None:  # type: ignore[no-untyped-def]
    body = client.get("/api/rules/public").json()
    assert body["events"]["impression_min_ms"] == RULES.events.impression_min_ms
    assert body["events"]["session_idle_minutes"] == RULES.events.session_idle_minutes
    assert body["exploration"]["every"] == RULES.exploration.every
    assert [r["code"] for r in body["reasons"]["recruiter"]] == list(RULES.reasons.recruiter)
    assert body["privacy"]["below_k_label"] == f"<{RULES.privacy.k_anon}"
    assert len(body["seniority"]) == 6
