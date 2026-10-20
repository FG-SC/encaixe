"""Everything computed for one (candidate, job) pair: requirements, hard filters, raw criteria, good fit."""

from __future__ import annotations

from dataclasses import dataclass, field

from app import clock
from app import geo as geo_mod
from app import taxonomy as tax_mod
from app.config import RULES
from app.ranking.features import CandidateFeatures, JobFeatures, job_comp_max_for

# --------------------------------------------------------------------------- requirements


@dataclass
class SkillStatus:
    skill: str
    status: str  # proven_recent | proven | partial | listed | listed_partial | missing
    credit: float  # proven credit (1, 0.5, 0)


@dataclass
class RequirementEval:
    must_total: int
    must_credit: float
    recent_credit: float
    listed_credit: float
    nice_total: int
    nice_credit: float
    must_status: list[SkillStatus] = field(default_factory=list)
    nice_status: list[SkillStatus] = field(default_factory=list)
    languages: list[tuple[str, int, bool]] = field(default_factory=list)  # (code, required rank, met)

    @property
    def known(self) -> bool:
        return self.must_total > 0

    @property
    def key(self) -> tuple[float, float, float, float] | None:
        """Lexicographic key (spec 7.2): proven, proven recently, only listed, nice proven."""
        if not self.known:
            return None
        nice = self.nice_credit / self.nice_total if self.nice_total else 0.0
        t = self.must_total
        return (self.must_credit / t, self.recent_credit / t, self.listed_credit / t, nice)

    @property
    def must_share(self) -> float:
        return self.must_credit / self.must_total if self.must_total else 0.0


def _neighbors(have: frozenset[str]) -> frozenset[str]:
    """Skills one parent/child step away from ``have`` (they earn partial credit)."""
    tax = tax_mod.load()
    out: set[str] = set()
    for h in have:
        parent = tax.parent(h)
        if parent:
            out.add(parent)
        out.update(tax.children(h))
    return frozenset(out - have)


_NEIGHBOR_CACHE: dict[frozenset[str], frozenset[str]] = {}


def _credit_sets(have: set[str]) -> tuple[frozenset[str], frozenset[str]]:
    key = frozenset(have)
    nb = _NEIGHBOR_CACHE.get(key)
    if nb is None:
        if len(_NEIGHBOR_CACHE) > 4096:
            _NEIGHBOR_CACHE.clear()
        nb = _NEIGHBOR_CACHE[key] = _neighbors(key)
    return key, nb


def _credit(skill: str, sets: tuple[frozenset[str], frozenset[str]]) -> float:
    full, partial = sets
    if skill in full:
        return 1.0
    if skill in partial:
        return RULES.requirements.partial_credit
    return 0.0


def evaluate_requirements(c: CandidateFeatures, j: JobFeatures) -> RequirementEval:
    proven = _credit_sets(c.proven)
    recent_s = _credit_sets(c.proven_recent)
    claimed = _credit_sets(c.proven | c.listed)
    must_status: list[SkillStatus] = []
    must_credit = recent_credit = listed_credit = 0.0
    for s in j.must:
        p = _credit(s, proven)
        r = _credit(s, recent_s)
        listed_only = max(0.0, _credit(s, claimed) - p)
        must_credit += p
        recent_credit += r
        listed_credit += listed_only
        if p == 1.0:
            status = "proven_recent" if r == 1.0 else "proven"
        elif p > 0:
            status = "partial"
        elif listed_only == 1.0:
            status = "listed"
        elif listed_only > 0:
            status = "listed_partial"
        else:
            status = "missing"
        must_status.append(SkillStatus(s, status, p))
    langs: list[tuple[str, int, bool]] = []
    for code, rank in j.languages:
        have = c.languages.get(code)
        met = have is not None and (rank == 0 or have >= rank)
        langs.append((code, rank, met))
        if met:
            must_credit += 1.0
            recent_credit += 1.0
    nice_status = [
        SkillStatus(s, "proven" if _credit(s, proven) == 1 else "missing", _credit(s, proven)) for s in j.nice
    ]
    return RequirementEval(
        must_total=len(j.must) + len(j.languages),
        must_credit=must_credit,
        recent_credit=recent_credit,
        listed_credit=listed_credit,
        nice_total=len(j.nice),
        nice_credit=sum(x.credit for x in nice_status),
        must_status=must_status,
        nice_status=nice_status,
        languages=langs,
    )


# --------------------------------------------------------------------------- filters


@dataclass
class FilterReason:
    code: str
    value: object = None
    threshold: object = None
    detail: dict = field(default_factory=dict)


def distance_km(c: CandidateFeatures, j: JobFeatures) -> float | None:
    geo = geo_mod.load()
    a, b = geo.get_city(c.city_id), geo.get_city(j.city_id)
    if a is None or b is None:
        return None
    return 0.0 if a.id == b.id else geo_mod.haversine_km(a, b)


def hard_filters(c: CandidateFeatures, j: JobFeatures, req: RequirementEval, side: str) -> list[FilterReason]:
    """Every failing hard filter (spec 7.1), in RULES.filters.codes order."""
    out: list[FilterReason] = []
    if side == "candidate" and j.status != "open":
        out.append(FilterReason("closed", j.status))
    if side == "recruiter" and not c.visible:
        out.append(FilterReason("not_visible"))
    wants = c.wants
    if j.arrangement and j.arrangement not in wants.arrangements:
        out.append(
            FilterReason(
                "arrangement_not_accepted", j.arrangement, list(wants.arrangements), {"arrangement": j.arrangement}
            )
        )
    elif j.arrangement != "remote" and wants.max_distance_km is not None:
        # An unknown arrangement counts as onsite for the distance: a job that does not say it is remote is
        # rarely remote. Without a known city, a job in another country is beyond any distance limit.
        d = distance_km(c, j)
        if d is not None and d > wants.max_distance_km:
            out.append(
                FilterReason(
                    "beyond_distance",
                    round(d),
                    wants.max_distance_km,
                    {"distance_km": d, "max_distance_km": wants.max_distance_km, "arrangement": j.arrangement},
                )
            )
        elif d is None and j.country and c.country and j.country != c.country:
            out.append(
                FilterReason(
                    "beyond_distance",
                    j.country,
                    c.country,
                    {
                        "other_country": j.country,
                        "max_distance_km": wants.max_distance_km,
                        "arrangement": j.arrangement,
                    },
                )
            )
    if j.eligibility and c.country and c.country not in j.eligibility:
        out.append(FilterReason("country_eligibility", c.country, j.eligibility, {"countries": j.eligibility}))
    if wants.comp_min:
        job_max, _ = job_comp_max_for(j, wants)
        ratio = RULES.filters.comp_min_ratio
        if job_max is not None and job_max < ratio * wants.comp_min:
            out.append(
                FilterReason(
                    "salary_below_min",
                    job_max,
                    ratio * wants.comp_min,
                    {
                        "job_comp": job_max,
                        "candidate_comp": wants.comp_min,
                        "ratio": ratio,
                        "currency": wants.currency,
                        "period": wants.period,
                    },
                )
            )
    if j.level is not None and c.level is not None:
        gap = abs(j.level - c.level)
        if gap >= RULES.filters.seniority_gap_exclude:
            out.append(
                FilterReason(
                    "seniority_gap",
                    gap,
                    RULES.filters.seniority_gap_exclude,
                    {
                        "job_level": j.level,
                        "candidate_level": c.level,
                        "gap": gap,
                        "threshold": RULES.filters.seniority_gap_exclude,
                    },
                )
            )
    if out_of_area(c, j, req):
        out.append(
            FilterReason(
                "out_of_area",
                sorted(c.domains),
                j.domains,
                {"job_domains": j.domains, "candidate_domains": sorted(c.domains)},
            )
        )
    return out


def out_of_area(c: CandidateFeatures, j: JobFeatures, req: RequirementEval) -> bool:
    """No proof of any (non-transversal) must requirement AND no taxonomy domain in common (spec 7.1)."""
    if not j.must_nontransversal or not j.domains:
        return False
    proves_something = any(st.credit > 0 for st in req.must_status if st.skill in j.must_nontransversal)
    return not proves_something and not (c.domains & set(j.domains))


# --------------------------------------------------------------------------- criteria


@dataclass
class Raw:
    """A raw criterion value. ``value`` None = unknown; ``na`` = not applicable (both neutral)."""

    value: object = None
    na: bool = False
    flags: tuple[str, ...] = ()
    info: dict = field(default_factory=dict)


def raw_criteria(
    c: CandidateFeatures, j: JobFeatures, req: RequirementEval, sem: float, title: float
) -> dict[str, Raw]:
    out: dict[str, Raw] = {
        "requirements": Raw(req.key),
        "semantic": Raw(float(sem)),
        "title": Raw(float(title)),
        "seniority": Raw(
            abs(j.level - c.level) if j.level is not None and c.level is not None else None,
            info={"job_level": j.level, "candidate_level": c.level},
        ),
    }
    wants = c.wants
    job_max, fx = job_comp_max_for(j, wants)
    if job_max is not None and wants.comp_min:
        out["salary"] = Raw(
            (job_max - wants.comp_min) / wants.comp_min,
            flags=("fx",) if fx else (),
            info={
                "job_comp": job_max,
                "candidate_comp": wants.comp_min,
                "currency": wants.currency,
                "period": wants.period,
            },
        )
    else:
        out["salary"] = Raw(
            None,
            flags=("salary_unknown",) if job_max is None else (),
            info={
                "job_comp": job_max,
                "candidate_comp": wants.comp_min,
                "currency": wants.currency,
                "period": wants.period,
            },
        )
    if j.arrangement == "remote" and "remote" in wants.arrangements:
        out["distance"] = Raw(0.0, info={"remote": True})
    else:
        d = distance_km(c, j)
        out["distance"] = Raw(d, info={"remote": False, "km": d})
    if j.arrangement == "remote":
        if c.tz and j.tz:
            hours = geo_mod.tz_overlap_hours(
                c.tz, j.tz, clock.today(), RULES.workday.start_hour, RULES.workday.end_hour
            )
            out["timezone"] = Raw(hours, info={"job_tz": j.tz})
        else:
            out["timezone"] = Raw(None, info={"job_tz": j.tz})
    else:
        out["timezone"] = Raw(None, na=True)
    return out


# --------------------------------------------------------------------------- good fit


@dataclass
class GoodFit:
    is_good_fit: bool
    evaluable: bool
    must_credit: float
    must_total: int
    seniority_gap: int | None


def good_fit(c: CandidateFeatures, j: JobFeatures, req: RequirementEval, passes_filters: bool) -> GoodFit:
    gap = abs(j.level - c.level) if j.level is not None and c.level is not None else None
    evaluable = req.must_total > 0
    ok = (
        passes_filters
        and evaluable
        and req.must_share >= RULES.good_fit.must_share - 1e-9
        and (gap is None or gap <= RULES.good_fit.max_seniority_gap)
    )
    return GoodFit(ok, evaluable, req.must_credit, req.must_total, gap)
