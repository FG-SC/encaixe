"""Optional LLM (spec 6), fully offline: a MockTransport plays Groq. Every failure falls back, visibly."""

from __future__ import annotations

import json

import httpx
import pytest
from sqlmodel import Session, select

from app.config import reset_settings
from app.llm import client as llm_client
from app.llm.onboarding import extract_cv_for_onboarding
from app.llm.ratelimit import Limiter, RateLimited
from app.llm.schemas import CvExtraction, JobExtraction, strict_json_schema, violations
from app.models import LlmCache, Setting
from app.seed.loader import persona_text

CV_OUT = {
    "headline": "Analista de Dados Júnior",
    "city": "Florianópolis",
    "experiences": [
        {
            "role": "Analista de Dados Júnior",
            "company": "Maré Logística Digital",
            "start": "2024-03",
            "end": None,
            "skills": ["SQL", "Python", "Power BI"],
            "responsibilities": "Painéis e SQL.",
        }
    ],
    "education": [
        {
            "degree": "Bacharelado",
            "field": "Estatística",
            "institution": "Universidade X",
            "start_year": 2019,
            "end_year": 2023,
            "in_progress": False,
        }
    ],
    "skills_listed": ["Git", "Excel"],
    "languages": [{"language": "en", "level": "intermediate"}],
}


def completion(content: dict) -> dict:
    return {
        "id": "c1",
        "object": "chat.completion",
        "created": 0,
        "model": "openai/gpt-oss-20b",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(content, ensure_ascii=False)},
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


@pytest.fixture
def groq(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    reset_settings()
    import app.llm.ratelimit as rl

    monkeypatch.setattr(rl, "_limiter", Limiter(sleep=lambda s: None))
    state: dict = {"requests": [], "respond": lambda req: httpx.Response(200, json=completion(CV_OUT))}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(json.loads(request.content))
        return state["respond"](request)

    llm_client.set_transport(httpx.MockTransport(handler))
    yield state
    llm_client.set_transport(None)


def test_schemas_follow_strict_mode_rules() -> None:
    for schema in (CvExtraction, JobExtraction):
        assert violations(strict_json_schema(schema)) == []
    from langchain_core.utils.function_calling import convert_to_json_schema

    lc = convert_to_json_schema(CvExtraction, strict=True)
    bad = [v for v in violations(lc) if "keyword 'default'" in v or "minimum" in v or "pattern" in v]
    assert bad == []  # no defaults leak: nullable fields have no default


def test_cv_extraction_with_llm_sends_strict_and_uses_the_cache(session: Session, groq) -> None:  # type: ignore[no-untyped-def]
    draft = extract_cv_for_onboarding(persona_text("ana"), llm_consent=True)
    assert draft.method == "llm" and draft.llm_status == "ok" and draft.llm_cache_key
    sent = groq["requests"][0]
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["strict"] is True
    assert sent["reasoning_effort"] == "low"
    assert draft.experiences[0].skills_used == ["sql", "python", "power_bi"]
    assert draft.provenance["experiences.0.role"].method == "llm" and draft.provenance["experiences.0.role"].stated
    assert draft.name == "Ana Ribeiro Lima"  # name and contact never come from the LLM
    again = extract_cv_for_onboarding(persona_text("ana"), llm_consent=True)
    assert len(groq["requests"]) == 1 and again.llm_status == "ok (cache)"
    status = session.get(Setting, "llm_status").value  # type: ignore[union-attr]
    assert status["requests_today"] == 1 and status["cache_hits"] == 1


def test_no_consent_or_no_key_means_heuristic(session: Session, groq, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    d = extract_cv_for_onboarding(persona_text("ana"), llm_consent=False)
    assert d.method == "heuristic" and d.llm_status.startswith("off") and groq["requests"] == []
    monkeypatch.delenv("GROQ_API_KEY")
    reset_settings()
    d = extract_cv_for_onboarding(persona_text("ana"), llm_consent=True)
    assert d.method == "heuristic" and "GROQ_API_KEY" in d.llm_status


@pytest.mark.parametrize(
    ("status_code", "body", "expected"),
    [
        (
            400,
            {"error": {"code": "json_validate_failed", "message": "Generated JSON does not match"}},
            "json_validate_failed",
        ),
        (429, {"error": {"message": "rate limited"}}, "429"),
        (200, {"not": "a completion"}, "Error"),
    ],
)
def test_failures_fall_back_visibly(session: Session, groq, status_code, body, expected) -> None:  # type: ignore[no-untyped-def]
    groq["respond"] = lambda req: httpx.Response(status_code, json=body, headers={"retry-after": "1"})
    d = extract_cv_for_onboarding(persona_text("ana"), llm_consent=True)
    assert d.method == "heuristic" and d.llm_status.startswith("fallback") and d.experiences
    status = session.get(Setting, "llm_status").value  # type: ignore[union-attr]
    assert status["state"] == "error" and expected.lower() in str(status["reason"]).lower()


def test_rate_limiter() -> None:
    t = [0.0]
    lim = Limiter(clock=lambda: t[0], sleep=lambda s: None)
    lim.acquire(7000, max_wait=0)
    with pytest.raises(RateLimited):
        lim.acquire(7000, max_wait=5)  # the 8K tokens/min bucket is nearly empty
    t[0] += 60
    lim.acquire(7000, max_wait=0)
    with pytest.raises(RateLimited):
        lim.acquire(10, max_wait=0, requests_today=1000)  # daily cap
    lim.cool_down(30)
    with pytest.raises(RateLimited):
        lim.acquire(10, max_wait=5)


def test_background_job_upgrade_keeps_the_version(session: Session, groq) -> None:  # type: ignore[no-untyped-def]
    from app.extraction.job import RawPosting, extract_job
    from app.ingest.snapshot import save_snapshot
    from app.jobs import upsert_job
    from app.llm.queue import upgrade_job

    job = upsert_job(
        session,
        extract_job(RawPosting(title="Cientista de Dados", description="Trabalhe com dados.")),
        source="seed",
        source_id="x1",
    ).job
    session.commit()
    out = {
        "title": "Cientista de Dados",
        "company": None,
        "location": None,
        "arrangement": "remote",
        "seniority": "mid",
        "years_min": 3,
        "skills_must": ["Python", "machine learning"],
        "skills_nice": ["Spark"],
        "languages": [],
        "comp_min": None,
        "comp_max": None,
        "currency": None,
        "period": None,
        "regime": None,
        "eligibility_countries": [],
        "timezone": None,
    }
    groq["respond"] = lambda req: httpx.Response(200, json=completion(out))
    assert upgrade_job(job.id) is True
    session.expire_all()
    j = session.get(type(job), job.id)
    assert j.extraction_method == "llm" and j.version == 1  # type: ignore[union-attr]
    assert j.requires["skills_must"] == ["python", "machine_learning"] and j.requires["seniority"] == 3  # type: ignore[union-attr]
    assert j.offers["arrangement"] == "remote" and j.provenance["_llm"]["method"] == "llm"  # type: ignore[union-attr]
    path = save_snapshot(session, "llm")
    import gzip

    with gzip.open(path, "rt", encoding="utf-8") as fh:
        assert len(json.load(fh)["llm_cache"]) == 1


def test_purge_removes_the_cv_cache_entry(client, groq, login) -> None:  # type: ignore[no-untyped-def]
    login("ana@example.com")
    draft = client.post("/api/candidates/parse", data={"text": persona_text("ana"), "llm_consent": "true"}).json()
    profile = {
        k: draft[k]
        for k in (
            "name",
            "contact",
            "headline",
            "city_id",
            "experiences",
            "education",
            "skills_listed",
            "languages",
            "wants",
        )
    }
    cid = client.post(
        "/api/candidates", json={"profile": profile, "llm_consent": True, "llm_cache_key": draft["llm_cache_key"]}
    ).json()["candidate_id"]
    from app.db import session_scope

    with session_scope() as s:
        assert s.get(LlmCache, draft["llm_cache_key"]) is not None
    assert client.delete(f"/api/candidates/{cid}").json()["deleted"]["llm_cache"] == 1
    with session_scope() as s:
        assert s.get(LlmCache, draft["llm_cache_key"]) is None
        assert s.exec(select(Setting).where(Setting.key.startswith(f"llm_cv_cache:{cid}:"))).all() == []  # type: ignore[attr-defined]
