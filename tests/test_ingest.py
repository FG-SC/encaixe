"""Ingestion (spec 5.1) against synthetic recorded responses: never the network, never real data."""

from __future__ import annotations

import html
import json

import httpx
import pytest
from sqlmodel import Session, select

from app import clock
from app.ingest.connectors import github_company, github_labels_to_fields, strip_contacts
from app.ingest.run import ingest
from app.ingest.snapshot import list_snapshots, load_snapshot, save_snapshot
from app.models import IngestRun, Job

GH_JOB = {
    "id": 101,
    "title": "Analista de Dados Pleno",
    "absolute_url": "https://boards.example/tainha/101",
    "location": {"name": "Florianópolis, SC"},
    "content": html.escape(
        "<p>Sobre nós: empresa fictícia.</p><h3>Requisitos</h3><ul><li>SQL</li><li>Python</li>"
        "</ul><p>Contato: rh@tainha.example ou (48) 99999-0000. Desde 2019-2021.</p>"
    ),
}
GH_JOB2 = {**GH_JOB, "id": 102, "title": "Engenheiro de Dados", "absolute_url": "https://boards.example/tainha/102"}


def transport(routes: dict[str, object], calls: list | None = None, etag: str | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        assert request.headers["User-Agent"].startswith("Encaixe/")
        if etag and request.headers.get("If-None-Match") == etag:
            return httpx.Response(304)
        for prefix, body in routes.items():
            if str(request.url).startswith(prefix):
                return httpx.Response(200, json=body, headers={"ETag": etag} if etag else {})
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.ingest.http as http_mod

    monkeypatch.setattr(http_mod.time, "sleep", lambda s: None)


def test_disabled_sources_are_skipped_with_their_reason(session: Session) -> None:
    reports = ingest(session, ["greenhouse", "weworkremotely"])
    assert [r.status for r in reports] == ["skipped", "skipped"]
    assert "termos" in reports[0].message and "sem conector" in reports[1].message


def test_greenhouse_ingest_dedups_and_closes_after_two_missed_runs(session: Session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _no_sleep(monkeypatch)
    url = "https://boards-api.greenhouse.io/v1/boards/tainha/jobs"
    t = transport({url: {"jobs": [GH_JOB, GH_JOB2]}})
    r = ingest(session, ["greenhouse"], ["tainha"], accept_terms=True, transport=t)[0]
    assert r.status == "ok" and (r.run.n_seen, r.run.n_new) == (2, 2)  # type: ignore[union-attr]
    job = session.exec(select(Job).where(Job.source_id == "tainha:101")).one()
    assert job.url == GH_JOB["absolute_url"] and job.requires["skills_must"] == ["sql", "python"]
    assert "rh@tainha.example" not in job.description_text and "99999" not in job.description_text
    assert "2019-2021" in job.description_text  # years are not phone numbers
    # same posting again: unchanged; then 102 disappears for two runs → closed
    t2 = transport({url: {"jobs": [GH_JOB]}})
    ingest(session, ["greenhouse"], ["tainha"], accept_terms=True, transport=t2, force=True)
    assert session.exec(select(Job).where(Job.source_id == "tainha:102")).one().status == "open"
    ingest(session, ["greenhouse"], ["tainha"], accept_terms=True, transport=t2, force=True)
    assert session.exec(select(Job).where(Job.source_id == "tainha:102")).one().status == "closed"
    assert len(session.exec(select(IngestRun)).all()) == 3
    # once per 24 h per board, unless forced
    again = ingest(session, ["greenhouse"], ["tainha"], accept_terms=True, transport=t2)[0]
    assert again.status == "skipped"


def test_etag_and_offline_cache(session: Session, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _no_sleep(monkeypatch)
    url = "https://boards-api.greenhouse.io/v1/boards/tainha/jobs"
    calls: list = []
    t = transport({url: {"jobs": [GH_JOB]}}, calls, etag='W/"abc"')
    ingest(session, ["greenhouse"], ["tainha"], accept_terms=True, transport=t, cache_dir=tmp_path)
    ingest(session, ["greenhouse"], ["tainha"], accept_terms=True, transport=t, cache_dir=tmp_path, force=True)
    assert calls[1].headers.get("If-None-Match") == 'W/"abc"'
    offline = ingest(session, ["greenhouse"], ["tainha"], accept_terms=True, offline=True, cache_dir=tmp_path)[0]
    assert offline.status == "ok" and offline.run.n_seen == 1  # type: ignore[union-attr]
    missing = ingest(session, ["greenhouse"], ["other"], accept_terms=True, offline=True, cache_dir=tmp_path)[0]
    assert missing.status == "error" and "not cached" in missing.message


def test_lever_structured_fields_and_cross_source_dedup(session: Session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _no_sleep(monkeypatch)
    ingest(
        session,
        ["greenhouse"],
        ["tainha"],
        accept_terms=True,
        transport=transport({"https://boards-api.greenhouse.io": {"jobs": [GH_JOB]}}),
    )
    lever = [
        {
            "id": "a1",
            "text": "Analista de Dados Pleno",
            "hostedUrl": "https://jobs.example/a1",
            "categories": {"location": "Florianópolis, SC"},
            "workplaceType": "hybrid",
            "descriptionPlain": "Analise dados.",
            "lists": [{"text": "Requirements", "content": "<li>SQL</li>"}],
            "salaryRange": {"min": 7000, "max": 9000, "currency": "BRL", "interval": "per-month-salary"},
        },
        {
            "id": "a2",
            "text": "Data Scientist",
            "hostedUrl": "https://jobs.example/a2",
            "categories": {"location": "Remote - LATAM"},
            "workplaceType": "remote",
            "descriptionPlain": "Write to ds@lever.example",
            "lists": [{"text": "Requirements", "content": "<li>Python</li>"}],
            "salaryRange": {"min": 50000, "max": 70000, "currency": "USD", "interval": "per-year-salary"},
        },
    ]
    # board "tainha" has no display name in the config, so both sources name the company "tainha"
    r = ingest(
        session,
        ["lever"],
        ["tainha"],
        accept_terms=True,
        transport=transport({"https://api.lever.co/v0/postings/tainha": lever}),
    )[0]
    # a1 has the same normalized company ("tainha"), title and city as the Greenhouse posting → deduplicated
    assert r.details["duplicates_across_sources"] == 1 and r.run.n_new == 1  # type: ignore[union-attr]
    job = session.exec(select(Job).where(Job.source_id == "tainha:a2")).one()
    assert job.offers["arrangement"] == "remote" and job.offers["comp_max"] == 70000
    assert job.offers["period"] == "year" and "ds@lever.example" not in job.description_text


def test_github_labels_prs_and_contacts(session: Session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _no_sleep(monkeypatch)
    issues = [
        {
            "number": 7,
            "title": "[Peixe Fintech] Desenvolvedor Python Pleno",
            "html_url": "https://github.com/x/7",
            "labels": [{"name": "Pleno"}, {"name": "CLT"}, {"name": "Remoto"}],
            "body": "## Requisitos\n- Python\n- Django\n## Como se candidatar\nEnvie para vagas@peixe.example "
            "ou (11) 98888-7777 / https://linkedin.com/in/recrutadora",
        },
        {"number": 8, "title": "Ajusta README", "pull_request": {"url": "x"}, "labels": [], "body": ""},
    ]
    r = ingest(
        session,
        ["github"],
        ["comunidade/vagas"],
        accept_terms=True,
        transport=transport({"https://api.github.com/repos/comunidade/vagas/issues": issues}),
    )[0]
    assert r.run.n_seen == 1  # type: ignore[union-attr]
    job = session.exec(select(Job).where(Job.source == "github")).one()
    assert job.source_id == "comunidade/vagas#7" and job.title == "Desenvolvedor Python Pleno"
    assert job.requires["seniority"] == 3 and job.offers["regime"] == "clt" and job.offers["arrangement"] == "remote"
    assert job.labels == ["Pleno", "CLT", "Remoto"] and job.requires["skills_must"] == ["python", "django"]
    for secret in ("vagas@peixe.example", "98888", "linkedin.com/in"):
        assert secret not in job.description_text
    assert github_company("[Peixe Fintech] Desenvolvedor Python Pleno") == "Peixe Fintech"
    assert github_labels_to_fields(["Júnior", "PJ", "Florianópolis"]) == {
        "seniority": 2,
        "regime": "pj",
        "city_id": "florianopolis-sc-br",
    }


def test_strip_contacts_keeps_years_and_amounts() -> None:
    text = "Fale com joao@empresa.example, +55 (48) 99999-0000. Experiência 2019-2021, salário R$ 12.000 - 15.000."
    out = strip_contacts(text)
    assert "joao@" not in out and "99999" not in out and "2019-2021" in out and "12.000 - 15.000" in out


def test_snapshot_round_trip(session: Session) -> None:
    from app.seed.loader import load_seed_jobs

    load_seed_jobs(session)
    session.commit()
    path = save_snapshot(session, "t1")
    assert path.exists() and "t1" in list_snapshots()
    with __import__("gzip").open(path, "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    assert len(data["jobs"]) == 60 and data["jobs"][0]["versions"]
    seed_job = session.exec(select(Job).where(Job.source == "seed")).first()
    seed_job.status = "closed"  # type: ignore[union-attr]
    session.add(seed_job)
    session.commit()
    clock.advance_days(1)
    counts = load_snapshot(session, "t1")
    assert counts["jobs"] == 60 and session.get(Job, seed_job.id).status == "open"  # type: ignore[union-attr]
