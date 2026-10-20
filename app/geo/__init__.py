"""Static geography: ~160 cities, ~45 countries, regions (UN M49), timezones. No geocoding API.

Data: ``cities.csv`` (coordinates and timezones derived from GeoNames, CC BY 4.0), ``countries.csv``
(names from Unicode CLDR), ``regions.csv`` (memberships from UN M49). See NOTICE.

Traps handled here:
- country acronyms in location fields (trap 6): bare "BR", "US", "PT" are never places; two-letter codes
  count only as an explicit qualifier ("Lisboa, PT", "Austin, TX");
- timezone abbreviations (trap 3): ET, PT, CT… match only uppercase and only next to time context
  ("9am-5pm ET", "overlap with PT hours", "fuso"), never as words ("PT" = Portugal/português).
"""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from app.textnorm import fold, phrase_pattern

DATA_DIR = Path(__file__).parent


@dataclass(frozen=True)
class City:
    id: str
    name: str
    state: str
    country: str
    lat: float
    lon: float
    tz: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class CityMatch:
    city_id: str
    start: int
    end: int
    qualified: bool


@dataclass(frozen=True)
class Region:
    key: str
    aliases: tuple[str, ...]
    members: frozenset[str]  # ISO alpha-2; empty = worldwide


class Geo:
    def __init__(self) -> None:
        with (DATA_DIR / "cities.csv").open(encoding="utf-8", newline="") as fh:
            self.cities: dict[str, City] = {}
            for row in csv.DictReader(fh):
                self.cities[row["id"]] = City(
                    id=row["id"],
                    name=row["name"],
                    state=row["state"] or "",
                    country=row["country"],
                    lat=float(row["lat"]),
                    lon=float(row["lon"]),
                    tz=row["tz"],
                    aliases=tuple(a for a in (row.get("aliases") or "").split("|") if a),
                )
        with (DATA_DIR / "countries.csv").open(encoding="utf-8", newline="") as fh:
            self.countries: dict[str, dict[str, str]] = {r["code"]: r for r in csv.DictReader(fh)}
        self.regions: dict[str, Region] = {}
        with (DATA_DIR / "regions.csv").open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                key = row["region"].split(" ")[0]
                members = frozenset() if row["members"].strip() == "*" else frozenset(row["members"].split("|"))
                self.regions[key] = Region(key, tuple(a for a in row["aliases"].split("|") if a), members)

        # name/alias (folded) -> city ids in CSV order (first = default for bare homonyms)
        self._city_names: dict[str, list[str]] = {}
        for c in self.cities.values():
            for n in (c.name, *c.aliases):
                ids = self._city_names.setdefault(fold(n), [])
                if c.id not in ids:
                    ids.append(c.id)
        self._city_re = phrase_pattern(list(self._city_names))
        self._country_names: dict[str, str] = {}
        for code, r in self.countries.items():
            for n in (r["name_pt"], r["name_en"], *[a for a in r["aliases"].split("|") if a]):
                if len(n) > 2:  # never bare two-letter codes (trap 6)
                    self._country_names.setdefault(fold(n), code)
        self._country_re = phrase_pattern(list(self._country_names))
        self._region_names: dict[str, str] = {}
        for key, region in self.regions.items():
            for a in region.aliases:
                self._region_names[fold(a)] = key
        self._region_re = phrase_pattern(list(self._region_names))
        self._states_by_country: dict[str, set[str]] = {}
        for c in self.cities.values():
            if c.state:
                self._states_by_country.setdefault(c.country, set()).add(c.state)

    # ------------------------------------------------------------------ cities

    def get_city(self, city_id: str | None) -> City | None:
        return self.cities.get(city_id) if city_id else None

    def find_city(self, text: str | None) -> CityMatch | None:
        """First city in ``text``. A qualifier (", SC", " - SP", ", Brazil", ", TX") picks among homonyms."""
        matches = self.find_cities(text)
        return matches[0] if matches else None

    def find_cities(self, text: str | None) -> list[CityMatch]:
        if not text or self._city_re is None:
            return []
        folded = fold(text)
        out: list[CityMatch] = []
        for m in self._city_re.finditer(folded):
            ids = self._city_names[m.group(0)]
            qual = self._qualifier(text, m.end())
            chosen = None
            if qual:
                chosen = next((i for i in ids if qual in (self.cities[i].state, self.cities[i].country)), None)
            if chosen is None and qual is None and len(ids) >= 1:
                chosen = ids[0]
            if chosen is None:  # a qualifier that matches none of the homonyms: not this place
                continue
            out.append(CityMatch(chosen, m.start(), m.end(), qual is not None))
        return out

    def _qualifier(self, text: str, pos: int) -> str | None:
        """State or country code right after a city name: "Florianópolis, SC", "Austin, TX", "Porto, PT"."""
        m = re.match(r"\s*(?:,|-|–|/|\()\s*([A-Z]{2})(?![A-Za-z])", text[pos:])
        if m:
            return m.group(1)
        m = re.match(r"\s*(?:,|-|–|/|\()\s*([^\n,;()/|]{3,40})", text[pos:])
        if m:
            name = fold(m.group(1)).strip()
            for country_name, code in self._country_names.items():
                if name.startswith(country_name):
                    return code
        return None

    def country_of(self, city_id: str | None) -> str | None:
        c = self.get_city(city_id)
        return c.country if c else None

    # ------------------------------------------------------------------ countries and regions

    def find_countries(self, text: str | None) -> list[str]:
        """Countries named in ``text`` (names, demonyms, spelled-out abbreviations; never bare codes)."""
        if not text or self._country_re is None:
            return []
        seen: dict[str, None] = {}
        for m in self._country_re.finditer(fold(text)):
            seen.setdefault(self._country_names[m.group(0)], None)
        return list(seen)

    def find_regions(self, text: str | None) -> list[str]:
        if not text or self._region_re is None:
            return []
        seen: dict[str, None] = {}
        for m in self._region_re.finditer(fold(text)):
            seen.setdefault(self._region_names[m.group(0)], None)
        return list(seen)

    def region_members(self, key: str) -> frozenset[str]:
        return self.regions[key].members

    def _places_to_countries(self, fragment: str) -> list[str] | None:
        """Countries meant by a short place fragment; None = worldwide; [] = nothing recognized."""
        regions = self.find_regions(fragment)
        if any(not self.regions[r].members for r in regions):
            return None
        codes: dict[str, None] = {}
        for r in regions:
            for c in sorted(self.regions[r].members):
                codes.setdefault(c, None)
        for c in self.find_countries(fragment):
            codes.setdefault(c, None)
        for cm in self.find_cities(fragment):
            codes.setdefault(self.cities[cm.city_id].country, None)
        for c in self.codes_in_location_field(fragment):
            codes.setdefault(c, None)
        return list(codes)

    def codes_in_location_field(self, text: str | None) -> list[str]:
        """Uppercase country codes in a *location field* ("Remote - BR", "Lisboa, PT", "USA").

        Only for location/eligibility fragments: in free text "PT" may be Portuguese or Pacific Time.
        """
        if not text:
            return []
        out: dict[str, None] = {}
        for code in re.findall(r"(?<![A-Za-z])([A-Z]{2,3})(?![A-Za-z])", text):
            code = {"USA": "US", "UK": "GB", "EUA": "US"}.get(code, code)
            if code in self.countries:
                out.setdefault(code, None)
        return list(out)

    def location_country(self, location_text: str | None) -> str | None:
        """Country of a location field: its city, else the LAST country named ("City, Region, Country"), else a code."""
        if not location_text:
            return None
        city = self.find_city(location_text)
        if city:
            return self.cities[city.city_id].country
        names = self.find_countries(location_text)
        if names:
            return names[-1]
        codes = self.codes_in_location_field(location_text)
        return codes[0] if codes else None

    _ELIGIBILITY_PATTERNS = [
        # "Remote - US", "Remoto (Brasil)", "Remote, LATAM", "Remote: Americas"
        r"\b(?:remote|remoto|remota|fully remote|100% remot[oa])\s*(?:-|–|—|\(|,|:|/|in|in the|no|na|em)\s*"
        r"(?P<p>[^\n.;)]{2,60})",
        # "US only", "Brazil-based only", "LATAM only"
        r"(?P<p>[A-Za-zÀ-ÿ. ]{2,40}?)\s*(?:-based)?\s+only\b",
        # "must be located/based in", "must reside in" (a bare "we are located in" is the company's office)
        r"\b(?:must|should|need to|needs to|required to|have to|has to)\s+(?:be\s+)?(?:physically\s+)?"
        r"(?:located|based|residing|reside|live|living)\s+in\s+(?:the\s+)?(?P<p>[^\n.;,)]{2,50})",
        # "authorized/eligible to work in", "candidates from", "citizens of"
        r"\b(?:authori[sz]ed to work|eligible to work|legally (?:able|allowed) to work|work authorization"
        r"(?: for| in)?|candidates (?:from|in|based in)|applicants (?:from|in|based in)|citizens? of|"
        r"citizenship (?:of|in))\s+(?:in\s+)?(?:the\s+)?(?P<p>[^\n.;,)]{2,50})",
        r"\b(?P<p>U\.?S\.?|United States|American)\s+citizen(?:ship)?\b",
        # pt-BR: "residentes no Brasil", "apenas candidatos do Brasil", "somente para o Brasil"
        r"\b(?:residentes?|resid[ae]|morar|candidat[oa]s|pessoas|profissionais)\s+(?:em|no|na|do|da|nos|nas)\s+"
        r"(?P<p>[^\n.;,)]{2,40})",
        r"\b(?:apenas|somente|exclusivamente)\s+(?:para\s+)?(?:candidat[oa]s\s+)?(?:em|no|na|do|da|o|a)?\s*"
        r"(?P<p>[^\n.;,)]{2,40})",
    ]

    def find_eligibility(self, text: str | None) -> list[str]:
        """Countries a job explicitly restricts candidates to (empty = no explicit restriction)."""
        if not text:
            return []
        found: dict[str, None] = {}
        for pattern in self._ELIGIBILITY_PATTERNS:
            for m in re.finditer(pattern, text, flags=re.IGNORECASE):
                countries = self._places_to_countries(m.group("p"))
                if countries is None:  # "remote, worldwide": explicitly no restriction
                    continue
                for c in countries:
                    found.setdefault(c, None)
        return list(found)

    # ------------------------------------------------------------------ timezones

    TZ_ABBREVIATIONS = {
        "ET": "America/New_York",
        "EST": "America/New_York",
        "EDT": "America/New_York",
        "CT": "America/Chicago",
        "CST": "America/Chicago",
        "CDT": "America/Chicago",
        "MT": "America/Denver",
        "MST": "America/Denver",
        "MDT": "America/Denver",
        "PT": "America/Los_Angeles",
        "PST": "America/Los_Angeles",
        "PDT": "America/Los_Angeles",
        "BRT": "America/Sao_Paulo",
        "BRST": "America/Sao_Paulo",
        "CET": "Europe/Berlin",
        "CEST": "Europe/Berlin",
        "WET": "Europe/Lisbon",
        "GMT": "Europe/London",
        "BST": "Europe/London",
    }
    _TZ_CONTEXT = re.compile(
        r"time ?zones?|hours?|business|overlap|working|fuso|hor[aá]rio|expediente|\d{1,2}(?::\d{2})?\s*"
        r"(?:am|pm|h)\b|\d{1,2}h\d{0,2}|between|until|até|from|core",
        re.IGNORECASE,
    )

    def parse_tz(self, text: str | None) -> str | None:
        """Job timezone from the text: "UTC-3", "GMT+1", or an uppercase abbreviation in time context."""
        if not text:
            return None
        m = re.search(r"\b(?:UTC|GMT)\s?([+\-−–])\s?(\d{1,2})(?::?(\d{2}))?\b", text)
        if m:
            sign = -1 if m.group(1) in "-−–" else 1
            hours = int(m.group(2)) + (int(m.group(3) or 0) / 60)
            if hours <= 14:
                return _fixed_offset_name(sign * hours)
        for m in re.finditer(
            r"(?<![A-Za-z])(" + "|".join(sorted(self.TZ_ABBREVIATIONS, key=len, reverse=True)) + r")(?![A-Za-z])", text
        ):
            window = text[max(0, m.start() - 30) : m.end() + 30]
            if self._TZ_CONTEXT.search(window.replace(m.group(1), " ")):
                return self.TZ_ABBREVIATIONS[m.group(1)]
        return None


def _fixed_offset_name(hours: float) -> str:
    sign = "+" if hours >= 0 else "-"
    h = abs(hours)
    whole, minutes = int(h), int(round((h - int(h)) * 60))
    return f"UTC{sign}{whole}" + (f":{minutes:02d}" if minutes else "")


def tzinfo_for(tz: str) -> timezone | ZoneInfo:
    m = re.fullmatch(r"UTC([+-])(\d{1,2})(?::(\d{2}))?", tz)
    if m:
        delta = timedelta(hours=int(m.group(2)), minutes=int(m.group(3) or 0))
        return timezone(delta if m.group(1) == "+" else -delta)
    return ZoneInfo(tz)


def haversine_km(a: City, b: City) -> float:
    r = 6371.0088
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lon - a.lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


@lru_cache(maxsize=8192)
def tz_overlap_hours(tz_a: str, tz_b: str, on_date: date, start_hour: int, end_hour: int) -> float:
    """Hours of overlap between the [start_hour, end_hour) local workdays of two timezones on a date."""

    def window(tz: str) -> tuple[datetime, datetime]:
        info = tzinfo_for(tz)
        s = datetime(on_date.year, on_date.month, on_date.day, start_hour, tzinfo=info).astimezone(UTC)
        e = datetime(on_date.year, on_date.month, on_date.day, end_hour, tzinfo=info).astimezone(UTC)
        return s, e

    (sa, ea), (sb, eb) = window(tz_a), window(tz_b)
    overlap = (min(ea, eb) - max(sa, sb)).total_seconds() / 3600
    return max(0.0, round(overlap, 2))


@lru_cache(maxsize=1)
def load() -> Geo:
    return Geo()
