"""Skills taxonomy (``skills.yaml``): aliases, parents, domains, languages and the seniority ladder.

Matching contract (also in the YAML header):
- ``aliases`` are lowercase and accent-free; they match the folded text (``app.textnorm.fold``) with
  alphanumeric boundaries, leftmost-longest.
- ``case_sensitive_aliases`` (R, Go, React, Excel, ML, IA, AI…) match the accent-free text with case
  preserved: "React" is the library, "react quickly" is a verb.
- ``blockers`` (plain phrase, or ``re:`` regex on the case-preserved text) veto overlapping matches of
  that skill only ("go to market", "R$", "excel at").
- ``transversal`` skills (Excel, Git, negotiation…) define no domain and never count as proof of area.
- ``also_domains`` extend the candidate's domains but do not vote in a job's majority domain.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from app.textnorm import fold, fold_keep_case, phrase_pattern

TAXONOMY_PATH = Path(__file__).with_name("skills.yaml")

# Language ids of skills.yaml -> ISO 639-1 codes used in profiles and jobs.
LANGUAGE_CODES = {
    "english": "en",
    "spanish": "es",
    "portuguese": "pt",
    "french": "fr",
    "german": "de",
    "italian": "it",
    "mandarin": "zh",
    "japanese": "ja",
}


@dataclass(frozen=True)
class Skill:
    id: str
    label: str
    label_en: str
    domain: str
    parent: str | None
    also_domains: tuple[str, ...] = ()
    transversal: bool = False


@dataclass(frozen=True)
class SkillMatch:
    skill_id: str
    start: int
    end: int
    alias: str


@dataclass(frozen=True)
class LanguageMatch:
    language: str  # ISO 639-1
    level: str | None
    start: int
    end: int


@dataclass(frozen=True)
class SeniorityMatch:
    level: int
    start: int
    end: int
    strength: str  # "explicit" | "role"


@dataclass
class _Blockers:
    phrases: re.Pattern[str] | None = None
    regexes: list[re.Pattern[str]] = field(default_factory=list)


def _blocker_pattern(phrases: list[str]) -> re.Pattern[str] | None:
    parts = []
    for p in sorted(set(phrases), key=lambda s: (-len(s), s)):
        left = r"(?<![a-z0-9])" if p[:1].isalnum() else ""
        right = r"(?![a-z0-9])" if p[-1:].isalnum() else ""
        parts.append(f"{left}{re.escape(p)}{right}")
    return re.compile("|".join(parts)) if parts else None


def _spans(pattern: re.Pattern[str] | None, text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in pattern.finditer(text)] if pattern else []


def _overlaps(a: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    return any(a[0] < e and s < a[1] for s, e in spans)


class Taxonomy:
    def __init__(self, data: dict) -> None:
        self.version = data.get("version", 1)
        self.domain_info: dict[str, dict] = {d["id"]: d for d in data["domains"]}
        self.skills: dict[str, Skill] = {}
        alias_owner: dict[str, str] = {}
        cs_owner: dict[str, str] = {}
        self._blockers: dict[str, _Blockers] = {}
        for raw in data["skills"]:
            sid = raw["id"]
            self.skills[sid] = Skill(
                id=sid,
                label=raw["label"],
                label_en=raw.get("label_en", raw["label"]),
                domain=raw["domain"],
                parent=raw.get("parent"),
                also_domains=tuple(raw.get("also_domains", ())),
                transversal=bool(raw.get("transversal", False)),
            )
            for alias in raw.get("aliases", []):
                alias_owner[fold(alias)] = sid
            for alias in raw.get("case_sensitive_aliases", []):
                cs_owner[fold_keep_case(alias)] = sid
            phrases = [fold(b) for b in raw.get("blockers", []) if not b.startswith("re:")]
            regexes = [re.compile(b[3:]) for b in raw.get("blockers", []) if b.startswith("re:")]
            self._blockers[sid] = _Blockers(_blocker_pattern(phrases), regexes)
        self._alias_owner = alias_owner
        self._cs_owner = cs_owner
        self._alias_re = phrase_pattern(list(alias_owner))
        self._cs_re = phrase_pattern(list(cs_owner), case_sensitive=True)
        self._children: dict[str, list[str]] = {}
        for s in self.skills.values():
            if s.parent:
                self._children.setdefault(s.parent, []).append(s.id)

        self.level_order: list[str] = list(data.get("language_level_order", []))
        self.languages: dict[str, dict] = {}
        lang_alias: dict[str, str] = {}
        level_word: dict[str, str] = {}
        for raw in data.get("languages", []):
            code = LANGUAGE_CODES.get(raw["id"], raw["id"])
            self.languages[code] = raw
            for alias in raw.get("aliases", []):
                lang_alias[fold(alias)] = code
            for level, words in raw.get("level_words", {}).items():
                for w in words:
                    level_word.setdefault(fold(w), level)
        self._lang_owner = lang_alias
        self._lang_re = phrase_pattern(list(lang_alias))
        self._level_word = level_word
        self._level_re = phrase_pattern(list(level_word))

        sen = data.get("seniority", {})
        self.seniority_labels: dict[int, str] = {}
        explicit: dict[str, int] = {}
        explicit_cs: dict[str, int] = {}
        for lv in sen.get("levels", []):
            self.seniority_labels[lv["level"]] = lv.get("label_pt", str(lv["level"]))
            for t in lv.get("tokens", []):
                explicit[fold(t)] = lv["level"]
            for t in lv.get("case_sensitive_tokens", []):
                explicit_cs[t] = lv["level"]
        role: dict[str, int] = {}
        for rt in sen.get("role_tokens", []):
            for t in rt.get("tokens", []):
                role[fold(t)] = rt["level"]
        self._sen_explicit, self._sen_explicit_cs, self._sen_role = explicit, explicit_cs, role
        self._sen_explicit_re = phrase_pattern(list(explicit))
        self._sen_explicit_cs_re = phrase_pattern(list(explicit_cs), case_sensitive=True)
        self._sen_role_re = phrase_pattern(list(role))
        self._sen_neutral_re = phrase_pattern([fold(t) for t in sen.get("no_level_role_nouns", [])])
        self._sen_blockers_re = _blocker_pattern([fold(t) for t in sen.get("blockers", [])])

    # ------------------------------------------------------------------ skills

    def has(self, skill_id: str) -> bool:
        return skill_id in self.skills

    def label(self, skill_id: str) -> str:
        s = self.skills.get(skill_id)
        return s.label if s else skill_id

    def parent(self, skill_id: str) -> str | None:
        s = self.skills.get(skill_id)
        return s.parent if s else None

    def children(self, skill_id: str) -> list[str]:
        return list(self._children.get(skill_id, ()))

    def related(self, a: str, b: str) -> bool:
        """Direct parent/child (partial credit)."""
        return a != b and (self.parent(a) == b or self.parent(b) == a)

    def domain(self, skill_id: str) -> str | None:
        s = self.skills.get(skill_id)
        return None if s is None or s.transversal else s.domain

    def domains(self, skill_id: str) -> set[str]:
        """Domain plus also_domains; empty for transversal or unknown skills."""
        s = self.skills.get(skill_id)
        if s is None or s.transversal:
            return set()
        return {s.domain, *s.also_domains}

    def is_transversal(self, skill_id: str) -> bool:
        s = self.skills.get(skill_id)
        return bool(s and s.transversal)

    def job_domains(self, skill_ids: list[str]) -> list[str]:
        """Majority domain(s) of a job's skills (transversal skills and also_domains do not vote)."""
        votes = Counter(d for d in (self.domain(s) for s in skill_ids) if d)
        if not votes:
            return []
        top = max(votes.values())
        return sorted(d for d, n in votes.items() if n == top)

    def find_skills(self, text: str) -> list[SkillMatch]:
        """Skills mentioned in ``text``, leftmost-longest, without overlaps, in text order."""
        if not text:
            return []
        folded = fold(text)
        cased = fold_keep_case(text)
        candidates: list[SkillMatch] = []
        if self._alias_re:
            for m in self._alias_re.finditer(folded):
                candidates.append(SkillMatch(self._alias_owner[m.group(0)], m.start(), m.end(), m.group(0)))
        if self._cs_re:
            for m in self._cs_re.finditer(cased):
                candidates.append(SkillMatch(self._cs_owner[m.group(0)], m.start(), m.end(), m.group(0)))
        candidates.sort(key=lambda c: (c.start, -(c.end - c.start)))
        chosen: list[SkillMatch] = []
        blocked_cache: dict[str, list[tuple[int, int]]] = {}
        for c in candidates:
            if chosen and c.start < chosen[-1].end:
                continue
            if c.skill_id not in blocked_cache:
                b = self._blockers.get(c.skill_id, _Blockers())
                spans = _spans(b.phrases, folded)
                for rx in b.regexes:
                    spans += _spans(rx, cased)
                blocked_cache[c.skill_id] = spans
            if _overlaps((c.start, c.end), blocked_cache[c.skill_id]):
                continue
            chosen.append(c)
        return chosen

    def skill_ids(self, text: str) -> list[str]:
        """Distinct skill ids in order of first mention."""
        seen: dict[str, None] = {}
        for m in self.find_skills(text):
            seen.setdefault(m.skill_id, None)
        return list(seen)

    # ------------------------------------------------------------------ languages

    def find_languages(self, text: str) -> list[LanguageMatch]:
        """Languages with the nearest level word in the same line ("inglês avançado", "Fluent English")."""
        if not text or not self._lang_re:
            return []
        folded = fold(text)
        out: list[LanguageMatch] = []
        for m in self._lang_re.finditer(folded):
            line_start = folded.rfind("\n", 0, m.start()) + 1
            line_end = folded.find("\n", m.end())
            line_end = len(folded) if line_end == -1 else line_end
            lo, hi = max(line_start, m.start() - 30), min(line_end, m.end() + 40)
            best: tuple[int, str] | None = None
            if self._level_re:
                for lm in self._level_re.finditer(folded, lo, hi):
                    dist = lm.start() - m.end() if lm.start() >= m.end() else m.start() - lm.end()
                    # Another language mentioned between the two: the level belongs to it.
                    between = folded[min(m.end(), lm.end()) : max(m.start(), lm.start())]
                    if self._lang_re.search(between):
                        continue
                    if best is None or dist < best[0]:
                        best = (dist, self._level_word[lm.group(0)])
            out.append(LanguageMatch(self._lang_owner[m.group(0)], best[1] if best else None, m.start(), m.end()))
        return out

    def level_rank(self, level: str | None) -> int:
        """0 = unknown, 1 = basic … 5 = native."""
        return self.level_order.index(level) + 1 if level in self.level_order else 0

    # ------------------------------------------------------------------ seniority

    def seniority_from_title(self, title: str | None) -> SeniorityMatch | None:
        """Explicit tokens (Jr, Pleno, Senior, Staff, I/II/III…) win over role tokens (manager, head…).

        Several explicit levels in one title (Jr/Pl, "Pleno a Sênior") → the lowest one.
        """
        if not title:
            return None
        folded = fold(title)
        cased = fold_keep_case(title)
        blocked = _spans(self._sen_blockers_re, folded)
        neutral = _spans(self._sen_neutral_re, folded)
        explicit: list[SeniorityMatch] = []
        for rx, table, text in (
            (self._sen_explicit_re, self._sen_explicit, folded),
            (self._sen_explicit_cs_re, self._sen_explicit_cs, cased),
        ):
            if rx is None:
                continue
            for m in rx.finditer(text):
                if not _overlaps((m.start(), m.end()), blocked):
                    explicit.append(SeniorityMatch(table[m.group(0)], m.start(), m.end(), "explicit"))
        if explicit:
            return min(explicit, key=lambda s: (s.level, s.start))
        roles = [
            SeniorityMatch(self._sen_role[m.group(0)], m.start(), m.end(), "role")
            for m in (self._sen_role_re.finditer(folded) if self._sen_role_re else [])
            if not _overlaps((m.start(), m.end()), blocked + neutral)
        ]
        return max(roles, key=lambda s: s.level) if roles else None


@lru_cache(maxsize=1)
def load() -> Taxonomy:
    with TAXONOMY_PATH.open(encoding="utf-8") as fh:
        return Taxonomy(yaml.safe_load(fh))
