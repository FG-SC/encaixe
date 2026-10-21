"""Login by e-mail link and the access rules of every route. Fictional people only."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from fastapi.routing import APIRoute
from sqlmodel import Session, select

from app import auth, clock, mailer
from app.config import RULES, Settings, reset_settings
from app.models import Account, AuthSession, LoginToken


def _token() -> str:
    return re.search(r"#t=([\w-]+)", mailer.OUTBOX[-1]["body"]).group(1)  # type: ignore[union-attr]


def test_magic_link_flow(client) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/me").json()["account"] is None
    assert client.get("/api/candidates/1/xray").status_code == 401
    r = client.post("/api/auth/request", json={"email": "  Bia@Example.COM "})
    assert r.status_code == 200 and "spam" in r.json()["message"]
    sent = mailer.OUTBOX[-1]
    assert sent["to"] == "bia@example.com" and "/entrar#t=" in sent["body"]
    token = _token()
    # a first login needs the terms; asking does not spend the link
    assert client.post("/api/auth/verify", json={"token": token}).status_code == 409
    me = client.post("/api/auth/verify", json={"token": token, "accept_terms": True}).json()
    assert me["account"]["email"] == "bia@example.com" and me["account"]["terms_version"] == RULES.auth.terms_version
    assert client.get("/api/me").json()["account"]["email"] == "bia@example.com"
    # the link works once
    assert client.post("/api/auth/verify", json={"token": token, "accept_terms": True}).status_code == 400
    client.post("/api/auth/logout")
    assert client.get("/api/me").json()["account"] is None


def test_links_expire_and_are_rate_limited(client, session: Session) -> None:  # type: ignore[no-untyped-def]
    client.post("/api/auth/request", json={"email": "bia@example.com"})
    assert client.post("/api/auth/request", json={"email": "bia@example.com"}).status_code == 429
    assert client.post("/api/auth/request", json={"email": "invalido"}).status_code == 422
    row = session.exec(select(LoginToken)).one()
    row.expires_at = clock.real_now() - timedelta(seconds=1)
    session.add(row)
    session.commit()
    assert client.post("/api/auth/verify", json={"token": _token(), "accept_terms": True}).status_code == 400


def test_sessions_use_real_time_not_the_demo_clock(client, login) -> None:  # type: ignore[no-untyped-def]
    login("bia@example.com")
    client.post("/api/dev/clock", json={"advance_days": RULES.auth.session_days + 15})
    assert client.get("/api/me").json()["account"]["email"] == "bia@example.com"


def test_invite_only_beta(client, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ALLOWED_EMAILS", "convidada@example.com")
    reset_settings()
    assert client.post("/api/auth/request", json={"email": "curioso@example.com"}).status_code == 403
    assert client.post("/api/auth/request", json={"email": "Convidada@example.com"}).status_code == 200


def _create_candidate(client, login, email: str) -> int:  # type: ignore[no-untyped-def]
    login(email)
    profile = {"headline": "Analista de Dados", "city_id": "florianopolis-sc-br"}
    return client.post("/api/candidates", json={"profile": profile}).json()["candidate_id"]


def test_a_profile_is_only_reachable_by_its_account(client, login) -> None:  # type: ignore[no-untyped-def]
    ana = _create_candidate(client, login, "ana@example.com")
    assert client.post("/api/candidates", json={"profile": {"headline": "x"}}).status_code == 409
    bia = _create_candidate(client, login, "bia@example.com")
    # Bia's session on Ana's routes: everything is 404, including export and delete
    for path in ("", "/xray", "/deck", "/filtered", "/applications", "/saved", "/explore", "/export"):
        assert client.get(f"/api/candidates/{ana}{path}").status_code == 404, path
    assert client.delete(f"/api/candidates/{ana}").status_code == 404
    assert client.put(f"/api/candidates/{ana}/profile", json={"headline": "x"}).status_code == 404
    assert client.get(f"/api/candidates/{bia}/xray").status_code == 200


def test_events_act_as_the_logged_account(client, login, session: Session) -> None:  # type: ignore[no-untyped-def]
    from app.seed.loader import load_seed_jobs

    load_seed_jobs(session)
    session.commit()
    ana = _create_candidate(client, login, "ana@example.com")
    bia = _create_candidate(client, login, "bia@example.com")
    event = {
        "client_event_id": "e-1",
        "actor_type": "candidate",
        "actor_id": ana,  # forged: Bia is logged in
        "item_type": "job",
        "item_id": 1,
        "type": "impression",
        "session_id": "s",
    }
    assert client.post("/api/events", json=event).status_code == 200
    from app.models import InteractionEvent

    stored = session.exec(select(InteractionEvent).where(InteractionEvent.client_event_id == "e-1")).one()
    assert stored.actor_id == bia
    recruiter_event = {**event, "client_event_id": "e-2", "actor_type": "recruiter", "context_job_id": 1}
    assert client.post("/api/events", json=recruiter_event).status_code == 403  # Bia is not a recruiter


def test_recruiters_only_reach_their_own_jobs(client, login) -> None:  # type: ignore[no-untyped-def]
    def recruiter(email: str, company: str) -> tuple[int, int]:
        login(email)
        rid = client.post("/api/recruiters", json={"name": "Pessoa", "company": company}).json()["id"]
        draft = client.post("/api/jobs/parse", json={"text": "Analista de Dados\nRequisitos\n- SQL", "use_llm": False})
        job = client.post(f"/api/recruiters/{rid}/jobs", json={"draft": draft.json()}).json()["job_id"]
        return rid, job

    rid_a, job_a = recruiter("rh@tainha.example", "Tainha Analytics")
    rid_b, _ = recruiter("rh@farol.example", "Farol Fintech")
    for path in (f"/api/recruiters/{rid_a}/jobs", f"/api/recruiters/{rid_a}/matches"):
        assert client.get(path).status_code == 404, path
    for path in ("deck", "funnel", "explore"):
        assert client.get(f"/api/recruiters/{rid_a}/jobs/{job_a}/{path}").status_code == 404, path
    assert client.patch(f"/api/jobs/{job_a}", json={"status": "closed", "recruiter_id": rid_a}).status_code == 404
    assert client.get(f"/api/recruiters/{rid_b}/jobs").status_code == 200


ALLOWED_WITHOUT_LOGIN = {
    "/api/health",
    "/api/rules/public",
    "/api/rules",
    "/api/meta/skills",
    "/api/meta/cities",
    "/api/auth/request",
    "/api/auth/verify",
    "/api/auth/logout",
    "/api/me",
}


def _calls(dependant) -> set:  # type: ignore[no-untyped-def]
    out = {dependant.call}
    for sub in dependant.dependencies:
        out |= _calls(sub)
    return out


def test_every_api_route_requires_login(monkeypatch: pytest.MonkeyPatch) -> None:
    """A new route must depend on current_account (or be a dev-only route that production never mounts)."""
    from app.api.main import create_app

    for env, allowed_dev in (("dev", True), ("prod", False)):
        monkeypatch.setenv("ENCAIXE_ENV", env)
        monkeypatch.setattr(Settings, "prod_problems", lambda self: [])
        reset_settings()
        app = create_app(front_dist=None)
        for route in app.routes:
            if not isinstance(route, APIRoute) or not route.path.startswith("/api"):
                continue
            if route.path in ALLOWED_WITHOUT_LOGIN or (allowed_dev and route.path.startswith("/api/dev/")):
                continue
            calls = _calls(route.dependant)
            assert auth.current_account in calls or auth.dev_only in calls, (env, route.path)
        if env == "prod":
            assert not any(getattr(r, "path", "").startswith("/api/dev") for r in app.routes)


def test_logout_closes_the_session_row(client, login, session: Session) -> None:  # type: ignore[no-untyped-def]
    login("bia@example.com")
    assert len(session.exec(select(AuthSession)).all()) == 1
    client.post("/api/auth/logout")
    session.expire_all()
    assert session.exec(select(AuthSession)).all() == []
    assert session.exec(select(Account)).one().email == "bia@example.com"
