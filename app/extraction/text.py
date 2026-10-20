"""HTML to text, section detection and institutional-text removal.

Trap 2: section headings count only at the start of a line ("Requisitos:", "## Nice to have"), never in the
middle of a sentence ("the requirements of our clients"). Trap 8: about-us, benefits, EEO, privacy and
how-to-apply blocks are removed before skills and embeddings are computed.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from app.textnorm import fold

# --------------------------------------------------------------------------- html


_BLOCK_TAGS = re.compile(r"(?i)</?(?:p|div|br|li|ul|ol|h[1-6]|tr|table|section|article|header|footer)\b[^>]*>")
_LI_OPEN = re.compile(r"(?i)<li\b[^>]*>")
_TAG = re.compile(r"<[^>]+>")


def html_to_text(raw: str | None) -> str:
    """Greenhouse sends HTML-escaped HTML; Lever sends HTML or plain text. Returns plain text lines."""
    if not raw:
        return ""
    s = raw
    for _ in range(2):  # double-escaped content ("&lt;p&gt;")
        if "&lt;" in s or "&amp;" in s or "&#" in s:
            s = html.unescape(s)
    if "<" in s and ">" in s:
        s = _LI_OPEN.sub("\n• ", s)
        s = _BLOCK_TAGS.sub("\n", s)
        s = _TAG.sub("", s)
        s = html.unescape(s)
    s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in s.split("\n")]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip()


# --------------------------------------------------------------------------- sections

# Order matters: "nice" phrases are checked before "must" ("Qualificações desejáveis").
_HEADINGS: list[tuple[str, list[str]]] = [
    (
        "nice",
        [
            "nice to have",
            "nice-to-have",
            "nice to haves",
            "bonus points",
            "bonus",
            "pluses",
            "plus",
            "it's a plus",
            "it is a plus",
            "would be a plus",
            "preferred qualifications",
            "preferred skills",
            "preferred",
            "desirable",
            "good to have",
            "extra points",
            "differentials",
            "diferenciais",
            "diferencial",
            "desejaveis",
            "desejavel",
            "qualificacoes desejaveis",
            "requisitos desejaveis",
            "conhecimentos desejaveis",
            "sera um diferencial",
            "sera um plus",
            "o que pode te destacar",
            "pontos extras",
            "e um plus",
            "seria legal ter",
        ],
    ),
    (
        "must",
        [
            "requirements",
            "requirement",
            "required",
            "required skills",
            "requirements and qualifications",
            "qualifications",
            "basic qualifications",
            "minimum qualifications",
            "must have",
            "must-have",
            "must haves",
            "what you'll need",
            "what you will need",
            "what we're looking for",
            "what we are looking for",
            "what you bring",
            "who you are",
            "skills",
            "hard skills",
            "technical skills",
            "requisitos",
            "requisitos obrigatorios",
            "requisitos e qualificacoes",
            "requisitos tecnicos",
            "qualificacoes",
            "conhecimentos necessarios",
            "conhecimentos obrigatorios",
            "conhecimentos",
            "o que esperamos de voce",
            "o que buscamos",
            "o que procuramos",
            "o que voce precisa ter",
            "o que voce precisa",
            "o que voce traz",
            "pre-requisitos",
            "pre requisitos",
            "competencias",
            "habilidades",
            "perfil desejado",
            "perfil",
            "exigencias",
        ],
    ),
    (
        "responsibilities",
        [
            "responsibilities",
            "your responsibilities",
            "what you'll do",
            "what you will do",
            "what you'll be doing",
            "the role",
            "about the role",
            "role",
            "the job",
            "your mission",
            "day to day",
            "your impact",
            "responsabilidades",
            "atribuicoes",
            "atividades",
            "principais atividades",
            "o que voce vai fazer",
            "o que voce fara",
            "seu dia a dia",
            "sobre a vaga",
            "a vaga",
            "descricao da vaga",
            "descricao",
            "desafios",
            "sua missao",
            "missao do cargo",
            "job description",
            "description",
            "overview",
        ],
    ),
    (
        "salary",
        [
            "salary",
            "salary range",
            "compensation",
            "pay range",
            "pay",
            "remuneracao",
            "salario",
            "faixa salarial",
            "bolsa",
            "bolsa auxilio",
        ],
    ),
    (
        "location",
        [
            "location",
            "local",
            "localizacao",
            "local de trabalho",
            "modalidade",
            "regime",
            "contratacao",
            "tipo de contratacao",
            "modelo de trabalho",
            "work model",
        ],
    ),
    (
        "institutional",
        [
            "about us",
            "about the company",
            "who we are",
            "our company",
            "our mission",
            "our story",
            "about",
            "benefits",
            "perks",
            "perks and benefits",
            "what we offer",
            "we offer",
            "why join us",
            "why you'll love",
            "equal opportunity",
            "equal employment opportunity",
            "eeo",
            "diversity",
            "diversity and inclusion",
            "privacy",
            "privacy notice",
            "data privacy",
            "how to apply",
            "application process",
            "interview process",
            "next steps",
            "sobre nos",
            "sobre a empresa",
            "quem somos",
            "nossa empresa",
            "nossa missao",
            "nossa historia",
            "a empresa",
            "beneficios",
            "o que oferecemos",
            "oferecemos",
            "por que trabalhar conosco",
            "diversidade",
            "diversidade e inclusao",
            "inclusao",
            "privacidade",
            "como se candidatar",
            "como aplicar",
            "etapas do processo",
            "processo seletivo",
            "proximos passos",
        ],
    ),
]

_HEADING_LOOKUP: list[tuple[str, str]] = sorted(
    [(phrase, kind) for kind, phrases in _HEADINGS for phrase in phrases], key=lambda x: -len(x[0])
)

_BULLET = re.compile(r"^[\s#>*•·\-–—+]*")
_HEADING_TAIL = re.compile(r"^[\s:：\-–—!?.]*$")

# Institutional paragraphs that appear outside a heading (EEO statements, privacy notes).
_INSTITUTIONAL_LINES = re.compile(
    r"(?i)equal opportunity|equal employment|without regard to (?:race|sex|gender)|we celebrate diversity|"
    r"reasonable accommodation|privacy (?:policy|notice)|pol[ií]tica de privacidade|lgpd|"
    r"valorizamos a diversidade|todas as pessoas candidatas|sem distin[cç][aã]o de|"
    r"e-verify|background check|pessoas com defici[eê]ncia \(pcd\)|vaga (?:tamb[eé]m )?(?:afirmativa|exclusiva)"
)


@dataclass
class Section:
    kind: str  # must | nice | responsibilities | salary | location | institutional | intro
    heading: str | None
    start: int  # char offset of the section body in the text
    end: int

    def body(self, text: str) -> str:
        return text[self.start : self.end]


def heading_kind(line: str) -> tuple[str, int] | None:
    """(kind, body offset within the line) when the line *starts* with a known heading; else None.

    Offset = len(line) for a bare heading ("Requisitos:"), the start of the rest for "Requisitos: Python",
    0 for a heading followed by a few words ("Requisitos obrigatórios para a vaga"), whose line stays in the
    body. One-word headings ("Pay", "Plus", "Perfil") must stand alone or end with a colon/dash.
    """
    lead = len(line) - len(line.lstrip())
    stripped_full = _BULLET.sub("", line)
    offset0 = len(line) - len(stripped_full)
    stripped = stripped_full.strip().strip("*_").strip()
    if not stripped or len(stripped) > 90:
        return None
    key = fold(stripped)
    for phrase, kind in _HEADING_LOOKUP:
        if not key.startswith(phrase):
            continue
        rest = stripped[len(phrase) :]
        if rest and rest[0].isalnum():  # "skillset" is not "skills"
            continue
        if _HEADING_TAIL.match(rest):
            return kind, len(line)
        m = re.match(r"^\s*(?:\([^)]*\))?\s*[:：\-–—]\s*(.*)$", rest)
        if m:
            body = m.group(1)
            return kind, (line.find(body, offset0) if body else len(line))
        one_word = " " not in phrase
        if not one_word and len(rest.split()) <= 4 and not rest.rstrip().endswith((".", ",", ";")):
            return kind, max(lead, 0)
    # "Sobre a Lumen Dados", "About Acme": an about-the-company heading with the company's name.
    if re.match(r"^(?:sobre (?:a|o|nos)|about|conheca a|conheca o|quem e a|who is)\s+\S", key) and (
        len(stripped.split()) <= 6 and not stripped.rstrip().endswith((".", ",", ";"))
    ):
        return "institutional", len(line)
    return None


def split_sections(text: str) -> list[Section]:
    """Sections in text order. Text before the first heading is "intro"."""
    sections: list[Section] = []
    pos = 0
    current = Section("intro", None, 0, 0)
    for line in text.splitlines(keepends=True):
        hk = heading_kind(line)
        if hk is not None:
            kind, offset = hk
            current.end = pos
            sections.append(current)
            current = Section(kind, line.strip(), pos + offset, 0)
        pos += len(line)
    current.end = len(text)
    sections.append(current)
    return [s for s in sections if s.end > s.start or s.heading]


def strip_institutional(text: str, sections: list[Section] | None = None) -> str:
    """Text without institutional sections and EEO/privacy lines (trap 8)."""
    sections = sections if sections is not None else split_sections(text)
    kept = [s.body(text) for s in sections if s.kind != "institutional"]
    lines = [ln for ln in "\n".join(kept).splitlines() if not _INSTITUTIONAL_LINES.search(ln)]
    return "\n".join(lines).strip()


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý0-9])")


def first_sentences(text: str, max_words: int) -> str:
    """The first sentences/lines of ``text`` up to ``max_words`` words."""
    words: list[str] = []
    for piece in _SENTENCE_END.split(text.replace("\n", " ")):
        piece_words = piece.split()
        if not piece_words:
            continue
        if words and len(words) + len(piece_words) > max_words:
            break
        words.extend(piece_words[: max_words - len(words)])
        if len(words) >= max_words:
            break
    return " ".join(words)
