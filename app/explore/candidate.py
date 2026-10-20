"""Candidate side of Explorar, starting with the Raio-X (the first screen after onboarding)."""

from __future__ import annotations

import numpy as np
from sqlmodel import Session

from app import geo as geo_mod
from app import taxonomy as tax_mod
from app import texts
from app.config import RULES
from app.embeddings.projection import PROJECTION_KEY, star_position
from app.models import Job, Setting
from app.ranking.counterfactual import unlock_counts
from app.ranking.index import job_index
from app.ranking.service import rank_for_candidate

SIGNATURE = "feito no Encaixe — vagas com regras abertas"


def explore_data(session: Session, candidate_id: int) -> dict:
    """Explorar (spec 12): where the jobs are, which skill unlocks most, salaries, revealed preferences, timeline."""
    from collections import Counter

    from sqlmodel import col, select

    from app.events.status import candidate_judgments
    from app.models import ProfileRevision
    from app.money import convert
    from app.ranking.index import features_for_revision
    from app.ranking.pair import evaluate_requirements, good_fit, hard_filters

    tax = tax_mod.load()
    geo = geo_mod.load()
    xray = xray_data(session, candidate_id)
    result = rank_for_candidate(session, candidate_id, ranker="static-v1")
    c = result.meta["candidate"]
    idx = job_index(session)
    good_ids = {it.item_id for it in result.items if it.good_fit.is_good_fit}
    eligible_ids = {it.item_id for it in result.items}
    # where the jobs are (remote counted apart)
    per_city: dict[str, Counter[str]] = {}
    remote: Counter[str] = Counter()
    for j in idx.jobs:
        status = "good_fit" if j.job_id in good_ids else ("eligible" if j.job_id in eligible_ids else "filtered")
        if j.arrangement == "remote":
            remote[status] += 1
        elif j.city_id in geo.cities:
            per_city.setdefault(j.city_id, Counter())[status] += 1  # type: ignore[index]
    cities = [
        {
            "city_id": cid,
            "name": geo.cities[cid].name,
            "lat": geo.cities[cid].lat,
            "lon": geo.cities[cid].lon,
            "total": sum(cnt.values()),
            **dict(cnt),
        }
        for cid, cnt in per_city.items()
    ]
    # which skills unlock most (top 10, with example jobs)
    unlock = unlock_counts(c, idx.jobs)
    by_id = {j.job_id: j for j in idx.jobs}
    examples: dict[str, list[str]] = {}
    from app.ranking.counterfactual import with_skills

    for skill, _ in unlock.most_common(10):
        cs = with_skills(c, [skill])
        hits = []
        for j in idx.jobs:
            if j.job_id in good_ids or skill not in j.must:
                continue
            r = evaluate_requirements(cs, j)
            if good_fit(cs, j, r, not hard_filters(cs, j, r, "candidate")).is_good_fit:
                hits.append(j.title)
        examples[skill] = hits[:3]
    unlock_rows = [
        {"skill": s, "label": tax.label(s), "jobs": n, "examples": examples.get(s, [])}
        for s, n in unlock.most_common(10)
    ]
    # salaries of good fits vs the declared minimum (approximate FX flagged)
    salaries = []
    for jid in good_ids:
        j = by_id.get(jid)
        if j is None:
            continue
        lo = convert(j.offers.comp_min, j.offers.currency, j.offers.period, c.wants.currency, c.wants.period)
        hi = convert(j.offers.comp_max, j.offers.currency, j.offers.period, c.wants.currency, c.wants.period)
        if hi or lo:
            salaries.append(
                {
                    "job_id": jid,
                    "title": j.title,
                    "min": round((lo or hi).value),  # type: ignore[union-attr]
                    "max": round((hi or lo).value),
                    "approx_fx": bool((hi or lo).approx_fx),
                }
            )  # type: ignore[union-attr]
    # revealed preferences: reasons given when swiping left
    lefts = [e for e in candidate_judgments(session, candidate_id) if e.type == "swipe_left"]
    reasons = Counter(e.reason or "none" for e in lefts)
    rejected_comp = []
    for e in lefts:
        j = by_id.get(e.item_id)
        if e.reason == "salary" and j is not None:
            conv = convert(
                j.offers.comp_max if j.offers.comp_max is not None else j.offers.comp_min,
                j.offers.currency,
                j.offers.period,
                c.wants.currency,
                c.wants.period,
            )
            if conv:
                rejected_comp.append(conv.value)
    # profile timeline: good fits per revision (each revision ranked against today's open jobs)
    timeline = []
    for rev in session.exec(
        select(ProfileRevision).where(ProfileRevision.candidate_id == candidate_id).order_by(col(ProfileRevision.ts))
    ).all():
        from app.models import Candidate

        cand = session.get(Candidate, candidate_id)
        if rev.embedding is None or cand is None:
            continue
        cf = features_for_revision(session, cand, rev)
        n_good = 0
        for j in idx.jobs:
            r = evaluate_requirements(cf, j)
            if good_fit(cf, j, r, not hard_filters(cf, j, r, "candidate")).is_good_fit:
                n_good += 1
        timeline.append({"ts": rev.ts.isoformat(), "kind": rev.kind, "good_fit": n_good})
    return {
        "map": xray["map"],
        "star": xray["star"],
        "cities": cities,
        "remote": dict(remote),
        "unlock": unlock_rows,
        "salaries": {
            "jobs": salaries,
            "comp_min": c.wants.comp_min,
            "currency": c.wants.currency,
            "period": c.wants.period,
        },
        "revealed": {
            "reasons": [
                {"reason": r, "label": texts.REASON_LABELS_CANDIDATE.get(r, "sem motivo"), "count": n}
                for r, n in reasons.most_common()
            ],
            "salary_rejected_median": float(np.median(rejected_comp)) if rejected_comp else None,
            "declared_min": c.wants.comp_min,
            "text": _revealed_text(reasons, rejected_comp, c.wants.comp_min),
        },
        "timeline": timeline,
    }


def _revealed_text(reasons, rejected_comp, declared) -> str | None:  # type: ignore[no-untyped-def]
    n = reasons.get("salary", 0)
    if not n or not rejected_comp:
        return None
    median = float(np.median(rejected_comp))
    sentence = (
        f"Você recusou {n} vaga(s) por salário; a mediana do teto dessas vagas era {texts.fmt_money(median, 'BRL')}."
    )
    if declared:
        sentence += f" Seu mínimo declarado é {texts.fmt_money(declared, 'BRL')}."
        if median >= declared:
            sentence += " Talvez seu mínimo real seja maior do que o declarado."
    return sentence


def _map_points(session: Session) -> tuple[list[dict], np.ndarray, list[int]]:
    idx = job_index(session)
    if idx.jobs and all(
        (session.get(Job, j.job_id) or Job(source="", source_id="", title="")).x is None for j in idx.jobs
    ):
        # The map was never computed (jobs loaded some other way): compute it now, so the Raio-X works on first use.
        from app.embeddings.projection import compute_projection

        compute_projection(session)
        session.flush()
        idx = job_index(session)
    pts, xy, rows = [], [], []
    for i, j in enumerate(idx.jobs):
        job = session.get(Job, j.job_id)
        if job is None or job.x is None:
            continue
        pts.append(
            {
                "job_id": j.job_id,
                "x": job.x,
                "y": job.y,
                "cluster": job.cluster,
                "domain": (job.domains or [None])[0],
                "title": job.title,
            }
        )
        xy.append((job.x, job.y))
        rows.append(i)
    return pts, np.array(xy, dtype=float).reshape(-1, 2), rows


def xray_data(session: Session, candidate_id: int) -> dict:
    tax = tax_mod.load()
    result = rank_for_candidate(session, candidate_id, ranker="static-v1")
    c = result.meta["candidate"]
    good = [it for it in result.items if it.good_fit.is_good_fit]
    idx = job_index(session)
    unlock = unlock_counts(c, idx.jobs)
    top = [{"skill": s, "label": tax.label(s), "jobs": n} for s, n in unlock.most_common(3)]
    points, xy, rows = _map_points(session)
    good_ids = {it.item_id for it in good}
    filtered_ids = {f.item_id for f in result.filtered}
    for p in points:
        p["good_fit"] = p["job_id"] in good_ids
        p["filtered"] = p["job_id"] in filtered_ids
    star = None
    if rows:
        x, y, nearest = star_position(c.emb, idx.emb[rows], xy)
        star = {
            "x": x,
            "y": y,
            "nearest": [points[k]["job_id"] for k in nearest],
            "rule": f"Sua estrela fica na média das {RULES.projection.knn_star} vagas mais parecidas com seu "
            "perfil, pesada pela similaridade.",
        }
    proj = session.get(Setting, PROJECTION_KEY)
    city = geo_mod.load().get_city(c.city_id)
    understood = {
        "headline": c.headline,
        "seniority_label": texts.seniority_label(c.level),
        "city": city.name if city else None,
        "proven": [tax.label(s) for s in sorted(c.proven)],
        "proven_recent": [tax.label(s) for s in sorted(c.proven_recent)],
        "listed": [tax.label(s) for s in sorted(c.listed)],
        "domains": [tax.domain_info.get(d, {}).get("label_pt", d) for d in sorted(c.domains)],
        "languages": [{"language": texts.LANGUAGE_LABELS.get(k, k), "rank": v} for k, v in c.languages.items()],
    }
    return {
        "understood": understood,
        "good_fit_count": len(good),
        "n_open": result.meta["n_total"],
        "n_eligible": result.meta["n_eligible"],
        "n_filtered": result.meta["n_filtered"],
        "top_unlock": top,
        "star": star,
        "map": {"points": points, "clusters": (proj.value or {}).get("clusters", []) if proj else []},
        "good_fit_rule": f"Bom encaixe: passa nos filtros, comprova ≥ {int(RULES.good_fit.must_share * 100)}% dos "
        f"obrigatórios e está a até {RULES.good_fit.max_seniority_gap} nível de senioridade.",
        "share_card": {
            "star": star and {"x": star["x"], "y": star["y"]},
            "good_fit_count": len(good),
            "top_unlock": [t["label"] for t in top],
            "signature": SIGNATURE,
            "aspect": "4:5",
            "personal_data": False,
        },
    }
