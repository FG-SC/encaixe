"""Market map: 2D projection of open jobs (PCA → t-SNE; umap is forbidden), KMeans clusters labelled by
taxonomy domain, and the candidate's star (similarity-weighted mean of the most similar open jobs).
"""

from __future__ import annotations

import logging
from collections import Counter

import numpy as np
from sqlmodel import Session, select

from app import clock
from app import taxonomy as tax_mod
from app.config import RULES
from app.db import from_blob
from app.jobs import bump_jobs_version, ensure_job_vectors, latest_version
from app.models import Job, Setting

log = logging.getLogger(__name__)

PROJECTION_KEY = "projection"


def _scale01(xy: np.ndarray) -> np.ndarray:
    lo, hi = xy.min(axis=0), xy.max(axis=0)
    span = np.where(hi - lo == 0, 1, hi - lo)
    return (xy - lo) / span


def project_points(vectors: np.ndarray) -> np.ndarray:
    """(n, d) → (n, 2) in [0, 1]. t-SNE for n ≥ min_points_tsne, PCA otherwise."""
    from sklearn.decomposition import PCA

    n = vectors.shape[0]
    rules = RULES.projection
    if n == 0:
        return np.zeros((0, 2))
    if n < 3:
        return np.full((n, 2), 0.5) if n == 1 else np.array([[0.0, 0.5], [1.0, 0.5]])
    if n < rules.min_points_tsne or rules.method == "pca":
        return _scale01(PCA(n_components=2, random_state=rules.random_state).fit_transform(vectors))
    from sklearn.manifold import TSNE

    reduced = PCA(
        n_components=min(rules.pca_dim, n - 1, vectors.shape[1]), random_state=rules.random_state
    ).fit_transform(vectors)
    tsne = TSNE(
        n_components=2,
        init="pca",
        random_state=rules.random_state,
        perplexity=min(rules.perplexity, (n - 1) / 3),
        learning_rate="auto",
    )
    return _scale01(tsne.fit_transform(reduced))


def compute_projection(session: Session) -> dict:
    """Recompute x, y and cluster of every open job and store the cluster labels."""
    from sklearn.cluster import KMeans

    tax = tax_mod.load()
    ensure_job_vectors(session, only_open=True)
    jobs = session.exec(select(Job).where(Job.status == "open")).all()
    rows: list[tuple[Job, np.ndarray]] = []
    for job in jobs:
        v = latest_version(session, job.id)  # type: ignore[arg-type]
        vec = from_blob(v.embedding) if v and v.embedding else None
        if vec is not None:
            rows.append((job, vec))
    if not rows:
        return {"n": 0, "clusters": []}
    matrix = np.vstack([r[1] for r in rows])
    xy = project_points(matrix)
    k = max(1, min(RULES.projection.clusters, len(rows)))
    labels = (
        KMeans(n_clusters=k, n_init=4, random_state=RULES.projection.random_state).fit_predict(matrix)
        if len(rows) > 1
        else np.zeros(1, dtype=int)
    )
    clusters = []
    for c in range(k):
        idx = [i for i in range(len(rows)) if labels[i] == c]
        if not idx:
            continue
        domains = Counter(d for i in idx for d in (rows[i][0].domains or ["outros"])[:1])
        skills = Counter(s for i in idx for s in (rows[i][0].requires or {}).get("skills_must", []))
        domain = domains.most_common(1)[0][0]
        top = [s for s, _ in skills.most_common(3)]
        clusters.append(
            {
                "id": c,
                "domain": domain,
                "n": len(idx),
                "label": tax.domain_info.get(domain, {}).get("label_pt", domain),
                "top_skills": [tax.label(s) for s in top],
                "cx": float(xy[idx, 0].mean()),
                "cy": float(xy[idx, 1].mean()),
            }
        )
    for i, (job, _) in enumerate(rows):
        job.x, job.y, job.cluster = float(xy[i, 0]), float(xy[i, 1]), int(labels[i])
        session.add(job)
    info = {
        "computed_at": clock.now().isoformat(),
        "method": RULES.projection.method if len(rows) >= RULES.projection.min_points_tsne else "pca",
        "n": len(rows),
        "clusters": clusters,
    }
    row = session.get(Setting, PROJECTION_KEY)
    if row is None:
        session.add(Setting(key=PROJECTION_KEY, value=info))
    else:
        row.value = info
        session.add(row)
    bump_jobs_version(session)
    log.info("projection: %d jobs, %d clusters", len(rows), len(clusters))
    return info


def star_position(
    vec: np.ndarray, matrix: np.ndarray, xy: np.ndarray, k: int | None = None
) -> tuple[float, float, list[int]]:
    """Similarity-weighted mean of the (x, y) of the k most similar jobs (indices returned too)."""
    if matrix.shape[0] == 0:
        return 0.5, 0.5, []
    k = min(k or RULES.projection.knn_star, matrix.shape[0])
    sims = matrix @ vec
    top = np.argsort(-sims)[:k]
    w = np.clip(sims[top], 0, None) + 1e-6
    x, y = (xy[top] * w[:, None]).sum(axis=0) / w.sum()
    return float(x), float(y), [int(i) for i in top]
