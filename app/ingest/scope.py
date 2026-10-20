"""Scope of the MVP (RULES.scope): a sample of one region — onsite/hybrid jobs there, remote jobs open to the country.

Decided per market posting at ingestion, after extraction:
- remote: in if its eligibility list includes the country, or, without a list, if it is not located in another country;
- onsite, hybrid or unknown arrangement: in if its city is in the region.
A posting out of scope is not stored; ingestion counts it per board (RunReport.details and a Setting row).
Recruiter-published jobs and the fictional seed do not go through this (the hard filters still apply to them).
"""

from __future__ import annotations

from dataclasses import dataclass

from app import geo as geo_mod
from app.config import RULES, Rules
from app.extraction.job import RawPosting
from app.schemas import JobDraft

CODES = ("remote_open", "remote_closed", "in_region", "outside_region")


@dataclass(frozen=True)
class ScopeDecision:
    in_scope: bool
    code: str  # one of CODES


def decide(raw: RawPosting, draft: JobDraft, rules: Rules = RULES) -> ScopeDecision:
    s = rules.scope
    if draft.offers.arrangement == "remote":
        eligibility = draft.eligibility.countries or []
        located = draft.country or raw.structured.get("country") or None
        ok = s.country in eligibility if eligibility else located in (None, s.country)
        return ScopeDecision(ok, "remote_open" if ok else "remote_closed")
    city = geo_mod.load().get_city(draft.city_id)
    ok = city is not None and city.country == s.country and city.state == s.region
    return ScopeDecision(ok, "in_region" if ok else "outside_region")
