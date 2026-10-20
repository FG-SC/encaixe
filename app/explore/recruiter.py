"""Recruiter side of Explorar (spec 12): funnel, bottleneck, candidate pool, market benchmark, reasons, congestion.

Privacy (spec 10): candidates who are not visible are excluded from EVERY aggregate (otherwise they would leak
by inference), and every count below RULES.privacy.k_anon renders as "<k"; map cells below k are not shown.
"""

from __future__ import annotations

import dataclasses
from collections import Counter

import numpy as np
from sqlmodel import Session, col, select

from app import geo as geo_mod
from app import taxonomy as tax_mod
from app import texts
from app.config import RULES
from app.events import applicants
from app.models import InteractionEvent, Job, Match
from app.money import convert
from app.ranking.pair import evaluate_requirements, good_fit, hard_filters
from app.ranking.service import job_features_for, rank_for_job

K = RULES.privacy.k_anon


def kc(n: int) -> str:
    return texts.k_anon_count(n)


def funnel(session: Session, job_id: int) -> dict:
    tax = tax_mod.load()
    j = job_features_for(session, job_id)
    apps = applicants(session, job_id)
    result = rank_for_job(session, job_id, applicants=apps, ranker="static-v1")
    eligible = result.items
    # visible = everyone except candidates who chose not to appear (they never enter an aggregate)
    visible_ids = {it.item_id for it in eligible} | {
        f.item_id for f in result.filtered if all(r.code != "not_visible" for r in f.reasons)
    }
    n_visible = len(visible_ids)
    good = [it for it in eligible if it.good_fit.is_good_fit]
    rec_events = session.exec(
        select(InteractionEvent).where(
            InteractionEvent.actor_type == "recruiter", InteractionEvent.context_job_id == job_id
        )
    ).all()
    seen = {e.item_id for e in rec_events if e.type == "impression" and e.item_id in apps and e.item_id in visible_ids}
    latest: dict[int, str] = {}
    for e in sorted(rec_events, key=lambda e: (e.ts, e.id or 0)):
        if e.type in ("swipe_left", "swipe_right"):
            latest[e.item_id] = e.type
    advanced = {cid for cid, t in latest.items() if t == "swipe_right" and cid in visible_ids}
    rejected = {cid for cid, t in latest.items() if t == "swipe_left" and cid in visible_ids}
    matches = session.exec(select(Match.candidate_id).where(Match.job_id == job_id)).all()
    stages = [
        ("visible", "perfis visíveis", n_visible),
        ("eligible", "passam nos filtros", len(eligible)),
        ("good_fit", "bom encaixe", len(good)),
        ("applied", "se candidataram", len(apps & visible_ids)),
        ("seen", "candidaturas vistas", len(seen)),
        ("advanced", "avançaram (swipe à direita)", len(advanced)),
        ("not_advanced", "não avançaram", len(rejected)),
        ("matched", "encaixes", len([m for m in matches if m in visible_ids])),
    ]
    # per requirement: how many eligible candidates prove it, and the bottleneck
    pool = [p.extra["candidate"] for p in _pairs_of(eligible)]
    must_rows = []
    base_good = len(good)
    for skill in j.must:
        proving = 0
        for c in pool:
            req = evaluate_requirements(c, j)
            if any(st.skill == skill and st.credit == 1.0 for st in req.must_status):
                proving += 1
        relaxed = dataclasses.replace(
            j,
            must=[s for s in j.must if s != skill],
            must_nontransversal=[s for s in j.must_nontransversal if s != skill],
        )
        gained = 0
        for c in pool:
            req = evaluate_requirements(c, relaxed)
            if good_fit(c, relaxed, req, not hard_filters(c, relaxed, req, "recruiter")).is_good_fit:
                gained += 1
        must_rows.append(
            {
                "skill": skill,
                "label": tax.label(skill),
                "proving": kc(proving),
                "good_fit_without_it": kc(gained),
                "gain": gained - base_good,
            }
        )
    bottleneck = max(must_rows, key=lambda r: r["gain"], default=None)
    filters = Counter(r.code for f in result.filtered for r in f.reasons if r.code != "not_visible")
    return {
        "job_id": job_id,
        "stages": [{"code": c, "label": label, "count": kc(n)} for c, label, n in stages],
        "requirements": [{k: v for k, v in r.items() if k != "gain"} for r in must_rows],
        "bottleneck": None
        if not bottleneck or bottleneck["gain"] <= 0
        else {
            "skill": bottleneck["skill"],
            "label": bottleneck["label"],
            "text": f"Sem exigir {bottleneck['label']}, {kc(base_good + bottleneck['gain'])} perfis seriam bom "
            f"encaixe (hoje: {kc(base_good)}).",
        },
        "filters": [
            {"code": code, "title": texts.FILTER_TITLES.get(code, code), "count": kc(n)}
            for code, n in filters.most_common()
        ],
        "k_anon": K,
        "note": f'Contagens menores que {K} aparecem como "{texts.below_k_label()}"; perfis invisíveis não entram.',
    }


def _pairs_of(items: list) -> list:  # type: ignore[type-arg]
    return [it for it in items if "candidate" in it.extra]


def explore(session: Session, job_id: int) -> dict:
    geo = geo_mod.load()
    j = job_features_for(session, job_id)
    job = session.get(Job, job_id)
    result = rank_for_job(session, job_id, ranker="static-v1")
    pool = [it.extra["candidate"] for it in result.items]
    # candidate pool on the market map: each candidate's star, aggregated in a grid; cells below k hidden
    from app.embeddings.projection import star_position
    from app.ranking.index import job_index

    idx = job_index(session)
    placed = [(i, session.get(Job, f.job_id)) for i, f in enumerate(idx.jobs)]
    placed = [(i, jb) for i, jb in placed if jb is not None and jb.x is not None]
    rows = [i for i, _ in placed]
    xy = np.array([[jb.x, jb.y] for _, jb in placed])  # type: ignore[union-attr]
    grid = 8
    cells: Counter[tuple[int, int]] = Counter()
    if rows:
        for c in pool:
            x, y, _ = star_position(c.emb, idx.emb[rows], xy)
            cells[(min(grid - 1, int(x * grid)), min(grid - 1, int(y * grid)))] += 1
    shown_cells = [
        {"gx": gx, "gy": gy, "x": (gx + 0.5) / grid, "y": (gy + 0.5) / grid, "count": n}
        for (gx, gy), n in cells.items()
        if n >= K
    ]
    by_city = Counter(c.city_id for c in pool if c.city_id)
    cities = [
        {
            "city_id": cid,
            "name": geo.cities[cid].name,
            "lat": geo.cities[cid].lat,
            "lon": geo.cities[cid].lon,
            "count": n,
        }
        for cid, n in by_city.items()
        if n >= K and cid in geo.cities
    ]
    # market benchmark: the most similar open market jobs
    market = [(i, f) for i, f in enumerate(idx.jobs) if f.origin == "market"]
    bench = []
    if market:
        sims = np.array([idx.emb[i] @ j.emb for i, _ in market])
        for k in np.argsort(-sims)[:20]:
            f = market[int(k)][1]
            amount = f.offers.comp_max if f.offers.comp_max is not None else f.offers.comp_min
            conv = convert(amount, f.offers.currency, f.offers.period, "BRL", "month")
            bench.append(
                {
                    "job_id": f.job_id,
                    "title": f.title,
                    "similarity": round(float(sims[int(k)]), 3),
                    "arrangement": f.arrangement,
                    "comp_brl_month": round(conv.value) if conv else None,
                    "approx_fx": bool(conv and conv.approx_fx),
                }
            )
    comps = [b["comp_brl_month"] for b in bench if b["comp_brl_month"]]
    own = convert(j.offers.comp_max, j.offers.currency, j.offers.period, "BRL", "month")
    # candidates' own left-swipe reasons on this job (private one by one; aggregated only with ≥ k people)
    reasons = Counter(
        e.reason or "none"
        for e in session.exec(
            select(InteractionEvent).where(
                InteractionEvent.actor_type == "candidate",
                InteractionEvent.item_id == job_id,
                InteractionEvent.type == "swipe_left",
            )
        ).all()
    )
    total = sum(reasons.values())
    reason_rows = (
        [
            {"reason": r, "label": texts.REASON_LABELS_CANDIDATE.get(r, "sem motivo"), "count": kc(n)}
            for r, n in reasons.most_common()
        ]
        if total >= K
        else []
    )
    # congestion: are this job's top-5 also in the top-5 of the other platform jobs?
    top5 = [it.item_id for it in result.items[:5]]
    shared = Counter()
    for other in session.exec(
        select(Job).where(Job.origin == "platform", Job.status == "open", col(Job.id) != job_id)
    ).all():
        r = rank_for_job(session, other.id, ranker="static-v1")  # type: ignore[arg-type]
        for it in r.items[:5]:
            if it.item_id in top5:
                shared[it.item_id] += 1
    return {
        "job": {
            "id": job_id,
            "title": job.title if job else "",
            "x": job.x if job else None,
            "y": job.y if job else None,
        },
        "pool_size": kc(len(pool)),
        "pool_map": {"grid": grid, "cells": shown_cells, "hidden_cells": len([n for n in cells.values() if n < K])},
        "cities": cities,
        "benchmark": {
            "jobs": bench,
            "n_with_salary": len(comps),
            "p25": float(np.percentile(comps, 25)) if comps else None,
            "p50": float(np.percentile(comps, 50)) if comps else None,
            "p75": float(np.percentile(comps, 75)) if comps else None,
            "own_comp_brl_month": round(own.value) if own else None,
            "arrangements": dict(Counter(b["arrangement"] or "não informada" for b in bench)),
        },
        "candidate_reasons": {
            "total": kc(total),
            "rows": reason_rows,
            "note": f"Mostrado só com pelo menos {K} recusas; o motivo de cada pessoa é privado.",
        },
        "congestion": {
            "top5_in_other_lists": kc(sum(1 for v in shared.values() if v > 0)),
            "text": "Quantos dos seus 5 primeiros perfis também estão entre os 5 primeiros de outras "
            "vagas da plataforma (eles podem estar disputados).",
        },
        "k_anon": K,
    }
