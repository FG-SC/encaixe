"""CV extraction at onboarding: heuristic always; the LLM only with consent and a key (spec 6)."""

from __future__ import annotations

import logging

from app.config import get_settings
from app.extraction.cv import extract_cv
from app.schemas import CandidateDraft

log = logging.getLogger(__name__)


def extract_cv_for_onboarding(text: str, llm_consent: bool) -> CandidateDraft:
    draft = extract_cv(text)
    if not llm_consent:
        draft.llm_status = "off: sem autorização para usar IA"
        return draft
    if not get_settings().llm_enabled:
        draft.llm_status = "off: IA não configurada (sem GROQ_API_KEY); usamos o extrator heurístico"
        return draft
    try:
        from app.llm.client import llm_extract_cv

        return llm_extract_cv(text, draft)
    except Exception as exc:  # never block onboarding: fall back and say so
        log.warning("LLM CV extraction failed: %s", exc)
        draft.llm_status = f"fallback: {type(exc).__name__}; usamos o extrator heurístico"
        return draft
