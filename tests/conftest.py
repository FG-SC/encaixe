"""Test isolation: a fresh var dir and database per test, fake embeddings, no network."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    real_connect = socket.socket.connect

    def guarded(self: socket.socket, address: object) -> object:
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and host not in _LOCAL_HOSTS and not host.startswith("127."):
            raise RuntimeError(f"network access blocked in tests: {address!r}")
        return real_connect(self, address)  # type: ignore[arg-type]

    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    var = tmp_path / "var"
    # The developer's .env (e.g. a real GROQ_API_KEY) never reaches the tests.
    monkeypatch.setattr("app.config.read_env_file", lambda path: {})
    monkeypatch.setenv("ENCAIXE_VAR_DIR", str(var))
    monkeypatch.delenv("ENCAIXE_DB_URL", raising=False)
    monkeypatch.setenv("EMBEDDINGS", "fake")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("LOG_LEVEL", "WARNING")

    from app import clock
    from app.config import reset_settings
    from app.db import init_db, reset_engine

    reset_settings()
    reset_engine()
    clock.reset_cache()
    _reset_optional_caches()

    from app.config import get_settings

    get_settings().ensure_var_dirs()
    init_db()
    yield var
    reset_engine()
    reset_settings()
    clock.reset_cache()
    _reset_optional_caches()


def _reset_optional_caches() -> None:
    """Modules from later phases register in-memory caches (embedder, indexes); drop them."""
    import importlib

    for name in ("app.embeddings", "app.ranking.index"):
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError:
            continue
        reset = getattr(module, "reset_caches", None)
        if callable(reset):
            reset()


@pytest.fixture
def session() -> Iterator[object]:
    from app.db import session_scope

    with session_scope() as s:
        yield s


@pytest.fixture
def client() -> Iterator[object]:
    from fastapi.testclient import TestClient

    from app.api.main import create_app

    with TestClient(create_app(front_dist=None)) as c:
        yield c


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _empty_outbox() -> Iterator[None]:
    from app import mailer

    mailer.OUTBOX.clear()
    yield
    mailer.OUTBOX.clear()


@pytest.fixture
def login(client):  # type: ignore[no-untyped-def]
    """Log the test client in. By e-mail: the real link flow (request → e-mail in OUTBOX → verify).
    By candidate_id / recruiter_id: the dev-only persona login. Returns the /api/me payload."""
    import re

    from app import mailer

    def _login(email: str | None = None, *, candidate_id: int | None = None, recruiter_id: int | None = None) -> dict:
        if email is not None and candidate_id is None and recruiter_id is None:
            assert client.post("/api/auth/request", json={"email": email}).status_code == 200
            token = re.search(r"#t=([\w-]+)", mailer.OUTBOX[-1]["body"]).group(1)  # type: ignore[union-attr]
            r = client.post("/api/auth/verify", json={"token": token, "accept_terms": True})
        else:
            body = {"email": email, "candidate_id": candidate_id, "recruiter_id": recruiter_id}
            r = client.post("/api/dev/login", json=body)
        assert r.status_code == 200, r.text
        return r.json()

    return _login
