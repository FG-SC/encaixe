"""Company identity: normalized name, exact match, aliases. No size, revenue or prestige score."""

from __future__ import annotations

import re

from sqlmodel import Session, select

from app.models import Company
from app.textnorm import fold, squash

LEGAL_SUFFIXES = (
    "inc",
    "incorporated",
    "llc",
    "l.l.c",
    "ltd",
    "limited",
    "ltda",
    "s.a",
    "s/a",
    "sa",
    "me",
    "epp",
    "eireli",
    "gmbh",
    "ag",
    "bv",
    "plc",
    "corp",
    "corporation",
    "co",
    "company",
    "sas",
    "srl",
    "spa",
    "oy",
    "ab",
    "pty",
)
_SUFFIX_RE = re.compile(
    r"(?:[\s,.-]+(?:" + "|".join(re.escape(s) for s in sorted(LEGAL_SUFFIXES, key=len, reverse=True)) + r")\.?)+\s*$"
)


def normalize(name: str | None) -> str:
    """Lowercase, accent-free, no punctuation, no legal suffixes: "Google LLC" -> "google"."""
    if not name:
        return ""
    s = fold(name).strip()
    for _ in range(3):  # "Acme Brasil Ltda. - ME"
        s2 = _SUFFIX_RE.sub("", s)
        if s2 == s:
            break
        s = s2
    s = re.sub(r"[^\w\s&+]", " ", s)
    return squash(s)


def get_or_create_company(session: Session, name: str | None) -> Company | None:
    """Exact match on the normalized name; new spellings are kept as aliases."""
    key = normalize(name)
    if not key or name is None:
        return None
    company = session.exec(select(Company).where(Company.name_normalized == key)).first()
    clean = squash(name)
    if company is None:
        company = Company(name=clean, name_normalized=key, aliases=[])
        session.add(company)
        session.flush()
    elif clean != company.name and clean not in company.aliases:
        company.aliases = [*company.aliases, clean]
        session.add(company)
    return company
