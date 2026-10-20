"""Ranking metrics."""

from __future__ import annotations

import math

import numpy as np


def mrr(ranks: list[int]) -> float:
    return float(np.mean([1.0 / r for r in ranks])) if ranks else 0.0


def recall_at(ranks: list[int], k: int) -> float:
    return float(np.mean([r <= k for r in ranks])) if ranks else 0.0


def ndcg_single(ranks: list[int], k: int = 10) -> float:
    """One relevant item per query: DCG = 1/log2(1 + rank) when rank ≤ k (ideal = 1)."""
    return float(np.mean([1.0 / math.log2(1 + r) if r <= k else 0.0 for r in ranks])) if ranks else 0.0


def auc(liked: list[int], disliked: list[int]) -> float | None:
    """P(a liked item is ranked above a disliked one); ties count half."""
    if not liked or not disliked:
        return None
    wins = sum((lr < dr) + 0.5 * (lr == dr) for lr in liked for dr in disliked)
    return wins / (len(liked) * len(disliked))


def ndcg_gains(gains_in_order: list[float], all_gains: list[float], k: int = 10) -> float:
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains_in_order[:k]))
    ideal = sum(g / math.log2(i + 2) for i, g in enumerate(sorted(all_gains, reverse=True)[:k]))
    return dcg / ideal if ideal > 0 else 0.0


def gini(values: list[float]) -> float:
    """0 = perfectly even exposure, → 1 = all exposure on one item."""
    x = np.sort(np.asarray(values, dtype=float))
    if x.size == 0 or x.sum() == 0:
        return 0.0
    n = x.size
    return float((2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum()))
