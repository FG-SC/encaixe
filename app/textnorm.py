"""Text normalization shared by the taxonomy, geography, companies and extraction.

``fold`` removes accents and lowercases **character by character**, so the folded string has the same
length as the original and every match span in the folded text points at the same characters of the
original (provenance keeps the original excerpt). ``fold_keep_case`` does the same without lowering.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache


@lru_cache(maxsize=4096)
def _fold_char(ch: str, lower: bool) -> str:
    decomposed = unicodedata.normalize("NFKD", ch)
    base = "".join(c for c in decomposed if not unicodedata.combining(c))
    if len(base) != 1:  # ligatures, ß, symbols that expand: keep 1:1 alignment
        base = ch
    return base.lower() if lower else base


def fold(text: str) -> str:
    """Lowercase, accent-free, same length as ``text``."""
    return "".join(_fold_char(c, True) for c in text)


def fold_keep_case(text: str) -> str:
    """Accent-free, case preserved, same length as ``text``."""
    return "".join(_fold_char(c, False) for c in text)


_SPACES = re.compile(r"\s+")


def squash(text: str) -> str:
    """Collapse whitespace runs to one space and strip."""
    return _SPACES.sub(" ", text).strip()


def norm_key(text: str) -> str:
    """Comparison key: folded, punctuation as spaces, squashed."""
    return squash(re.sub(r"[^\w#+.]+", " ", fold(text)))


WORD_CHARS = "a-z0-9"


def phrase_pattern(phrases: list[str], case_sensitive: bool = False) -> re.Pattern[str] | None:
    """One regex alternation (longest first) with alphanumeric boundaries on both sides."""
    unique = sorted({p for p in phrases if p}, key=lambda p: (-len(p), p))
    if not unique:
        return None
    body = "|".join(re.escape(p) for p in unique)
    word = "A-Za-z0-9" if case_sensitive else WORD_CHARS
    return re.compile(rf"(?<![{word}])(?:{body})(?![{word}])")


def excerpt(text: str, start: int, end: int, margin: int = 40) -> str:
    """Original text around a span, for provenance (``source_span``)."""
    a = max(0, start - margin)
    b = min(len(text), end + margin)
    prefix = "…" if a > 0 else ""
    suffix = "…" if b < len(text) else ""
    return prefix + squash(text[a:b]) + suffix
