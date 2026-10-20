"""Heuristic CV extraction: pasted text (or PDF text) → ``CandidateDraft`` with provenance, no LLM.

Experiences are the evidence: a skill mentioned inside a dated experience block is *used* there; a skill
only in the skills section (or the summary) is *listed*. Dated projects count as experiences.
"""

from __future__ import annotations

import re
from datetime import date

from app import geo as geo_mod
from app import taxonomy as tax_mod
from app.extraction.dates import DateRange, find_date_ranges
from app.schemas import CandidateDraft, EducationIn, ExperienceIn, LanguageLevel, Provenance
from app.textnorm import excerpt, fold, squash

_SECTION_HEADINGS: list[tuple[str, list[str]]] = [
    (
        "experience",
        [
            "experiencia profissional",
            "experiencias profissionais",
            "experiencia",
            "experiencias",
            "historico profissional",
            "trajetoria profissional",
            "professional experience",
            "work experience",
            "experience",
            "employment history",
            "career",
        ],
    ),
    ("projects", ["projetos", "projetos relevantes", "projects", "personal projects", "portfolio"]),
    ("education", ["formacao academica", "formacao", "educacao", "escolaridade", "education", "academic background"]),
    (
        "skills",
        [
            "habilidades",
            "competencias",
            "competencias tecnicas",
            "conhecimentos",
            "conhecimentos tecnicos",
            "ferramentas",
            "tecnologias",
            "skills",
            "technical skills",
            "hard skills",
            "tools",
            "stack",
            "habilidades tecnicas",
            "tech stack",
        ],
    ),
    ("languages", ["idiomas", "linguas", "languages"]),
    (
        "summary",
        [
            "resumo",
            "resumo profissional",
            "sobre mim",
            "sobre",
            "perfil",
            "perfil profissional",
            "objetivo",
            "summary",
            "about me",
            "profile",
            "objective",
            "professional summary",
        ],
    ),
    (
        "courses",
        [
            "cursos",
            "certificacoes",
            "certificados",
            "cursos e certificacoes",
            "certifications",
            "courses",
            "licenses & certifications",
        ],
    ),
    (
        "other",
        [
            "voluntariado",
            "volunteering",
            "interesses",
            "interests",
            "premios",
            "awards",
            "publicacoes",
            "publications",
            "referencias",
            "references",
        ],
    ),
]
_HEADING_LOOKUP = sorted(((p, k) for k, ps in _SECTION_HEADINGS for p in ps), key=lambda x: -len(x[0]))

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?:\+?55\s?)?(?:\(?\d{2}\)?\s?)?9?\d{4}[-\s]?\d{4}")
_URL = re.compile(r"(?:https?://)?(?:www\.)?(?:linkedin\.com/in/|github\.com/)[\w\-/]+", re.IGNORECASE)
_ROLE_NOUNS = re.compile(
    r"\b(?:analista|analyst|engenheir[oa]|engineer|desenvolvedor[a]?|developer|dev|cientista|scientist|"
    r"estagi[aá]ri[oa]|intern|trainee|assistente|assistant|auxiliar|coordenador[a]?|coordinator|gerente|manager|"
    r"consultor[a]?|consultant|especialista|specialist|arquitet[oa]|architect|l[ií]der|lead|head|diretor[a]?|"
    r"director|pesquisador[a]?|researcher|professor[a]?|t[eé]cnic[oa]|technician|administrador[a]?|"
    r"programador[a]?|programmer|designer|product owner|scrum master|bolsista|monitor[a]?|vendedor[a]?|"
    r"executiv[oa]|representante|supervisor[a]?|operador[a]?|projeto|project)\b",
    re.IGNORECASE,
)
_SPLIT = re.compile(r"\s+(?:—|–|-|\||@|at|na|no|em)\s+|\s*[|•·]\s*")
_DEGREE = re.compile(
    r"\b(?P<d>bacharelado|bacharel|licenciatura|tecn[oó]logo|gradua[cç][aã]o|mestrado|doutorado|mba|"
    r"p[oó]s[- ]gradua[cç][aã]o|especializa[cç][aã]o|t[eé]cnico|bachelor(?:'s)?|bsc|b\.sc|master(?:'s)?|msc|"
    r"m\.sc|ph\.?d|doctorate|associate degree|ensino m[eé]dio)\b(?:\s+(?:em|in|de|of)\s+(?P<f>[^,|\n—–()-]+))?",
    re.IGNORECASE,
)
_IN_PROGRESS = re.compile(r"cursando|em andamento|in progress|previs[aã]o|expected|incompleto|em curso", re.IGNORECASE)
_BULLET = re.compile(r"^\s*(?:[-•·*▪◦]|\d+[.)])\s*")
_OUTCOME = re.compile(r"\d+\s?%|\d+x\b|redu[zç]|aument|reduc|increas|improv|economi|sav|cresc|grew", re.IGNORECASE)
_PT_STOPWORDS = re.compile(r"\b(?:de|da|do|em|com|para|que|uma|experi[eê]ncia|atual)\b", re.IGNORECASE)


def _heading(line: str) -> str | None:
    stripped = re.sub(r"^[\s#*•\-–—=_]+|[\s:：*_=\-–—]+$", "", line).strip()
    if not stripped or len(stripped) > 45:
        return None
    key = fold(stripped)
    for phrase, kind in _HEADING_LOOKUP:
        if key == phrase or (key.startswith(phrase + " ") and len(key.split()) <= len(phrase.split()) + 2):
            return kind
    return None


def _sections(text: str) -> list[tuple[str, int, int]]:
    """(kind, start, end) in order; text before the first heading is "header"."""
    out: list[tuple[str, int, int]] = []
    kind, start, pos = "header", 0, 0
    for line in text.splitlines(keepends=True):
        h = _heading(line)
        if h is not None:
            out.append((kind, start, pos))
            kind, start = h, pos + len(line)
        pos += len(line)
    out.append((kind, start, len(text)))
    return [s for s in out if s[2] > s[1]]


def _split_role_company(header: str) -> tuple[str, str | None]:
    """ "Analista de Dados Jr — Lumen Tech" → (role, company). The part with a role noun is the role."""
    clean = squash(re.sub(r"\(.*?\)", " ", header))
    parts = [p.strip(" ,;:") for p in _SPLIT.split(clean) if p and p.strip(" ,;:")]
    if len(parts) <= 1:
        return clean, None
    role_idx = next((i for i, p in enumerate(parts) if _ROLE_NOUNS.search(p)), 0)
    role = parts[role_idx]
    others = [p for i, p in enumerate(parts) if i != role_idx and not _is_place(p)]
    company = others[0] if others else None
    return role, company


def _is_place(part: str) -> bool:
    """The whole part is a place ("Florianópolis, SC"), not a name that merely contains one."""
    cm = geo_mod.load().find_city(part)
    return bool(cm and cm.start <= 1 and cm.end >= len(part.rstrip(" ,.;")) - 4)


_INTEREST = re.compile(
    r"interesse|interessad|interest(?:ed)? in|curiosidade|curious|aprendendo|estudando|learning|quero aprender|"
    r"pretendo|gostaria de|would like to|aspiring|em transi[cç][aã]o para",
    re.IGNORECASE,
)


def _claims_only(text: str) -> str:
    """Drop sentences that state an interest ("Interesse em machine learning"): interest is not a skill."""
    sentences = re.split(r"(?<=[.!?;])\s+|\n", text)
    return "\n".join(x for x in sentences if not _INTEREST.search(x))


def _strip_dates(line: str, ranges: list[DateRange]) -> str:
    folded_line = line
    for r in sorted(ranges, key=lambda r: -r.span[0]):
        folded_line = folded_line[: r.span[0]] + " " + folded_line[r.span[1] :]
    return squash(folded_line.strip(" |-–—,()"))


def _experiences(
    text: str, start: int, end: int, prov: dict[str, Provenance], offset: int, projects: bool = False
) -> list[ExperienceIn]:
    tax = tax_mod.load()
    block = text[start:end]
    lines = block.splitlines(keepends=True)
    positions: list[int] = []
    pos = 0
    for ln in lines:
        positions.append(pos)
        pos += len(ln)
    date_lines = [(i, find_date_ranges(ln)) for i, ln in enumerate(lines)]
    date_lines = [(i, r) for i, r in date_lines if r]
    entries: list[tuple[int, int, DateRange, str]] = []  # (header_start_line, date_line, range, header)
    for idx, (i, ranges) in enumerate(date_lines):
        own = _strip_dates(lines[i], ranges)
        header_start = i
        header = own
        prev_limit = date_lines[idx - 1][0] + 1 if idx > 0 else 0
        j = i - 1
        while j >= prev_limit and not lines[j].strip():
            j -= 1
        if j >= prev_limit and lines[j].strip() and not _BULLET.match(lines[j]) and len(lines[j].strip()) < 90:
            header = squash(lines[j].strip() + (" — " + own if own else ""))
            header_start = j
        if not header:
            continue
        entries.append((header_start, i, ranges[0], header))
    out: list[ExperienceIn] = []
    for k, (h_start, d_line, rng, header) in enumerate(entries):
        body_end_line = entries[k + 1][0] if k + 1 < len(entries) else len(lines)
        body_lines = lines[d_line + 1 : body_end_line]
        body = "".join(body_lines)
        role, company = _split_role_company(header)
        n = len(out)
        skills = tax.skill_ids(header + "\n" + body)
        seniority = tax.seniority_from_title(role)
        outcomes = [squash(_BULLET.sub("", ln)) for ln in body_lines if _BULLET.match(ln) and _OUTCOME.search(ln)]
        responsibilities = squash(" ".join(_BULLET.sub("", ln).strip() for ln in body_lines if ln.strip()))
        out.append(
            ExperienceIn(
                company=company,
                role=role or ("Projeto" if projects else ""),
                seniority=seniority.level if seniority else None,
                start=rng.start,
                end=rng.end,
                skills_used=skills,
                responsibilities=responsibilities or None,
                outcomes=outcomes[:5],
            )
        )
        abs_start = offset + start + positions[h_start]
        abs_end = offset + start + positions[d_line] + len(lines[d_line])
        span_text = excerpt(text, abs_start - offset, abs_end - offset, margin=0)
        prov[f"experiences.{n}.role"] = Provenance(source_span=span_text, stated=True, confidence=0.7)
        prov[f"experiences.{n}.start"] = Provenance(source_span=span_text, stated=True, confidence=0.8)
        if company:
            prov[f"experiences.{n}.company"] = Provenance(source_span=span_text, stated=True, confidence=0.6)
        for sid in skills:
            prov[f"experiences.{n}.skills_used.{sid}"] = Provenance(source_span=span_text, stated=True, confidence=0.75)
    return out


def _education(block: str) -> list[EducationIn]:
    out: list[EducationIn] = []
    entries = [e for e in re.split(r"\n\s*\n|\n(?=\s*[•\-*])", block) if e.strip()]
    for entry in entries:
        lines = [squash(_BULLET.sub("", ln)) for ln in entry.splitlines() if ln.strip()]
        flat = " — ".join(lines)
        m = _DEGREE.search(flat)
        if not m:
            continue
        ranges = find_date_ranges(flat)
        in_progress = bool(_IN_PROGRESS.search(flat))
        years = [int(y) for y in re.findall(r"\b(?:19|20)\d\d\b", flat)]
        start = ranges[0].start if ranges else (date(years[0], 1, 1) if len(years) >= 2 else None)
        end = None if in_progress else (ranges[0].end if ranges else (date(years[-1], 12, 1) if years else None))
        institution = None
        rest = _strip_dates(flat[: m.start()] + " " + flat[m.end() :], ranges)
        parts = [p.strip(" ,;:—–-|") for p in re.split(r"—|–|\||,|-(?=\s)", rest) if p.strip(" ,;:—–-|")]
        parts = [p for p in parts if not re.fullmatch(r"[\d\s/]+", p) and not _IN_PROGRESS.search(p)]
        if parts:
            institution = parts[0]
        out.append(
            EducationIn(
                degree=squash(m.group("d")).capitalize(),
                field=squash(m.group("f")) if m.group("f") else None,
                institution=institution,
                start=start,
                end=end,
            )
        )
    return out


def extract_cv(text: str) -> CandidateDraft:
    tax = tax_mod.load()
    geo = geo_mod.load()
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    prov: dict[str, Provenance] = {}
    warnings: list[str] = []
    sections = _sections(text)
    experiences: list[ExperienceIn] = []
    listed: dict[str, None] = {}
    education: list[EducationIn] = []
    languages: list[LanguageLevel] = []
    header = next((text[s:e] for k, s, e in sections if k == "header"), "")
    summary = ""

    for kind, s, e in sections:
        block = text[s:e]
        if kind in ("experience", "projects"):
            experiences += _experiences(text, s, e, prov, 0, projects=kind == "projects")
        elif kind == "education":
            education += _education(block)
        elif kind == "skills":
            for sid in tax.skill_ids(block):
                listed.setdefault(sid, None)
                prov[f"skills_listed.{sid}"] = Provenance(
                    source_span=excerpt(block, 0, 0, 120), stated=True, confidence=0.8
                )
        elif kind == "languages":
            for lm in tax.find_languages(block):
                if lm.language not in {lang.language for lang in languages}:
                    languages.append(LanguageLevel(language=lm.language, level=lm.level))
                    prov[f"languages.{lm.language}"] = Provenance(
                        source_span=excerpt(block, lm.start, lm.end, 20), stated=True, confidence=0.8
                    )
        elif kind == "summary":
            summary = block
        elif kind == "courses":
            for sid in tax.skill_ids(block):
                listed.setdefault(sid, None)
                prov.setdefault(f"skills_listed.{sid}", Provenance(source_span="cursos", stated=True, confidence=0.6))

    # Experiences without an experience heading: look for dated blocks anywhere.
    if not experiences:
        experiences = _experiences(text, 0, len(text), prov, 0)
        if experiences:
            warnings.append("experiências encontradas sem um título de seção; confira as datas")

    # Summary/header skills are listed (mentioned without a dated experience).
    for sid in tax.skill_ids(_claims_only(summary)):
        listed.setdefault(sid, None)
        prov.setdefault(f"skills_listed.{sid}", Provenance(source_span="resumo", stated=True, confidence=0.6))

    # Name, contact, headline, city from the header.
    header_lines = [ln.strip() for ln in header.splitlines() if ln.strip()]
    name = ""
    if header_lines:
        first = header_lines[0]
        if (
            2 <= len(first.split()) <= 5
            and not re.search(r"[\d@|/]", first)
            and not _ROLE_NOUNS.search(first)
            and first[:1].isupper()
        ):
            name = first
            prov["name"] = Provenance(source_span=first, stated=True, confidence=0.7)
    contacts = _EMAIL.findall(header) + _URL.findall(header)
    phones = [p for p in _PHONE.findall(header) if len(re.sub(r"\D", "", p)) >= 10]
    contact = " · ".join(dict.fromkeys(contacts + phones)) or None
    headline = None
    for ln in header_lines[1:] if name else header_lines:
        if _ROLE_NOUNS.search(ln) and not _EMAIL.search(ln) and len(ln) < 100:
            headline = squash(re.split(r"\s[|·•]\s", ln)[0])
            prov["headline"] = Provenance(source_span=ln, stated=True, confidence=0.7)
            break
    if headline is None and experiences:
        headline = experiences[0].role
        prov["headline"] = Provenance(source_span=experiences[0].role, stated=False, confidence=0.4)
    # City: header lines other than the name ("Ana Ribeiro Lima" is not Lima, Peru); qualified matches first.
    city_id = None
    for ln in header_lines:
        if ln == name:
            continue
        found = geo.find_cities(ln)
        best = next((c for c in found if c.qualified), found[0] if found else None)
        if best:
            city_id = best.city_id
            prov["city_id"] = Provenance(
                source_span=excerpt(ln, best.start, best.end, 15),
                stated=True,
                confidence=0.8 if best.qualified else 0.6,
            )
            break

    # Portuguese is inferred as native for a Brazilian CV written in Portuguese.
    if "pt" not in {lang.language for lang in languages}:
        is_br = geo.country_of(city_id) == "BR"
        if is_br and len(_PT_STOPWORDS.findall(text)) >= 5:
            languages.append(LanguageLevel(language="pt", level="native"))
            prov["languages.pt"] = Provenance(source_span=None, stated=False, confidence=0.5)

    # CV order is kept (provenance keys use the indices); recency is always computed from the dates.
    if not experiences:
        warnings.append("nenhuma experiência com datas encontrada: skills contam como listadas, não comprovadas")

    return CandidateDraft(
        name=name,
        contact=contact,
        headline=headline,
        city_id=city_id,
        experiences=experiences,
        education=education,
        skills_listed=list(listed),
        languages=languages,
        provenance=prov,
        warnings=warnings,
        method="heuristic",
    )
