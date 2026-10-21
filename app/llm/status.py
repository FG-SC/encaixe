"""LLM status and daily usage in Setting["llm_status"]: the dev panel reads it; failures are never silent."""

from __future__ import annotations

import threading

from sqlmodel import Session

from app import clock
from app.config import get_settings
from app.models import Setting

STATUS_KEY = "llm_status"
_lock = threading.Lock()


def _today() -> str:
    return clock.today().isoformat()


def _load(session: Session) -> dict:
    row = session.get(Setting, STATUS_KEY)
    data = dict(row.value or {}) if row else {}
    if data.get("day") != _today():
        data.update(day=_today(), requests_today=0, tokens_today=0, background_today=0)
    return data


def update_status(**changes: object) -> dict:
    """Apply changes (``+=`` for counters ending in _inc) in its own short transaction."""
    from app.db import session_scope

    with _lock, session_scope() as session:
        data = _load(session)
        for key, value in changes.items():
            if key.endswith("_inc"):
                base = key[: -len("_inc")]
                data[base] = int(data.get(base, 0)) + int(value)  # type: ignore[arg-type]
            else:
                data[key] = value
        row = session.get(Setting, STATUS_KEY)
        if row is None:
            session.add(Setting(key=STATUS_KEY, value=data))
        else:
            row.value = data
            session.add(row)
        return data


def llm_status(session: Session) -> dict:
    settings = get_settings()
    stored = _load(session)
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
