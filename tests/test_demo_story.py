"""The demo story through the API (spec 1.7 #4): rejected, learned why, evolved, matched."""

from __future__ import annotations

import uuid
from datetime import date

from app import clock
from app.db import session_scope
from app.seed.loader import load_recruiters, load_seed_jobs, persona_text


def _event(client, **kw):  # type: ignore[no-untyped-def]
    body = {"client_event_id": str(uuid.uuid4()), "session_id": "s-demo", **kw}
    return client.post("/api/events", json=body)


def _card_meta(card: dict) -> dict:
    m = card["rank_meta"]
    return {k: m[k] for k in ("rank_position", "rank_sum", "slot", "propensity", "ranker_version", "rank_detail")}


def _find(cards: list[dict], item_id: int) -> dict | None:
    return next((c for c in cards if c["item_id"] == item_id), None)


def test_demo_story(client, login) -> None:  # type: ignore[no-untyped-def]
    with session_scope() as s:
        load_seed_jobs(s)
        load_recruiters(s)

    # 1. Ana logs in by e-mail link, pastes her CV, reviews and saves; preferences come from onboarding.
    login("ana@example.com")
    draft = client.post("/api/candidates/parse", data={"text": persona_text("ana"), "llm_consent": "false"}).json()
    assert draft["city_id"] == "florianopolis-sc-br" and draft["llm_status"].startswith("off")
    profile = {
        k: draft[k]
        for k in ("name", "contact", "headline", "city_id", "experiences", "education", "skills_listed", "languages")
    }
    profile["wants"] = {
        "comp_min": 5000,
        "currency": "BRL",
        "period": "month",
        "arrangements": ["remote", "hybrid", "onsite"],
        "max_distance_km": 60,
    }
    created = client.post("/api/candidates", json={"profile": profile, "visible_to_recruiters": True}).json()
    ana = created["candidate_id"]
    assert created["kind"] == "relevant"

    xray = client.get(f"/api/candidates/{ana}/xray").json()
    assert xray["share_card"]["personal_data"] is False and len(xray["top_unlock"]) == 3

    # 2. "Sales Manager" is in "Vagas que não te mostramos", out of area.
    filtered = client.get(f"/api/candidates/{ana}/filtered").json()
    out_of_area = next(g for g in filtered["groups"] if g["code"] == "out_of_area")
    assert any(i["job"]["title"] == "Sales Manager" for i in out_of_area["items"])

    # 3. Carla (Lumen Dados) publishes "ML Engineer Jr" by pasting its text.
    carla = next(r for r in client.get("/api/recruiters").json() if r["name"] == "Carla Menezes")["id"]
    login(recruiter_id=carla)
    job_draft = client.post("/api/jobs/parse", json={"text": persona_text("lumen_ml_engineer_jr")}).json()
    assert job_draft["requires"]["skills_must"] == ["python", "sql", "statistics", "pytorch", "deep_learning"]
    assert "motivo da recusa" in job_draft["notice"]
    job = client.post(f"/api/recruiters/{carla}/jobs", json={"draft": job_draft}).json()["job_id"]

    # 4. Ana finds the job in her deck and applies.
    login(candidate_id=ana)
    deck = client.get(f"/api/candidates/{ana}/deck", params={"session_id": "s-ana", "limit": 200}).json()
    card = _find(deck["cards"], job)
    assert card is not None and not card["good_fit"]["is_good_fit"]
    r = _event(
        client,
        actor_type="candidate",
        actor_id=ana,
        item_type="job",
        item_id=job,
        type="swipe_right",
        **_card_meta(card),
    ).json()
    assert r["results"][0]["created"] and r["results"][0]["impression_auto_created"]
    apps = client.get(f"/api/candidates/{ana}/applications").json()
    assert apps[0]["status"] == "sent"

    # 5. Carla's deck: Ana's blind card first, as an applicant; she declines with reason "skills".
    login(recruiter_id=carla)
    assert client.get(f"/api/candidates/{ana}/applications").status_code == 404  # Carla cannot read Ana's data
    rdeck = client.get(f"/api/recruiters/{carla}/jobs/{job}/deck", params={"session_id": "s-carla"}).json()
    first = rdeck["cards"][0]
    assert first["item_id"] == ana and first["applicant"] and first["candidate"]["name"] is None
    assert first["candidate"]["contact"] is None and first["explanation"]["applicants_first_text"]
    no_reason = _event(
        client,
        actor_type="recruiter",
        actor_id=carla,
        item_type="candidate",
        item_id=ana,
        context_job_id=job,
        type="swipe_left",
        **_card_meta(first),
    )
    assert no_reason.status_code == 422
    ok = _event(
        client,
        actor_type="recruiter",
        actor_id=carla,
        item_type="candidate",
        item_id=ana,
        context_job_id=job,
        type="swipe_left",
        reason="skills",
        **_card_meta(first),
    )
    assert ok.status_code == 200

    # 6. Ana sees that it did not advance, why, and what was missing.
    login(candidate_id=ana)
    app = client.get(f"/api/candidates/{ana}/applications").json()[0]
    assert app["status"] == "not_advanced" and app["seen_at"] is not None
    fb = app["feedback"]
    assert fb["reason"] == "skills" and [g["skill"] for g in fb["gaps"]["skills"]] == ["pytorch", "deep_learning"]
    assert "não avançou" in fb["message"] and "5 de 5" in fb["message"] and "bom encaixe" in fb["message"]
    assert "reprovad" not in fb["message"].lower()

    # 7. Time passes; Ana adds a dated experience using PyTorch and deep learning → relevant revision.
    client.post("/api/dev/clock", json={"advance_days": 45})
    today = clock.today()
    profile["experiences"] = [
        {
            "company": "Maré Logística Digital",
            "role": "Analista de Dados (projeto de visão computacional)",
            "seniority": 2,
            "start": date(today.year, today.month, 1).isoformat(),
            "end": None,
            "skills_used": ["python", "pytorch", "deep_learning", "computer_vision"],
            "responsibilities": "Treinei modelos de deep learning com PyTorch para inspeção visual de pacotes.",
            "outcomes": [],
        },
        *profile["experiences"],
    ]
    upd = client.put(f"/api/candidates/{ana}/profile", json=profile).json()
    assert upd["changed"] and upd["kind"] == "relevant"

    # 8. The job returns to her deck ("seu perfil mudou desde a recusa"); she applies again.
    deck = client.get(f"/api/candidates/{ana}/deck", params={"session_id": "s-ana-2", "limit": 200}).json()
    card = _find(deck["cards"], job)
    assert card is not None
    assert "profile_changed_since_rejection" in [b["code"] for b in card["badges"]]
    assert card["good_fit"]["is_good_fit"]
    _event(
        client,
        actor_type="candidate",
        actor_id=ana,
        item_type="job",
        item_id=job,
        type="swipe_right",
        session_id="s-ana-2",
        **_card_meta(card),
    )
    assert client.get(f"/api/candidates/{ana}/applications").json()[0]["status"] == "sent"

    # 9. Ana is back in Carla's deck ("perfil atualizado…"), now 5 of 5; Carla swipes right → É um encaixe!
    login(recruiter_id=carla)
    rdeck = client.get(f"/api/recruiters/{carla}/jobs/{job}/deck", params={"session_id": "s-carla-2"}).json()
    card = _find(rdeck["cards"], ana)
    assert card is not None and "profile_updated_since_last_review" in [b["code"] for b in card["badges"]]
    must = card["requirements"]["must"]
    assert all(m["status"].startswith("proven") for m in must) and len(must) == 5
    res = _event(
        client,
        actor_type="recruiter",
        actor_id=carla,
        item_type="candidate",
        item_id=ana,
        context_job_id=job,
        type="swipe_right",
        session_id="s-carla-2",
        **_card_meta(card),
    ).json()
    assert res["results"][0]["match"]["title"] == "É um encaixe!"
    matches = client.get(f"/api/recruiters/{carla}/matches").json()
    assert matches[0]["candidate"]["name"] == "Ana Ribeiro Lima" and matches[0]["candidate"]["contact"]
    login(candidate_id=ana)
    assert client.get(f"/api/candidates/{ana}/applications").json()[0]["status"] == "matched"
