"""Groq client (spec 6): strict structured outputs, cache, rate limits, fallback to the heuristic.

Primary path: ``ChatGroq(...).with_structured_output(Schema, method="json_schema", strict=True)``, with a runtime
check that ``strict`` really goes on the wire (langchain-groq < 1.1.3 silently drops it, and only the gpt-oss
models support it). Otherwise: the OpenAI-compatible HTTP endpoint with our own strict schema.
Every call goes through LlmCache. Any failure raises LlmError; callers fall back to the heuristic and say so.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date

import httpx
from pydantic import BaseModel, ValidationError
from sqlmodel import Session

from app import clock
from app import geo as geo_mod
from app import taxonomy as tax_mod
from app.config import RULES, get_settings
from app.db import session_scope
from app.extraction.job import RawPosting
from app.llm.ratelimit import RateLimited, limiter
from app.llm.schemas import SENIORITY_LEVEL, CvExtraction, JobExtraction, strict_json_schema
from app.llm.status import _load as _load_status
from app.llm.status import update_status
from app.models import LlmCache
from app.schemas import CandidateDraft, EducationIn, ExperienceIn, JobDraft, LanguageLevel, Provenance
from app.textnorm import fold

log = logging.getLogger(__name__)
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

CV_SYSTEM = (
    "Você extrai o perfil profissional de um currículo para um sistema de vagas com regras abertas. "
    "Não invente nada: use só o que está no texto. Datas no formato AAAA-MM (ano sozinho: AAAA-01). "
    "Em cada experiência, liste em 'skills' apenas as tecnologias e competências usadas nela. "
    "'skills_listed' são as citadas fora das experiências. Não inclua nome, e-mail nem telefone."
)
JOB_SYSTEM = (
    "Você extrai os requisitos e a oferta de uma vaga de emprego. Não invente nada. Separe requisitos "
    "obrigatórios de diferenciais. Ignore textos institucionais (sobre a empresa, benefícios, diversidade). "
    "Salário só se for remuneração da vaga (nunca captação, faturamento ou número de clientes)."
)

_transport: httpx.BaseTransport | None = None  # tests inject a MockTransport


class LlmError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def set_transport(transport: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = transport


def cache_key(task: str, model: str, prompt_version: str, content: str) -> str:
    return hashlib.sha256("\x1f".join([task, model, prompt_version, content]).encode("utf-8")).hexdigest()


def _estimate_tokens(*texts: str) -> int:
    return int(sum(len(t) for t in texts) / 3.5) + RULES.llm.max_completion_tokens


def _langchain_call(schema: type[BaseModel], system: str, user: str, timeout: float) -> BaseModel:
    from langchain_groq import ChatGroq

    settings = get_settings()
    http_client = httpx.Client(transport=_transport, timeout=timeout) if _transport else None
    llm = ChatGroq(
        model=settings.llm_model,
        api_key=settings.groq_api_key,
        timeout=timeout,
        max_retries=0,
        reasoning_effort=RULES.llm.reasoning_effort,
        model_kwargs={"max_completion_tokens": RULES.llm.max_completion_tokens},
        http_client=http_client,
    )
    runnable = llm.with_structured_output(schema, method="json_schema", strict=True)
    rf = getattr(getattr(runnable, "first", None), "kwargs", {}).get("response_format", {})
    if rf.get("json_schema", {}).get("strict") is not True:
        raise NotImplementedError("strict not on the wire")
    return runnable.invoke([("system", system), ("user", user)])  # type: ignore[return-value]


def _raw_call(schema: type[BaseModel], system: str, user: str, timeout: float) -> BaseModel:
    settings = get_settings()
    body = {
        "model": settings.llm_model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "schema": strict_json_schema(schema), "strict": True},
        },
        "reasoning_effort": RULES.llm.reasoning_effort,
        "include_reasoning": False,
        "max_completion_tokens": RULES.llm.max_completion_tokens,
    }
    with httpx.Client(transport=_transport, timeout=timeout) as client:
        resp = client.post(GROQ_URL, json=body, headers={"Authorization": f"Bearer {settings.groq_api_key}"})
    if resp.status_code == 429:
        raise RateLimited(float(resp.headers.get("retry-after", "60") or 60), "429 do provedor")
    if resp.status_code == 400:
        code = (resp.json().get("error") or {}).get("code", "bad_request") if resp.content else "bad_request"
        raise LlmError(str(code))
    if resp.status_code != 200:
        raise LlmError(f"http_{resp.status_code}")
    content = resp.json()["choices"][0]["message"]["content"]
    return schema.model_validate_json(content)


def call_structured(
    task: str, schema: type[BaseModel], system: str, user: str, *, timeout: float, max_wait: float
) -> tuple[BaseModel, str, bool]:
    """(parsed output, cache key, cache hit). Raises LlmError on any failure (callers fall back)."""
    settings = get_settings()
    if not settings.llm_enabled:
        raise LlmError("sem GROQ_API_KEY")
    version = RULES.llm.prompt_versions.get(task, "v1")
    key = cache_key(task, settings.llm_model, version, user)
    with session_scope() as s:
        hit = s.get(LlmCache, key)
        if hit is not None:
            try:
                parsed = schema.model_validate(hit.output_json)
                update_status(cache_hits_inc=1)
                return parsed, key, True
            except ValidationError:
                pass
        status = _load_status(s)
    est = _estimate_tokens(system, user)
    try:
        limiter().acquire(est, max_wait, status.get("requests_today", 0), status.get("tokens_today", 0))
        try:
            parsed = _langchain_call(schema, system, user, timeout)
        except NotImplementedError:
            parsed = _raw_call(schema, system, user, timeout)
    except RateLimited as exc:
        limiter().cool_down(min(exc.wait_s, 120))
        update_status(state="on", reason=f"limite: {exc.reason}")
        raise LlmError(f"rate_limited: {exc.reason}") from exc
    except LlmError as exc:
        update_status(state="error", reason=exc.reason, requests_today_inc=1)
        raise
    except Exception as exc:  # groq.BadRequestError (json_validate_failed), timeouts, OutputParserException…
        reason = _reason(exc)
        if "429" in reason or "RateLimit" in reason:
            limiter().cool_down(60)
        update_status(state="error", reason=reason, requests_today_inc=1)
        raise LlmError(reason) from exc
    update_status(state="on", reason=None, requests_today_inc=1, tokens_today_inc=est)
    with session_scope() as s:
        if s.get(LlmCache, key) is None:
            s.add(
                LlmCache(
                    key=key,
                    task=task,
                    model=settings.llm_model,
                    prompt_version=version,
                    output_json=parsed.model_dump(mode="json"),
                    created_at=clock.now(),
                )
            )
    return parsed, key, False


def _reason(exc: Exception) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        code = (body.get("error") or {}).get("code")
        if code:
            return str(code)
    return f"{type(exc).__name__}: {str(exc)[:160]}"


# --------------------------------------------------------------------------- merge helpers


def _month(value: str | None) -> date | None:
    if not value:
        return None
    m = re.match(r"^\s*(\d{4})(?:-(\d{1,2}))?", value)
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2) or 1)
    if not 1900 <= year <= clock.today().year + 1 or not 1 <= month <= 12:
        return None
    return date(year, month, 1)


def _skill_ids(values: list[str]) -> list[str]:
    tax = tax_mod.load()
    out: dict[str, None] = {}
    for v in values:
        for sid in tax.skill_ids(v) or []:
            out.setdefault(sid, None)
    return list(out)


def _prov(source: str, value: str | None, key: str, confidence: float = 0.8) -> Provenance:
    stated = bool(value) and fold(value or "").strip() in fold(source)
    return Provenance(source_span=value, stated=stated, confidence=confidence if stated else 0.55, method="llm")


def llm_extract_cv(text: str, heuristic: CandidateDraft) -> CandidateDraft:
    """Synchronous, one call, RULES.llm.onboarding_timeout_s (spec 6). Never writes a saved profile."""
    timeout = RULES.llm.onboarding_timeout_s
    out, key, hit = call_structured("cv_extraction", CvExtraction, CV_SYSTEM, text, timeout=timeout, max_wait=timeout)
    assert isinstance(out, CvExtraction)
    tax = tax_mod.load()
    geo = geo_mod.load()
    draft = heuristic.model_copy(deep=True)
    prov = {
        k: v for k, v in draft.provenance.items() if not k.startswith(("experiences.", "skills_listed.", "education"))
    }
    experiences = []
    for n, e in enumerate(out.experiences):
        skills = _skill_ids([*e.skills, e.responsibilities or ""])
        sm = tax.seniority_from_title(e.role)
        experiences.append(
            ExperienceIn(
                company=e.company,
                role=e.role,
                seniority=sm.level if sm else None,
                start=_month(e.start),
                end=_month(e.end),
                skills_used=skills,
                responsibilities=e.responsibilities,
            )
        )
        prov[f"experiences.{n}.role"] = _prov(text, e.role, key)
        prov[f"experiences.{n}.start"] = _prov(text, e.start, key, 0.7)
        for sid in skills:
            prov[f"experiences.{n}.skills_used.{sid}"] = Provenance(
                source_span=e.role, stated=True, confidence=0.7, method="llm"
            )
    if experiences or not heuristic.experiences:
        draft.experiences = experiences
    else:
        prov.update({k: v for k, v in heuristic.provenance.items() if k.startswith("experiences.")})
    listed = _skill_ids(out.skills_listed)
    if listed:
        draft.skills_listed = listed
        for sid in listed:
            prov[f"skills_listed.{sid}"] = Provenance(
                source_span=tax.label(sid), stated=True, confidence=0.7, method="llm"
            )
    if out.education:
        draft.education = [
            EducationIn(
                degree=d.degree,
                field=d.field,
                institution=d.institution,
                start=date(d.start_year, 1, 1) if d.start_year else None,
                end=None if d.in_progress or not d.end_year else date(d.end_year, 12, 1),
            )
            for d in out.education
        ]
    if out.languages:
        langs = {lang.language: LanguageLevel(language=lang.language, level=lang.level) for lang in out.languages}
        for lang in heuristic.languages:
            langs.setdefault(lang.language, lang)
        draft.languages = list(langs.values())
    if out.headline:
        draft.headline = out.headline
        prov["headline"] = _prov(text, out.headline, key)
    if out.city and not draft.city_id:
        cm = geo.find_city(out.city)
        if cm:
            draft.city_id = cm.city_id
            prov["city_id"] = _prov(text, out.city, key)
    draft.provenance = prov
    draft.method = "llm"
    draft.llm_status = "ok (cache)" if hit else "ok"
    draft.llm_cache_key = key
    return draft


def llm_extract_job(raw: RawPosting, heuristic: JobDraft, *, background: bool = False) -> JobDraft:
    timeout = RULES.llm.background_timeout_s if background else RULES.llm.onboarding_timeout_s
    user = f"Título: {raw.title}\nLocal: {raw.location_text or '-'}\n\n{heuristic.description_text}"
    out, key, _hit = call_structured(
        "job_extraction",
        JobExtraction,
        JOB_SYSTEM,
        user,
        timeout=timeout,
        max_wait=RULES.llm.background_timeout_s if background else 5,
    )
    assert isinstance(out, JobExtraction)
    geo = geo_mod.load()
    draft = heuristic.model_copy(deep=True)
    prov = dict(draft.provenance)
    must = _skill_ids(out.skills_must) or draft.requires.skills_must
    nice = [s for s in (_skill_ids(out.skills_nice) or draft.requires.skills_nice) if s not in must]
    draft.requires.skills_must, draft.requires.skills_nice = must, nice
    for sid in must:
        prov[f"requires.skills_must.{sid}"] = Provenance(source_span=sid, stated=True, confidence=0.75, method="llm")
    if out.seniority and not raw.structured.get("seniority"):
        draft.requires.seniority = SENIORITY_LEVEL[out.seniority]
    if out.years_min is not None and 0 < out.years_min <= 25:
        draft.requires.years_min = float(out.years_min)
    if out.languages:
        draft.requires.languages = [LanguageLevel(language=x.language, level=x.level) for x in out.languages]
    if out.arrangement and not raw.structured.get("arrangement"):
        draft.offers.arrangement = out.arrangement
    if draft.offers.comp_max is None and out.comp_max is not None and out.currency:  # never replaces a found salary
        draft.offers.comp_min, draft.offers.comp_max = out.comp_min, out.comp_max
        draft.offers.currency, draft.offers.period = out.currency.upper(), out.period or "month"
        prov["offers.comp_max"] = Provenance(source_span=str(out.comp_max), stated=True, confidence=0.75, method="llm")
    if out.regime:
        draft.offers.regime = out.regime
    if out.eligibility_countries:
        codes: dict[str, None] = {}
        for c in out.eligibility_countries:
            for code in geo.find_countries(c) or geo.codes_in_location_field(c.upper()):
                codes.setdefault(code, None)
        draft.eligibility.countries = list(codes)
    if out.timezone:
        draft.job_tz = geo.parse_tz(out.timezone) or draft.job_tz
    prov["_llm"] = Provenance(source_span=key, stated=False, confidence=1.0, method="llm")
    draft.provenance = prov
    draft.method = "llm"
    return draft


def cache_entries_for(session: Session, keys: list[str]) -> list[LlmCache]:
    return [e for k in keys if (e := session.get(LlmCache, k)) is not None]


__all__ = ["LlmError", "llm_extract_cv", "llm_extract_job", "call_structured", "cache_key", "json"]
