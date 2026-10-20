"""Money conversion with the approximate rates of RULES.currency (trap 7). Always flagged when used."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import RULES


@dataclass(frozen=True)
class Converted:
    value: float
    approx_fx: bool  # True when a currency conversion happened ("câmbio aproximado")


def convert(
    amount: float | None, currency: str | None, period: str | None, to_currency: str, to_period: str = "month"
) -> Converted | None:
    """Convert an amount per period to another currency and period. None when it cannot be converted."""
    if amount is None:
        return None
    cur = (currency or RULES.currency.base).upper()
    rates = RULES.currency.rates_to_brl
    if cur not in rates or to_currency.upper() not in rates:
        return None
    factors = RULES.currency.period_to_month
    src = factors.get(period or "month")
    dst = factors.get(to_period)
    if src is None or dst is None:
        return None
    monthly_brl = amount * rates[cur] * src
    value = monthly_brl / rates[to_currency.upper()] / dst
    return Converted(value, approx_fx=cur != to_currency.upper())
