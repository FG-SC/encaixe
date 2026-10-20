"""Drift experiment (spec 13): the preference of simulated users changes on a known day.

In memory (no database writes). Users have a hidden utility (the oracle). On ``drift_day`` half of them change
their preferred area: half of those also save a relevant profile revision that day (new dated experience in
the new area), the other half change taste only. Each day every user sees the top of their list (and swipes
the first cards by the oracle, with noise); quality is measured on the full top 10 against the CURRENT oracle.
"""

from __future__ import annotations

import dataclasses
import random
from datetime import date, timedelta

import numpy as np
from sqlmodel import Session

from app import clock
from app.config import RULES, Rules
from app.embeddings import embed_texts
from app.embeddings.texts import candidate_embed_text, candidate_title_texts
from app.eval.metrics import ndcg_gains
from app.ranking.engine import rank
from app.ranking.features import candidate_features
from app.ranking.feedback import Judgment, history_values
from app.ranking.index import job_index
from app.ranking.service import pairs_for_candidate
from app.synth.personas import make_personas, with_revision
from app.synth.simulate import LIKE_THRESHOLD, utility


def _features(profile, today: date):  # type: ignore[no-untyped-def]
    emb = embed_texts([candidate_embed_text(profile)])[0]
    titles = embed_texts(candidate_title_texts(profile))
    t = titles.mean(axis=0)
    t = t / (np.linalg.norm(t) or 1.0)
    return candidate_features(profile, emb, t, today)


def run_drift(
    session: Session,
    users: int = 30,
    days: int = 40,
    drift_day: int | None = None,
    seed: int = 7,
    swipes_per_day: int = 3,
) -> dict:
    idx = job_index(session)
    if not idx.jobs:
        return {"error": "sem vagas abertas"}
    drift_day = drift_day if drift_day is not None else days // 2
    today = clock.today()
    sim_start = today - timedelta(days=days)
    rng = random.Random(seed)
    personas = make_personas(users, seed, today, sim_start, days, revision_share=0.0)
    drifters = rng.sample(range(users), k=users // 2)
    with_rev = set(drifters[: len(drifters) // 2])
    for i in drifters:
        with_revision(rng, personas[i], drift_day, sim_start)
        if i not in with_rev:  # taste changes, profile does not
            personas[i].revised_profile = None
    feats_before = [_features(p.profile, today) for p in personas]
    feats_after = {i: _features(personas[i].revised_profile, today) for i in with_rev}  # type: ignore[arg-type]

    fb = RULES.feedback
    variants: dict[str, tuple[str, Rules]] = {
        "static-v1": ("static-v1", RULES),
        "feedback-v1": ("feedback-v1", RULES),
        "feedback-v1 sem decaimento": (
            "feedback-v1",
            dataclasses.replace(RULES, feedback=dataclasses.replace(fb, half_life_days=1e9)),
        ),
        "feedback-v1 sem desconto por revisão": (
            "feedback-v1",
            dataclasses.replace(RULES, feedback=dataclasses.replace(fb, gamma=1.0)),
        ),
    }
    curves: dict[str, dict[str, list[float]]] = {}
    for name, (ranker, rules) in variants.items():
        srng = random.Random(seed + 101)
        history: list[list[tuple[int, bool, np.ndarray, int | None, str | None]]] = [[] for _ in personas]
        prec_all, prec_drift, ndcg_all = [], [], []
        for day in range(days):
            p_day, p_drift, n_day = [], [], []
            for u, persona in enumerate(personas):
                revised = u in with_rev and day >= drift_day
                c = feats_after[u] if revised else feats_before[u]
                domains = (
                    persona.taste.drift_domains
                    if (persona.taste.drift_day is not None and day >= drift_day)
                    else persona.taste.domains
                )
                pairs = pairs_for_candidate(c, idx.jobs, idx.emb, idx.title_emb)
                if ranker == "feedback-v1" and len(history[u]) >= rules.feedback.k_min:
                    judgments = []
                    for d0, liked, vec, company, reason in history[u]:
                        n_rev = 1 if (u in with_rev and d0 < drift_day <= day) else 0
                        w = 0.5 ** ((day - d0) / rules.feedback.half_life_days) * rules.feedback.gamma**n_rev
                        lam = 0.0 if liked else rules.feedback.lambda_candidate.get(reason or "none", 0.0)
                        judgments.append(Judgment(liked, w, lam, vec, "", company, False, 0))
                    items = np.vstack([p.extra["job"].emb for p in pairs])
                    values, _ = history_values(judgments, items, [None] * len(pairs), rules)
                    for i, p in enumerate(pairs):
                        p.history = float(values[i])
                result = rank(pairs, side="candidate", ranker=ranker, rules=rules)
                if not result.items:
                    continue
                gains = {it.item_id: utility(domains, c, it.extra["job"], it.req) for it in result.items}
                top = result.items[:10]
                prec = float(np.mean([gains[it.item_id] >= LIKE_THRESHOLD for it in top]))
                p_day.append(prec)
                if persona.taste.drift_day is not None:
                    p_drift.append(prec)
                n_day.append(ndcg_gains([gains[it.item_id] for it in top], list(gains.values()), 10))
                for it in result.items[:swipes_per_day]:
                    u_val = gains[it.item_id] + srng.gauss(0, persona.taste.noise)
                    liked = u_val >= LIKE_THRESHOLD
                    j = it.extra["job"]
                    reason = (
                        None
                        if liked
                        else ("role_area" if max((domains.get(d, 0.1) for d in j.domains), default=0.3) < 0.3 else None)
                    )
                    history[u].append((day, liked, j.emb, j.company_id, reason))
            prec_all.append(float(np.mean(p_day)) if p_day else 0.0)
            prec_drift.append(float(np.mean(p_drift)) if p_drift else 0.0)
            ndcg_all.append(float(np.mean(n_day)) if n_day else 0.0)
        curves[name] = {
            "precision@10": prec_all,
            "precision@10 (quem mudou)": prec_drift,
            "ndcg@10": ndcg_all,
            "recovery_days": _recovery(prec_drift, drift_day),
        }
    return {
        "users": users,
        "days": days,
        "drift_day": drift_day,
        "drifters": len(drifters),
        "drifters_with_revision": len(with_rev),
        "curves": curves,
        "jobs": len(idx.jobs),
        "evaluated_at": clock.now().isoformat(),
    }


def _recovery(curve: list[float], drift_day: int, window: int = 7, share: float = 0.9) -> int | None:
    """Days after the drift until the drifters' precision is back to `share` of its pre-drift level."""
    before = curve[max(0, drift_day - window) : drift_day]
    if not before:
        return None
    target = share * float(np.mean(before))
    for k, v in enumerate(curve[drift_day:]):
        if v >= target:
            return k
    return None
