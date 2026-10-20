"""Salary extraction (traps 1 and 7).

Trap 1: amounts about funding or scale ("raised $50M", "100M customers", "faturamento de R$ 10 milhões")
are not salaries. A salary needs a currency marker AND salary context (salário, salary, remuneração,
compensation, pay range, bolsa…) or a salary-shaped range ("R$ 5.000 a R$ 7.000/mês"), no funding/scale
words nearby, no million/billion multipliers, and a plausible monthly value.
Trap 7: currencies differ; conversion to the candidate's currency happens in ranking with the approximate
rates of RULES.currency, always flagged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import RULES

_CURRENCY = (
    r"(?P<cur>R\$|US\$|U\$|USD|BRL|EUR|€|GBP|£|CAD|C\$|AUD|A\$|CHF|MXN|ARS|CLP|COP|PEN|UYU|INR|JPY|\$|"
    r"reais|d[oó]lares|dollars|euros)"
)
_NUM = r"(?P<{n}>\d{{1,3}}(?:[.,\s]\d{{3}})+(?:[.,]\d{{1,2}})?|\d+(?:[.,]\d+)?)\s*(?P<{n}k>k|mil|K)?"
_RANGE_SEP = r"\s*(?:-|–|—|a|até|to|and|e)\s*"

_AMOUNT_RE = re.compile(
    _CURRENCY
    + r"\s?"
    + _NUM.format(n="a")
    + r"(?:"
    + _RANGE_SEP
    + r"(?:"
    + _CURRENCY.replace("?P<cur>", "?:")
    + r"\s?)?"
    + _NUM.format(n="b")
    + r")?"
    + r"(?P<mult>\s*(?:mi|bi|milh[oõ]es|milh[aã]o|bilh[oõ]es|million|billion|mn|bn|[MB])\b)?",
    re.IGNORECASE,
)
# Amount written before the currency word: "5.000 reais", "120k USD"
_AMOUNT_AFTER_RE = re.compile(
    _NUM.format(n="a") + r"(?:" + _RANGE_SEP + _NUM.format(n="b") + r")?\s*"
    r"(?P<cur>reais|BRL|USD|EUR|d[oó]lares|dollars|euros)\b",
    re.IGNORECASE,
)

_CONTEXT = re.compile(
    r"sal[aá]ri|salary|remunera|compensa|pay\b|pay range|base pay|bolsa|ganho|faixa|stipend|wage|"
    r"\bote\b|pr[oó]-labore|pagamento|contrata[cç][aã]o|\bclt\b|\bpj\b|per (?:hour|month|year)|"
    r"por (?:m[eê]s|hora|ano)|/m[eê]s|/month|/year|/yr|/hora|/h\b|annual|anual|mensal|monthly",
    re.IGNORECASE,
)
_REJECT = re.compile(
    r"raised|raise[sd]?\b|funding|funded|series [a-e]\b|s[eé]rie [a-e]\b|valuation|valued|investment|investor|"
    r"invest|capta[cç]|captou|arrecad|aporte|faturament|revenue|\barr\b|\bgmv\b|customers|clients|users|"
    r"usu[aá]rios|clientes|downloads|transa[cç]|transactions|merchants|lojistas|empresas atendidas|"
    r"patrim[oô]nio|under management|\baum\b|budget|or[cç]amento|market cap|mercado de",
    re.IGNORECASE,
)
_PERIODS: list[tuple[str, str]] = [
    ("hour", r"/\s?h(?:ora|our|r)?\b|por hora|per hour|an hour|hourly|/hr\b"),
    ("day", r"/\s?dia\b|por dia|per day|daily|a day\b"),
    ("week", r"/\s?(?:semana|week)\b|por semana|per week|weekly"),
    ("month", r"/\s?m[eê]s\b|por m[eê]s|ao m[eê]s|mensais?|/\s?month|per month|a month|monthly|/mo\b"),
    ("year", r"/\s?(?:ano|year|yr)\b|por ano|ao ano|anuais?|per year|a year|annual(?:ly)?|/yr|\bpa\b|yearly"),
]

_CURRENCY_CODES = {
    "r$": "BRL",
    "brl": "BRL",
    "reais": "BRL",
    "us$": "USD",
    "u$": "USD",
    "usd": "USD",
    "$": "USD",
    "dolares": "USD",
    "dólares": "USD",
    "dollars": "USD",
    "eur": "EUR",
    "€": "EUR",
    "euros": "EUR",
    "gbp": "GBP",
    "£": "GBP",
    "cad": "CAD",
    "c$": "CAD",
    "aud": "AUD",
    "a$": "AUD",
    "chf": "CHF",
    "mxn": "MXN",
    "ars": "ARS",
    "clp": "CLP",
    "cop": "COP",
    "pen": "PEN",
    "uyu": "UYU",
    "inr": "INR",
    "jpy": "JPY",
}

# Plausible monthly salary in BRL (after approximate conversion).
MONTHLY_BRL_MIN = 400.0
MONTHLY_BRL_MAX = 250_000.0


@dataclass(frozen=True)
class Salary:
    comp_min: float
    comp_max: float
    currency: str
    period: str
    span: tuple[int, int]
    period_stated: bool


def parse_number(raw: str, thousands_suffix: str | None) -> float:
    s = raw.strip().replace(" ", "")
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", s):  # 5.000 / 120,000 / 1.200.000
        value = float(re.sub(r"[.,]", "", s))
    elif re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+[.,]\d{1,2}", s):  # 5.000,00 / 5,000.50
        value = float(re.sub(r"[.,]", "", s[:-3]) + "." + s[-2:]) if s[-3] in ".," else float(re.sub(r"[.,]", "", s))
    else:
        value = float(s.replace(",", "."))
    if thousands_suffix:
        value *= 1000
    return value


def _period_near(text: str, start: int, end: int) -> str | None:
    window = text[end : end + 40] + " " + text[max(0, start - 50) : start]
    for period, pattern in _PERIODS:
        if re.search(pattern, window, re.IGNORECASE):
            return period
    return None


def _infer_period(amount: float, currency: str) -> str:
    if amount < 300:
        return "hour"
    if currency == "BRL":
        return "year" if amount >= 150_000 else "month"
    return "year" if amount >= 20_000 else "month"


def _monthly_brl(amount: float, currency: str, period: str) -> float | None:
    rate = RULES.currency.rates_to_brl.get(currency)
    factor = RULES.currency.period_to_month.get(period)
    if rate is None or factor is None:
        return None
    return amount * rate * factor


def extract_salary(text: str | None) -> Salary | None:
    """The first plausible salary in ``text`` (None when there is none)."""
    if not text:
        return None
    candidates = [(m, False) for m in _AMOUNT_RE.finditer(text)] + [(m, True) for m in _AMOUNT_AFTER_RE.finditer(text)]
    candidates.sort(key=lambda c: c[0].start())
    for m, _after in candidates:
        if m.groupdict().get("mult"):
            continue  # "$50M", "R$ 10 milhões"
        start, end = m.start(), m.end()
        # Funding/scale words veto only within the same sentence; salary context may also come from the
        # previous line (a "Remuneração" heading).
        s_start = max(text.rfind(sep, 0, start) for sep in (". ", "\n", "; ", "! ", "? ")) + 1
        s_end_candidates = [i for i in (text.find(sep, end) for sep in (". ", "\n", "; ")) if i != -1]
        s_end = min(s_end_candidates) if s_end_candidates else len(text)
        if _REJECT.search(text[s_start:start] + " " + text[end:s_end]):
            continue
        prev_line_start = text.rfind("\n", 0, max(0, s_start - 1)) + 1
        before = text[prev_line_start:start][-120:]
        after = text[end : end + 40]
        cur_raw = (m.group("cur") or "").lower()
        currency = _CURRENCY_CODES.get(cur_raw, cur_raw.upper())
        a = parse_number(m.group("a"), m.group("ak"))
        b = parse_number(m.group("b"), m.group("bk") or m.group("ak")) if m.group("b") else a
        lo, hi = min(a, b), max(a, b)
        is_range = m.group("b") is not None
        has_context = bool(_CONTEXT.search(before + " " + text[start:end] + " " + after))
        if not has_context and not (is_range and currency != "USD"):
            continue  # a lonely "$" or "R$" amount without salary context
        period = _period_near(text, start, end)
        stated = period is not None
        period = period or _infer_period(hi, currency)
        monthly = _monthly_brl(hi, currency, period)
        if monthly is None or not (MONTHLY_BRL_MIN <= monthly <= MONTHLY_BRL_MAX):
            continue
        return Salary(lo, hi, currency, period, (start, end), stated)
    return None
