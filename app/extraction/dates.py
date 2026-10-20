"""Experience/education dates and years of experience.

Trap 4: years of experience are the length of the UNION of the intervals (overlaps counted once), never
"latest end minus earliest start".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from app.textnorm import fold

MONTHS = {
    "jan": 1,
    "janeiro": 1,
    "january": 1,
    "fev": 2,
    "fevereiro": 2,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "marco": 3,
    "march": 3,
    "abr": 4,
    "abril": 4,
    "apr": 4,
    "april": 4,
    "mai": 5,
    "maio": 5,
    "may": 5,
    "jun": 6,
    "junho": 6,
    "june": 6,
    "jul": 7,
    "julho": 7,
    "july": 7,
    "ago": 8,
    "agosto": 8,
    "aug": 8,
    "august": 8,
    "set": 9,
    "setembro": 9,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "out": 10,
    "outubro": 10,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "novembro": 11,
    "november": 11,
    "dez": 12,
    "dezembro": 12,
    "dec": 12,
    "december": 12,
}
_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))
_PRESENT = r"(?:atual(?:mente)?|o momento|presente|present|current(?:ly)?|now|hoje|ate o momento|em andamento|cursando)"


# One date: "jan/2022", "jan 2022", "janeiro de 2022", "01/2022", "2022-01", "2022"
def _date(p: str) -> str:
    year = r"(?:19|20)\d\d"
    return (
        rf"(?:(?:(?P<{p}m>{_MONTH_ALT})\.?(?:\s*(?:/|-|de|\s)\s*))(?P<{p}y1>{year})"
        rf"|(?P<{p}mm>0?[1-9]|1[0-2])\s*[/.-]\s*(?P<{p}y2>{year})"
        rf"|(?P<{p}y3>{year})\s*[/.-]\s*(?P<{p}mm3>0[1-9]|1[0-2])(?!\d)"
        rf"|(?P<{p}y4>{year}))"
    )


_RANGE = re.compile(
    r"(?<![\d/])(?:de\s+|desde\s+|since\s+|from\s+)?"
    + _date("s")
    + r"\s*(?:-|–|—|a|ate|to|until|→|>)\s*"
    + r"(?:"
    + _date("e")
    + r"|(?P<present>"
    + _PRESENT
    + r"))(?![\d/])",
    re.IGNORECASE,
)
_SINCE = re.compile(r"\b(?:desde|since)\s+" + _date("s"), re.IGNORECASE)


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date | None  # None = ongoing
    span: tuple[int, int]
    end_explicit_present: bool


def _pick(m: re.Match[str], p: str) -> date | None:
    g = m.groupdict()
    if g.get(f"{p}y1"):
        return date(int(g[f"{p}y1"]), MONTHS[g[f"{p}m"].lower()], 1)
    if g.get(f"{p}y2"):
        return date(int(g[f"{p}y2"]), int(g[f"{p}mm"]), 1)
    if g.get(f"{p}y3"):
        return date(int(g[f"{p}y3"]), int(g[f"{p}mm3"]), 1)
    if g.get(f"{p}y4"):
        return date(int(g[f"{p}y4"]), 1, 1)
    return None


def find_date_ranges(text: str) -> list[DateRange]:
    """Date ranges in text order. Year-only ends become December of that year."""
    folded = fold(text)
    out: list[DateRange] = []
    for m in _RANGE.finditer(folded):
        start = _pick(m, "s")
        if start is None:
            continue
        end = None if m.group("present") else _pick(m, "e")
        if end is not None and m.groupdict().get("ey4") and not m.groupdict().get("ey1"):
            end = date(end.year, 12, 1)
        if end is not None and end < start:
            continue
        out.append(DateRange(start, end, (m.start(), m.end()), bool(m.group("present"))))
    if not out:
        for m in _SINCE.finditer(folded):
            start = _pick(m, "s")
            if start:
                out.append(DateRange(start, None, (m.start(), m.end()), True))
    return out


def months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month) + 1


def union_years(intervals: list[tuple[date | None, date | None]], today: date) -> float:
    """Total years covered by the intervals, overlaps counted once (trap 4)."""
    spans: list[tuple[int, int]] = []
    for start, end in intervals:
        if start is None:
            continue
        stop = end or today
        if stop < start:
            continue
        spans.append((start.year * 12 + start.month - 1, stop.year * 12 + stop.month - 1))
    spans.sort()
    total = 0
    cur_s, cur_e = None, None
    for s, e in spans:
        if cur_e is None or s > cur_e + 1:
            if cur_e is not None and cur_s is not None:
                total += cur_e - cur_s + 1
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None and cur_s is not None:
        total += cur_e - cur_s + 1
    return round(total / 12, 2)


def overlaps_window(start: date | None, end: date | None, window_start: date, today: date) -> bool:
    """True when [start, end or today] intersects [window_start, today]."""
    if start is None:
        return False
    return (end or today) >= window_start and start <= today
