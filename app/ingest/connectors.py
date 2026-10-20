"""Connectors: source JSON → RawPosting. Pure parsing (fetching lives in app.ingest.run).

Only the endpoints of spec 5.1; never an application endpoint. Contact data (e-mails, phones, profile links)
is stripped before anything is stored.
"""

from __future__ import annotations

import re

from app import geo as geo_mod
from app import taxonomy as tax_mod
from app.config import RULES
from app.extraction.job import RawPosting
from app.extraction.text import html_to_text
from app.textnorm import fold

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Area code is mandatory, so year ranges ("2019-2021") and amounts are never taken for phone numbers.
_PHONE = re.compile(r"(?<!\d)(?:\+?\d{2}\s?)?\(?\d{2}\)?[\s.-]?9?\d{4}[-.\s]?\d{4}(?!\d)")
_PROFILE = re.compile(r"https?://(?:www\.)?(?:linkedin\.com/in|wa\.me|api\.whatsapp\.com|t\.me)/\S+", re.IGNORECASE)


def strip_contacts(text: str) -> str:
    """Remove e-mails, phone numbers and personal profile links (LGPD minimisation)."""
    text = _EMAIL.sub("[e-mail removido]", text)
    text = _PROFILE.sub("[contato removido]", text)
    return _PHONE.sub("[telefone removido]", text)


# --------------------------------------------------------------------------- Greenhouse


def greenhouse_postings(token: str, payload: dict) -> list[RawPosting]:
    company = RULES.ingest.sources["greenhouse"].board_names.get(token, token)
    out = []
    for j in payload.get("jobs", []):
        out.append(
            RawPosting(
                title=(j.get("title") or "").strip(),
                description=strip_contacts(html_to_text(j.get("content") or "")),
                company=company,
                location_text=(j.get("location") or {}).get("name"),
                source="greenhouse",
                source_id=f"{token}:{j.get('id')}",
                url=j.get("absolute_url"),
            )
        )
    return [p for p in out if p.title]


# --------------------------------------------------------------------------- Lever

_LEVER_ARRANGEMENT = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite", "onsite": "onsite"}
_LEVER_INTERVAL = {
    "per-year-salary": "year",
    "per-month-salary": "month",
    "per-week-salary": "week",
    "per-day-wage": "day",
    "per-hour-wage": "hour",
}


def lever_postings(company_slug: str, payload: list) -> list[RawPosting]:
    company = RULES.ingest.sources["lever"].board_names.get(company_slug, company_slug)
    out = []
    for p in payload or []:
        parts = [p.get("descriptionPlain") or html_to_text(p.get("description") or "")]
        for lst in p.get("lists") or []:
            parts.append(f"{lst.get('text', '')}\n{html_to_text(lst.get('content') or '')}")
        parts.append(p.get("additionalPlain") or "")
        structured: dict = {}
        arrangement = _LEVER_ARRANGEMENT.get((p.get("workplaceType") or "").lower())
        if arrangement:
            structured["arrangement"] = arrangement
        sr = p.get("salaryRange") or {}
        if sr.get("min") is not None or sr.get("max") is not None:
            structured["salary"] = {
                "min": sr.get("min"),
                "max": sr.get("max"),
                "currency": sr.get("currency"),
                "period": _LEVER_INTERVAL.get(sr.get("interval") or "", "year"),
            }
        cats = p.get("categories") or {}
        out.append(
            RawPosting(
                title=(p.get("text") or "").strip(),
                description=strip_contacts("\n\n".join(x for x in parts if x)),
                company=company,
                location_text=cats.get("location"),
                source="lever",
                source_id=f"{company_slug}:{p.get('id')}",
                url=p.get("hostedUrl"),
                structured=structured,
            )
        )
    return [p for p in out if p.title]


# --------------------------------------------------------------------------- GitHub issues

_REGIME_LABELS = {
    "clt": "clt",
    "pj": "pj",
    "estagio": "internship",
    "freela": "contractor",
    "freelancer": "contractor",
    "freelance": "contractor",
}
_ARRANGEMENT_LABELS = {
    "remoto": "remote",
    "remote": "remote",
    "hibrido": "hybrid",
    "hybrid": "hybrid",
    "presencial": "onsite",
    "on-site": "onsite",
}
_TITLE_COMPANY = [
    re.compile(r"^\s*\[(?P<c>[^\]]{2,60})\]"),
    re.compile(r"\s(?:na|no|at|@)\s+(?P<c>[A-ZÀ-Ý][\w&.\- ]{1,50})\s*$"),
    re.compile(r"\s[-–|]\s+(?P<c>[A-ZÀ-Ý][\w&.\- ]{1,50})\s*$"),
]


def github_labels_to_fields(labels: list[str]) -> dict:
    """Labels become stated fields (spec 5.1): seniority, regime, arrangement, city."""
    tax = tax_mod.load()
    geo = geo_mod.load()
    out: dict = {}
    for label in labels:
        key = fold(label).strip()
        if key in _REGIME_LABELS:
            out.setdefault("regime", _REGIME_LABELS[key])
            if key == "estagio":
                out.setdefault("seniority", 1)
            continue
        if key in _ARRANGEMENT_LABELS:
            out.setdefault("arrangement", _ARRANGEMENT_LABELS[key])
            continue
        sm = tax.seniority_from_title(label)
        if sm is not None and sm.strength == "explicit":
            out["seniority"] = min(out.get("seniority", 9), sm.level)
            continue
        city = geo.find_city(label)
        if city is not None and city.start == 0:
            out.setdefault("city_id", city.city_id)
    return out


def github_company(title: str) -> str | None:
    for rx in _TITLE_COMPANY:
        m = rx.search(title)
        if m:
            c = m.group("c").strip()
            if fold(c) not in _ARRANGEMENT_LABELS and not tax_mod.load().seniority_from_title(c):
                return c
    return None


def github_postings(repo: str, payload: list) -> list[RawPosting]:
    out = []
    for issue in payload or []:
        if "pull_request" in issue:  # the issues endpoint also returns PRs
            continue
        labels = [lb.get("name", "") for lb in issue.get("labels") or [] if isinstance(lb, dict)]
        fields = github_labels_to_fields(labels)
        title = (issue.get("title") or "").strip()
        location = None
        if fields.get("arrangement") == "remote":
            location = "Remoto (Brasil)"
        elif fields.get("city_id"):
            location = geo_mod.load().cities[fields["city_id"]].name
        out.append(
            RawPosting(
                title=re.sub(r"^\s*\[[^\]]*\]\s*", "", title) or title,
                description=strip_contacts(issue.get("body") or ""),
                company=github_company(title),
                location_text=location,
                source="github",
                source_id=f"{repo}#{issue.get('number')}",
                url=issue.get("html_url"),
                labels=labels,
                structured={k: v for k, v in fields.items() if k in ("arrangement", "regime", "seniority", "city_id")},
            )
        )
    return [p for p in out if p.title]
