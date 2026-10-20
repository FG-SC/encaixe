"""From raw values to positions (spec 7.3). Position 1 = best.

- Ties: sorted best-first, a group starts at value v0 and takes the following values while |v − v0| ≤
  precision (exact equality without a precision); every member gets the group's mean position.
- Unknown / not applicable: imputed with the median of the known values (tuples: the median element in
  lexicographic order), then ranked with everyone else — so it "stays in the middle"; with no known value,
  everyone gets the middle position.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

Value = float | tuple[float, ...] | None


def _median(known: list) -> object:
    if isinstance(known[0], tuple):
        ordered = sorted(known)
        return ordered[(len(ordered) - 1) // 2]
    return float(np.median(np.asarray(known, dtype=float)))


def _close(a: object, b: object, precision: float | None) -> bool:
    if isinstance(a, tuple):
        return all(abs(x - y) <= 1e-9 for x, y in zip(a, b, strict=True))  # type: ignore[arg-type]
    if precision:
        return abs(float(a) - float(b)) <= precision + 1e-12  # type: ignore[arg-type]
    return abs(float(a) - float(b)) <= 1e-12  # type: ignore[arg-type]


def imputed_values(values: Sequence[Value]) -> tuple[list[object], object | None]:
    known = [v for v in values if v is not None]
    if not known:
        return list(values), None
    med = _median(known)
    return [med if v is None else v for v in values], med


def positions(values: Sequence[Value], better: str, precision: float | None = None) -> np.ndarray:
    """Mean positions (1 = best) with ties within ``precision`` and unknowns at the median."""
    n = len(values)
    if n == 0:
        return np.zeros(0)
    full, med = imputed_values(values)
    if med is None:  # nothing known: everyone in the middle
        return np.full(n, (n + 1) / 2)
    reverse = better == "max"
    order = sorted(range(n), key=lambda i: full[i], reverse=reverse)  # type: ignore[arg-type,return-value]
    pos = np.zeros(n)
    k = 0
    while k < n:
        v0 = full[order[k]]
        g = k + 1
        while g < n and _close(full[order[g]], v0, precision):
            g += 1
        mean = (k + 1 + g) / 2  # mean of ranks k+1 … g
        for idx in order[k:g]:
            pos[idx] = mean
        k = g
    return pos
