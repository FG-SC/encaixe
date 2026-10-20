"""Job extraction for publishing: heuristic always; LLM when configured (platform jobs, spec 6)."""

from __future__ import annotations

import logging

from app.config import get_settings
from app.extraction.job import RawPosting, extract_job
from app.schemas import JobDraft

log = logging.getLogger(__name__)


def extract_job_for_publishing(raw: RawPosting, use_llm: bool = True) -> JobDraft:
    draft = extract_job(raw)
    if not use_llm or not get_settings().llm_enabled:
        return draft
    try:
        from app.llm.client import llm_extract_job

        return llm_extract_job(raw, draft)
    except Exception as exc:
        log.warning("LLM job extraction failed: %s", exc)
        draft.warnings.append(f"IA indisponível ({type(exc).__name__}); usamos o extrator heurístico")
        return draft
