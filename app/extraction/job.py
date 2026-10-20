"""Heuristic job extraction: raw posting → canonical ``JobDraft`` with provenance, no LLM."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app import geo as geo_mod
from app import taxonomy as tax_mod
from app.config import RULES
from app.extraction.salary import extract_salary
from app.extraction.text import Section, first_sentences, html_to_text, split_sections, strip_institutional
from app.schemas import Eligibility, JobDraft, LanguageLevel, Offers, Provenance, Requires
from app.textnorm import excerpt, fold

MAX_MUST_SKILLS = 15
MAX_NICE_SKILLS = 15

_REMOTE = re.compile(
    r"\b(?:remote|remoto|remota|home[ -]?office|100% remot[oa]|trabalho remoto|teletrabalho|work from home|"
    r"wfh|anywhere|remote-first|fully remote|distributed team)\b",
    re.IGNORECASE,
)
_NOT_REMOTE = re.compile(
    r"\b(?:not (?:a )?remote|no remote|não (?:é )?remot[oa]|sem home office|não aceitamos remoto)\b", re.IGNORECASE
)
_HYBRID = re.compile(r"\b(?:h[ií]brid[oa]|hybrid|flex[ií]vel \(h[ií]brido\))\b", re.IGNORECASE)
_ONSITE = re.compile(
    r"\b(?:presencial|on[- ]?site|in[- ]office|no escrit[oó]rio|in person|in-person|100% presencial)\b",
    re.IGNORECASE,
)
_REGIME = [
    ("internship", re.compile(r"\b(?:est[aá]gio|estagi[aá]ri[oa]|internship|intern)\b", re.IGNORECASE)),
    ("clt", re.compile(r"\bCLT\b")),
    ("pj", re.compile(r"\b(?:PJ|pessoa jur[ií]dica)\b")),
    (
        "contractor",
        re.compile(r"\b(?:contractor|freelance|freelancer|contrato tempor[aá]rio|B2B contract)\b", re.IGNORECASE),
    ),
]
_YEARS = re.compile(
    r"(?:(?:m[ií]nimo de|pelo menos|at least|minimum(?: of)?|mais de|over|\+)\s*)?(?P<n>\d{1,2})\s*\+?\s*"
    r"(?:\+|or more|ou mais)?\s*(?:years?|anos?|yrs?)\b(?P<ctx>.{0,40})",
    re.IGNORECASE,
)
_EXPERIENCE_CTX = re.compile(r"experi|atua|working|work|professional|na [aá]rea|in the field", re.IGNORECASE)
_LEVEL_IN_TEXT = re.compile(
    r"\b(?:n[ií]vel|level|senioridade|seniority)\s*:?\s*(?P<w>est[aá]gio|j[uú]nior|jr|pleno|pl|s[eê]nior|sr|"
    r"staff|principal|mid)\b|\b(?P<w2>junior|mid|senior|entry)[- ]level\b",
    re.IGNORECASE,
)


@dataclass
class RawPosting:
    """What a connector (or the seed, or a recruiter) hands to the extractor."""

    title: str
    description: str  # HTML or text
    company: str | None = None
    location_text: str | None = None
    source: str = "seed"
    source_id: str | None = None
    url: str | None = None
    labels: list[str] = field(default_factory=list)
    structured: dict = field(default_factory=dict)  # stated fields from the source (salaryRange, workplaceType…)


def _prov(
    text: str, span: tuple[int, int] | None, stated: bool, confidence: float, method: str = "heuristic"
) -> Provenance:
    return Provenance(
        source_span=excerpt(text, *span) if span else None, stated=stated, confidence=confidence, method=method
    )


def _skills_in(sections: list[Section], text: str, kinds: set[str]) -> list[tuple[str, tuple[int, int]]]:
    tax = tax_mod.load()
    out: list[tuple[str, tuple[int, int]]] = []
    for s in sections:
        if s.kind not in kinds:
            continue
        for m in tax.find_skills(s.body(text)):
            out.append((m.skill_id, (s.start + m.start, s.start + m.end)))
    return out


def _dedupe(items: list[tuple[str, tuple[int, int]]], limit: int) -> list[tuple[str, tuple[int, int]]]:
    seen: dict[str, tuple[int, int]] = {}
    for sid, span in items:
        seen.setdefault(sid, span)
    return list(seen.items())[:limit]


def _arrangement(title: str, location: str, body: str) -> tuple[str | None, str, bool]:
    """(arrangement, where it was found, stated)."""
    for where, text in (("location", location), ("title", title), ("body", body)):
        if not text:
            continue
        if _NOT_REMOTE.search(text):
            return "onsite", where, True
        if _HYBRID.search(text):
            return "hybrid", where, True
        if _REMOTE.search(text):
            return "remote", where, True
        if _ONSITE.search(text):
            return "onsite", where, True
    return None, "", False


def extract_job(raw: RawPosting) -> JobDraft:
    tax = tax_mod.load()
    geo = geo_mod.load()
    text = html_to_text(raw.description)
    sections = split_sections(text)
    clean = strip_institutional(text, sections)
    prov: dict[str, Provenance] = {}
    warnings: list[str] = []

    # ---- skills: title + must sections → must; nice sections → nice; without sections, everything → must
    title_skills = [(m.skill_id, (m.start, m.end)) for m in tax.find_skills(raw.title)]
    must_sections = [s for s in sections if s.kind == "must"]
    nice = _skills_in(sections, text, {"nice"})
    if must_sections:
        must = _skills_in(sections, text, {"must"})
        rest = _skills_in(sections, text, {"responsibilities", "intro", "location", "salary"})
        nice = nice + rest
        must_stated = True
    else:
        must = _skills_in(sections, text, {"must", "responsibilities", "intro", "location", "salary"})
        must_stated = False
        if must:
            warnings.append("sem seção de requisitos: todas as skills do texto foram tratadas como obrigatórias")
    if must_sections:
        # The requirements list is authoritative; skills only in the title are desirable.
        must_d = _dedupe(must, MAX_MUST_SKILLS)
        nice = [(s, sp) for s, sp in title_skills] + nice
    else:
        must_d = _dedupe([*((s, None) for s, _ in title_skills), *must], MAX_MUST_SKILLS)  # type: ignore[misc]
    must_ids = [s for s, _ in must_d]
    nice_d = [(s, sp) for s, sp in _dedupe(nice, MAX_NICE_SKILLS + len(must_ids)) if s not in must_ids]
    nice_d = nice_d[:MAX_NICE_SKILLS]
    spans = dict(must) | dict(nice)
    for sid in must_ids:
        sp = spans.get(sid)
        prov[f"requires.skills_must.{sid}"] = (
            _prov(text, sp, must_stated, 0.8 if must_stated else 0.55)
            if sp
            else Provenance(source_span=raw.title, stated=True, confidence=0.8, method="heuristic")
        )
    for sid, sp in nice_d:
        prov[f"requires.skills_nice.{sid}"] = _prov(text, sp, True, 0.6)

    # ---- languages (must when in a must section, in the title, or without sections)
    languages: list[LanguageLevel] = []
    lang_kinds = {"must"} if must_sections else {"must", "intro", "responsibilities"}
    for s in sections:
        if s.kind not in lang_kinds:
            continue
        for lm in tax.find_languages(s.body(text)):
            if lm.language not in {lang.language for lang in languages}:
                languages.append(LanguageLevel(language=lm.language, level=lm.level))
                prov[f"requires.languages.{lm.language}"] = _prov(
                    text, (s.start + lm.start, s.start + lm.end), True, 0.7
                )

    # ---- seniority: title first, then explicit text, then years
    years_min = None
    for m in _YEARS.finditer(clean):
        if _EXPERIENCE_CTX.search(m.group("ctx")) or _EXPERIENCE_CTX.search(clean[max(0, m.start() - 30) : m.start()]):
            n = int(m.group("n"))
            if 0 < n <= 25:
                years_min = float(n)
                prov["requires.years_min"] = _prov(clean, (m.start(), m.end()), True, 0.7)
                break
    level = None
    sm = tax.seniority_from_title(raw.title)
    if sm:
        level = sm.level
        prov["requires.seniority"] = Provenance(
            source_span=raw.title,
            stated=sm.strength == "explicit",
            confidence=0.9 if sm.strength == "explicit" else 0.6,
        )
    else:
        lm2 = _LEVEL_IN_TEXT.search(clean)
        if lm2:
            word = lm2.group("w") or lm2.group("w2") or ""
            sm2 = tax.seniority_from_title(word)
            if sm2:
                level = sm2.level
                prov["requires.seniority"] = _prov(clean, (lm2.start(), lm2.end()), True, 0.7)
        if level is None and years_min is not None:
            for lo, hi, lv in RULES.seniority.years_fallback:
                if lo <= years_min < hi:
                    level = lv
                    prov["requires.seniority"] = Provenance(
                        source_span=f"{years_min:g}+ anos de experiência", stated=False, confidence=0.4
                    )
                    break

    # ---- arrangement, location, eligibility, timezone
    location = raw.location_text or ""
    arrangement, where, stated = _arrangement(raw.title, location, clean)
    if raw.structured.get("arrangement"):
        arrangement, stated, where = raw.structured["arrangement"], True, "source"
    if arrangement:
        prov["offers.arrangement"] = Provenance(source_span=where, stated=stated, confidence=0.75)
    city = geo.find_city(location) or geo.find_city(raw.title)
    if city is None:
        for s in sections:
            if s.kind in {"location", "intro"}:
                cm = geo.find_city(s.body(text))
                if cm:
                    city = geo_mod.CityMatch(cm.city_id, s.start + cm.start, s.start + cm.end, cm.qualified)
                    break
    city_id = city.city_id if city else None
    if city_id:
        prov["city_id"] = Provenance(source_span=location or raw.title, stated=True, confidence=0.8)
    country = geo.location_country(location) or (geo.country_of(city_id) if city_id else None)
    eligibility = geo.find_eligibility(location + "\n" + clean)
    if eligibility:
        prov["eligibility.countries"] = Provenance(source_span=location or None, stated=True, confidence=0.7)
    job_tz = geo.parse_tz(location + "\n" + clean)
    if job_tz is None and arrangement == "remote" and city_id:
        job_tz = geo.cities[city_id].tz
        prov["job_tz"] = Provenance(source_span=location, stated=False, confidence=0.4)
    elif job_tz:
        prov["job_tz"] = Provenance(source_span=None, stated=True, confidence=0.7)

    # ---- salary and regime
    offers = Offers(arrangement=arrangement)
    structured_salary = raw.structured.get("salary")
    if structured_salary:
        offers.comp_min = structured_salary.get("min")
        offers.comp_max = structured_salary.get("max")
        offers.currency = structured_salary.get("currency")
        offers.period = structured_salary.get("period")
        prov["offers.comp_max"] = Provenance(source_span="campo estruturado da fonte", stated=True, confidence=0.95)
    else:
        sal = extract_salary(text)
        if sal:
            offers.comp_min, offers.comp_max, offers.currency, offers.period = (
                sal.comp_min,
                sal.comp_max,
                sal.currency,
                sal.period,
            )
            prov["offers.comp_max"] = _prov(text, sal.span, True, 0.75 if sal.period_stated else 0.55)
            if not sal.period_stated:
                prov["offers.period"] = Provenance(source_span=None, stated=False, confidence=0.4)
    for regime, rx in _REGIME:
        hit = rx.search(raw.title + "\n" + location + "\n" + clean)
        if hit:
            offers.regime = regime  # type: ignore[assignment]
            prov["offers.regime"] = _prov(
                raw.title + "\n" + location + "\n" + clean, (hit.start(), hit.end()), True, 0.7
            )
            break
    if raw.structured.get("regime"):
        offers.regime = raw.structured["regime"]

    if raw.structured.get("seniority") is not None:
        level = raw.structured["seniority"]
        prov["requires.seniority"] = Provenance(source_span="label", stated=True, confidence=0.9, method="label")
    if raw.structured.get("city_id"):
        city_id = raw.structured["city_id"]
        country = geo.country_of(city_id) or country

    if not must_ids:
        warnings.append("nenhum requisito obrigatório reconhecido")

    return JobDraft(
        title=raw.title.strip(),
        company=raw.company,
        description_text=text,
        location_text=raw.location_text,
        city_id=city_id,
        country=country,
        requires=Requires(
            skills_must=must_ids,
            skills_nice=[s for s, _ in nice_d],
            seniority=level,
            years_min=years_min,
            languages=languages,
        ),
        offers=offers,
        eligibility=Eligibility(countries=eligibility),
        job_tz=job_tz,
        provenance=prov,
        warnings=warnings,
        method="heuristic",
    )


def role_summary(draft: JobDraft, max_words: int = 40) -> str:
    """First sentences of the role description without institutional text (for the embedding)."""
    text = draft.description_text
    sections = split_sections(text)
    preferred = [s for s in sections if s.kind == "responsibilities"] or [s for s in sections if s.kind == "intro"]
    body = "\n".join(s.body(text) for s in preferred) or strip_institutional(text, sections)
    body = strip_institutional(body)
    return first_sentences(body, max_words)


def normalized_title(title: str) -> str:
    return re.sub(r"\s+", " ", fold(title)).strip()
