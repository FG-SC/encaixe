"""GET /api/rules: the "Como o Encaixe decide" page, generated from app/config.py."""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter

from app.config import rules_as_dict, rules_hash
from app.rules import render_html, render_markdown

router = APIRouter(prefix="/api", tags=["rules"])


@lru_cache(maxsize=1)
def _page(hash_: str) -> dict:
    md = render_markdown()
    return {"hash": hash_, "markdown": md, "html": render_html(md)}


@router.get("/rules")
def rules_page() -> dict:
    page = _page(rules_hash())
    return {**page, "rules": rules_as_dict()}
