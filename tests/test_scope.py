"""Scope of the MVP (RULES.scope: Santa Catarina + remote jobs open to Brazil). Fictional postings only."""

from __future__ import annotations

import html

import httpx
import pytest
from sqlmodel import Session, select

from app.extraction.job import RawPosting, extract_job
from app.ingest.run import SCOPE_KEY, ingest
from app.ingest.scope import decide
from app.models import Job, Setting

REQS = "Requisitos\n- SQL\n- Python"


@pytest.mark.parametrize(
    ("description", "location", "structured", "expected"),
    [
        (REQS, "Florianópolis, SC", {}, (True, "in_region")),
        (REQS, "São Paulo, SP", {}, (False, "outside_region")),
        (REQS, None, {}, (False, "outside_region")),  # no city: not in the sample
        (REQS + "\nVaga 100% remota.", "Remoto", {}, (True, "remote_open")),
        (REQS + "\nThis role is Remote - LATAM.", "Remote", {}, (True, "remote_open")),
        (REQS + "\nThis role is Remote - US only.", "Remote - US", {}, (False, "remote_closed")),
        (REQS + "\nVaga 100% remota.", "Remoto", {"country": "UY"}, (False, "remote_closed")),  # Lever country
    ],
)
def test_scope(description: str, location: str | None, structured: dict, expected: tuple[bool, str]) -> None:
    raw = RawPosting(title="Analista de Dados", description=description, location_text=location, structured=structured)
    d = decide(raw, extract_job(raw))
    assert (d.in_scope, d.code) == expected


def test_ingest_keeps_only_postings_in_scope(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.ingest.http as http_mod

    monkeypatch.setattr(http_mod.time, "sleep", lambda s: None)

    def job(job_id: int, location: str) -> dict:
        body = "<h3>Requisitos</h3><ul><li>SQL</li><li>Python</li></ul>"
        return {
            "id": job_id,
            "title": "Analista de Dados",
            "absolute_url": f"https://boards.example/tainha/{job_id}",
            "location": {"name": location},
            "content": html.escape(body),
        }

    def transport(jobs: list[dict]) -> httpx.MockTransport:
        return httpx.MockTransport(lambda request: httpx.Response(200, json={"jobs": jobs}))

    first = transport([job(1, "Joinville, SC"), job(2, "Recife, PE")])
    r = ingest(session, ["greenhouse"], ["tainha"], transport=first)[0]
    session.commit()
    assert r.status == "ok" and r.run.n_new == 1 and r.details["out_of_scope"] == {"outside_region": 1}  # type: ignore[union-attr]
    assert [j.source_id for j in session.exec(select(Job)).all()] == ["tainha:1"]
    row = session.get(Setting, SCOPE_KEY)
    assert row is not None and row.value["greenhouse/tainha"]["out_of_scope"] == 1

    # the posting moves out of the region: the stored copy closes at once
    r = ingest(session, ["greenhouse"], ["tainha"], transport=transport([job(1, "Recife, PE")]), force=True)[0]
    session.commit()
    stored = session.exec(select(Job).where(Job.source_id == "tainha:1")).one()
    assert stored.status == "closed" and r.run.n_closed == 1  # type: ignore[union-attr]
