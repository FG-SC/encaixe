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


def _map_points(session: Session) -> tuple[list[dict], np.ndarray, list[int]]:
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
