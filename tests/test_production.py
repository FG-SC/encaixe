"""Production mode (ENCAIXE_ENV=prod): no demo tools, honest texts, limits. Fictional data only."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app import clock, texts
from app.config import RULES, Settings, reset_settings
from app.extraction.job import RawPosting, extract_job
from app.jobs import upsert_job
from app.models import Setting

PROD_ENV = {
    "ENCAIXE_ENV": "prod",
    "BASE_URL": "https://encaixe.example",
    "SMTP_HOST": "smtp.example",
    "SMTP_FROM": "Encaixe <login@encaixe.example>",
}


@pytest.fixture
def prod(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in PROD_ENV.items():
        monkeypatch.setenv(key, value)
    # tests run with fake embeddings; everything else about production is real
    monkeypatch.setattr(Settings, "prod_problems", lambda self: [])
    reset_settings()


def test_prod_settings_are_checked() -> None:
    s = Settings.from_env(environ={"ENCAIXE_ENV": "prod", "BASE_URL": "http://x", "EMBEDDINGS": "tfidf"}, env_file=None)
    problems = " ".join(s.prod_problems())
    assert s.is_prod and "https" in problems and "SMTP_HOST" in problems and "onnx" in problems
    ok = Settings.from_env(environ={**PROD_ENV, "EMBEDDINGS": "onnx"}, env_file=None)
    assert ok.prod_problems() == [] and ok.base_url == "https://encaixe.example"
    with pytest.raises(ValueError):
        Settings.from_env(environ={"ENCAIXE_ENV": "staging"}, env_file=None)


def test_prod_app_refuses_an_incomplete_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.main import create_app

    monkeypatch.setenv("ENCAIXE_ENV", "prod")
    reset_settings()
    with pytest.raises(RuntimeError, match="BASE_URL"):
        create_app(front_dist=None)


def test_prod_app_has_no_dev_routes_or_docs(prod: None) -> None:
    from app.api.main import create_app

    with TestClient(create_app(front_dist=None)) as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/dev/status").status_code == 404
        assert c.post("/api/dev/clock", json={"advance_days": 3}).status_code == 404
        assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404


def test_prod_ignores_the_demo_clock(session: Session, prod: None) -> None:
    session.add(Setting(key=clock.OFFSET_KEY, value=30))
    session.commit()
    clock.reset_cache()
    assert clock.get_offset_days() == 0.0
    assert abs((clock.now() - clock.real_now()).total_seconds()) < 5


def test_demo_commands_refuse_to_run_in_prod(prod: None) -> None:
    from typer.testing import CliRunner

    from app.cli import app
    from app.config import get_settings

    db = get_settings().var_dir / "encaixe.db"
    assert db.exists()
    for args in (["demo", "reset"], ["seed"], ["synth", "candidates"], ["clock", "advance", "--days", "1"]):
        result = CliRunner().invoke(app, args)
        assert result.exit_code == 2, (args, result.output)
    assert db.exists()  # demo reset did not delete the production database


def test_backup_copies_the_database_and_keeps_the_newest(session: Session) -> None:
    import sqlite3

    from typer.testing import CliRunner

    from app.cli import app
    from app.config import get_settings

    session.add(Setting(key="marker", value="kept in the backup"))
    session.commit()
    folder = get_settings().var_dir / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(3):  # older backups, oldest first by name
        (folder / f"encaixe-2020010{i}-000000.db").write_bytes(b"old")
    result = CliRunner().invoke(app, ["backup", "--keep", "2"])
    assert result.exit_code == 0, result.output
    backups = sorted(folder.glob("encaixe-*.db"))
    assert len(backups) == 2 and backups[0].name == "encaixe-20200102-000000.db"
    con = sqlite3.connect(backups[-1])
    try:
        assert con.execute("select value from setting where key = 'marker'").fetchone()[0] == '"kept in the backup"'
    finally:
        con.close()


def test_blind_card_text_follows_the_rule() -> None:
    text = texts.PRIVACY_TEXTS["blind_card"]
    hidden_part, shown_part = text.split("Eles veem")
    for code in RULES.privacy.blind_hidden:
        assert texts.BLIND_HIDDEN_LABELS[code] in hidden_part
    assert "empresa" not in hidden_part and "empresas" in shown_part  # companies are shown (owner's decision)
    assert "não são verificados" in text
    stricter = texts.blind_card_text(("name", "contact", "company_names"))
    assert "nomes das empresas" in stricter.split("Eles veem")[0]


def test_collected_postings_are_not_redisplayed(client, login, session: Session) -> None:  # type: ignore[no-untyped-def]
    login("leitor@example.com")
    text = "Requisitos\n- SQL\n- Python"
    raw = RawPosting(title="Analista de Dados", description=text, location_text="Joinville, SC")
    market = upsert_job(session, extract_job(raw), source="greenhouse", source_id="tainha:1").job
    seed = upsert_job(session, extract_job(raw), source="seed", source_id="seed-x").job
    session.commit()
    assert client.get(f"/api/jobs/{market.id}").json()["description_text"] is None
    assert "SQL" in client.get(f"/api/jobs/{seed.id}").json()["description_text"]


def test_background_llm_rereads_have_a_daily_cap(session: Session) -> None:
    from app.llm import queue

    raw = RawPosting(title="Analista de Dados", description="Requisitos\n- SQL", location_text="Joinville, SC")
    ids = [upsert_job(session, extract_job(raw), source="t", source_id=f"t{i}").job.id for i in range(25)]
    session.commit()
    loop = asyncio.new_event_loop()
    queue._loop, queue._queue = loop, asyncio.Queue()
    try:
        cap = RULES.llm.background_daily_cap
        assert queue.enqueue(session, ids) == cap
        queue._pending.clear()
        assert queue.enqueue(session, ids) == 0  # same day: the cap is spent
        clock.advance_days(1)
        assert queue.enqueue(session, ids) == cap  # a new day resets the counter
    finally:
        queue._loop = queue._queue = None
        queue._pending.clear()
        loop.close()


def test_the_postings_own_workplace_tag_wins() -> None:
    raw = RawPosting(
        title="Consultor Comercial Externo",
        description="Benefícios: home office às sextas.\n\nSobre a Tainha Analytics\nSomos fictícios. #LI-ONSITE",
        location_text="Joinville, SC",
    )
    assert extract_job(raw).offers.arrangement == "onsite"


def test_cv_size_is_limited(client, login) -> None:  # type: ignore[no-untyped-def]
    login("ana@example.com")
    too_long = "Experiência com Python. " * (RULES.limits.cv_max_chars // 20)
    assert client.post("/api/candidates/parse", data={"text": too_long}).status_code == 413
