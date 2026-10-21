"""encaixe bench (spec 3): peak RSS of five steps, each in a fresh subprocess sampled by psutil.

1. start and warm the server (model loaded, one deck ranked) — budget 700 MB steady state;
2. embed 1,000 jobs; 3. 2D projection; 4. eval drift; 5. ingest --all against recorded responses with the
LLM off — batch budget 1 GB each. Steps run one after the other (never two heavy processes at once).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import psutil

SERVER_BUDGET_MB = 700
BATCH_BUDGET_MB = 1000

STEP_SERVER = """
from fastapi.testclient import TestClient
from sqlmodel import select
from app.api.main import create_app
from app.db import session_scope
from app.models import Candidate
with TestClient(create_app(front_dist=None)) as c:
    c.get("/api/health")
    with session_scope() as s:
        cand = s.exec(select(Candidate).where(Candidate.current_revision_id.is_not(None))).first()
    if cand is not None:
        c.post("/api/dev/login", json={"candidate_id": cand.id})  # the bench runs on the local demo (dev)
        r = c.get(f"/api/candidates/{cand.id}/deck", params={"session_id": "bench"})
        assert r.status_code == 200, r.text
    c.get("/api/rules")
"""

STEP_EMBED = """
import numpy as np
from app.embeddings import embed_texts
from app.seed.loader import seed_jobs_data
jobs = seed_jobs_data()
texts = [f"{j['title']} {i}. " + j['description'][:400] for i in range(1000) for j in [jobs[i % len(jobs)]]]
m = embed_texts(texts)
np.save(OUT, m)
"""

STEP_PROJECT = """
import numpy as np
from app.embeddings.projection import project_points
m = np.load(OUT)
xy = project_points(m)
assert xy.shape == (m.shape[0], 2)
"""

STEP_DRIFT = """
from app.db import session_scope
from app.eval.drift import run_drift
with session_scope() as s:
    run_drift(s, users=20, days=20)
"""

STEP_INGEST = """
from app.config import get_settings
from app.db import init_db, session_scope
from app.ingest.http import HttpClient
from app.ingest.run import ingest
from app.seed.loader import seed_jobs_data
get_settings().ensure_var_dirs(); init_db()
seed = seed_jobs_data()
boards = [f"bench{b}" for b in range(10)]
for b, board in enumerate(boards):
    jobs = [{"id": b * 1000 + i, "title": seed[(b * 100 + i) % len(seed)]["title"],
             "absolute_url": f"https://example.invalid/{board}/{i}",
             "location": {"name": seed[i % len(seed)]["location_text"]},
             "content": seed[(b * 100 + i) % len(seed)]["description"]} for i in range(100)]
    client = HttpClient("greenhouse")
    client.store(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true", {"jobs": jobs}, None)
with session_scope() as s:
    reports = ingest(s, ["greenhouse"], boards, accept_terms=True, offline=True)
assert all(r.status == "ok" for r in reports), reports
"""


def _run(name: str, code: str, env: dict[str, str], budget: int) -> dict:
    t0 = time.time()
    proc = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(code)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    peak = 0
    p = psutil.Process(proc.pid)
    while proc.poll() is None:
        # A Windows venv's python.exe is a launcher that runs the real interpreter as a child: sum the tree.
        try:
            tree = [p, *p.children(recursive=True)]
        except psutil.Error:  # the process ended between poll() and children()
            break
        rss = 0
        for q in tree:
            try:
                rss += q.memory_info().rss
            except psutil.Error:
                continue
        peak = max(peak, rss)
        time.sleep(0.05)
    out, _ = proc.communicate()  # also waits: after a break above, returncode would still be None
    ok = proc.returncode == 0
    return {
        "name": name,
        "peak_mb": peak / 2**20,
        "budget_mb": budget,
        "within_budget": peak / 2**20 <= budget,
        "seconds": round(time.time() - t0, 1),
        "ok": ok,
        # a native crash (e.g. an allocation failure inside ONNX Runtime) leaves no traceback, only this code
        "returncode": proc.returncode,
        "output_tail": out[-800:] if not ok else "",
    }


def run_bench() -> dict:
    from app.config import REPO_ROOT, get_settings

    settings = get_settings()
    base_env = {**os.environ, "PYTHONPATH": str(REPO_ROOT), "LOG_LEVEL": "WARNING", "GROQ_API_KEY": ""}
    tmp = Path(tempfile.mkdtemp(prefix="encaixe-bench-"))
    npy = tmp / "emb.npy"
    prefix = f"OUT = r'{npy}'\n"
    steps = [
        ("server start + warm-up (model + one deck)", STEP_SERVER, SERVER_BUDGET_MB, base_env),
        ("embed 1,000 jobs", prefix + STEP_EMBED, BATCH_BUDGET_MB, base_env),
        ("2D projection (t-SNE)", prefix + STEP_PROJECT, BATCH_BUDGET_MB, base_env),
        ("eval drift", STEP_DRIFT, BATCH_BUDGET_MB, base_env),
        # a throwaway var dir: the recorded responses and the 1,000 ingested jobs never touch the demo database
        (
            "ingest --all (respostas gravadas, LLM desligado)",
            STEP_INGEST,
            BATCH_BUDGET_MB,
            {**base_env, "ENCAIXE_VAR_DIR": str(tmp / "var")},
        ),
    ]
    results = [_run(name, code, env, budget) for name, code, budget, env in steps]
    return {"steps": results, "embeddings": settings.embeddings}
