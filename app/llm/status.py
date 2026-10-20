"""What the dev panel shows about the LLM: on / off / error (with the reason), model, usage, cache hits."""

from __future__ import annotations

from sqlmodel import Session

from app.config import get_settings
from app.models import Setting

STATUS_KEY = "llm_status"


def llm_status(session: Session) -> dict:
    settings = get_settings()
    row = session.get(Setting, STATUS_KEY)
    stored = dict(row.value or {}) if row else {}
    if not settings.llm_enabled:
        state, reason = "off", "sem GROQ_API_KEY: o extrator heurístico faz tudo"
    else:
        state = stored.get("state", "on")
        reason = stored.get("reason")
    return {
        "state": state,
        "reason": reason,
        "model": settings.llm_model,
        "requests_today": stored.get("requests_today", 0),
        "tokens_today": stored.get("tokens_today", 0),
        "cache_hits": stored.get("cache_hits", 0),
        "queue_size": stored.get("queue_size", 0),
        "day": stored.get("day"),
    }
