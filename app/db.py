"""Database: engine, sessions, ``init_db()``, SQLite pragmas, append-only events, vector blobs.

SQLite in ``var/encaixe.db`` (WAL). Every connection gets ``journal_mode=WAL``, ``foreign_keys=ON``,
``busy_timeout=5000`` and ``recursive_triggers=ON`` (without it, ``INSERT OR REPLACE`` deletes the old
row without firing delete triggers, i.e. it could rewrite an event). ``init_db()`` creates the tables
and the triggers that make ``interactionevent`` append-only (``BEFORE UPDATE`` / ``BEFORE DELETE`` ->
``RAISE(ABORT)``). The only way around them is ``allow_event_delete``, reserved for the LGPD purge
(``app.events.purge``).

JSON columns are plain ``dict``/``list`` values: reassign the attribute (do not mutate it in place)
so SQLAlchemy sees the change. Datetime columns are timezone-aware UTC (SQLModel's ``UTCDateTime``).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import event, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings

if TYPE_CHECKING:
    import numpy as np

EVENT_TABLE = "interactionevent"
NO_UPDATE_TRIGGER = "interactionevent_no_update"
NO_DELETE_TRIGGER = "interactionevent_no_delete"
APPEND_ONLY_MESSAGE = "interactionevent is append-only"

TRIGGERS_SQL: dict[str, str] = {
    NO_UPDATE_TRIGGER: (
        f"CREATE TRIGGER IF NOT EXISTS {NO_UPDATE_TRIGGER} BEFORE UPDATE ON {EVENT_TABLE} "
        f"BEGIN SELECT RAISE(ABORT, '{APPEND_ONLY_MESSAGE}'); END"
    ),
    NO_DELETE_TRIGGER: (
        f"CREATE TRIGGER IF NOT EXISTS {NO_DELETE_TRIGGER} BEFORE DELETE ON {EVENT_TABLE} "
        f"BEGIN SELECT RAISE(ABORT, '{APPEND_ONLY_MESSAGE}'); END"
    ),
}

_engine: Engine | None = None
_engine_lock = threading.Lock()


def _sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA recursive_triggers=ON")  # REPLACE conflict deletions fire the triggers
    finally:
        cursor.close()


def _is_memory_sqlite(url: str) -> bool:
    database = make_url(url).database
    return not database or database == ":memory:" or "mode=memory" in url


def make_engine(url: str) -> Engine:
    """Create an engine; SQLite gets cross-thread connections and the per-connection pragmas."""
    if not url.startswith("sqlite"):
        return create_engine(url)
    kwargs: dict[str, Any] = {"connect_args": {"check_same_thread": False}}
    if _is_memory_sqlite(url):
        kwargs["poolclass"] = StaticPool  # one shared connection, or each would see an empty database
    else:
        database = make_url(url).database
        if database:
            Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **kwargs)
    event.listen(engine, "connect", _sqlite_pragmas)
    return engine


def get_engine() -> Engine:
    """The process-wide engine, built from the settings on first use."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = make_engine(get_settings().db_url)
    return _engine


def reset_engine() -> None:
    """Dispose of the engine (tests point each case at a fresh database)."""
    global _engine
    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None


def ensure_append_only_triggers(engine: Engine | None = None) -> None:
    with (engine or get_engine()).begin() as conn:
        for sql in TRIGGERS_SQL.values():
            conn.execute(text(sql))


def init_db(engine: Engine | None = None) -> Engine:
    """Create every table (idempotent) and the append-only triggers on interactionevent."""
    from app import models  # noqa: F401  (registers the tables on SQLModel.metadata)

    engine = engine or get_engine()
    SQLModel.metadata.create_all(engine)
    ensure_append_only_triggers(engine)
    return engine


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on error, always close."""
    session = Session(get_engine(), expire_on_commit=False)
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def allow_event_delete(session: Session) -> Iterator[Session]:
    """Lift the interactionevent delete trigger inside ``session``'s transaction (LGPD purge only).

    pysqlite opens a transaction only before DML, so a ``DROP TRIGGER`` issued first would be
    committed at once. A no-op DELETE opens the write transaction, which makes the DROP part of it:
    if the caller rolls back, the trigger comes back with everything else. ORM deletes queued in the
    block are flushed before the trigger is recreated (in ``finally``); the caller then commits.
    """
    session.execute(text(f"DELETE FROM {EVENT_TABLE} WHERE 0"))
    session.execute(text(f"DROP TRIGGER IF EXISTS {NO_DELETE_TRIGGER}"))
    try:
        yield session
        session.flush()
    finally:
        try:
            session.execute(text(TRIGGERS_SQL[NO_DELETE_TRIGGER]))
        except Exception:
            # The transaction is unusable; rolling it back also undoes the DROP. Re-check on a fresh
            # connection so the trigger exists whatever happened.
            session.rollback()
            bind = session.get_bind()
            ensure_append_only_triggers(bind if isinstance(bind, Engine) else None)


def trigger_names(session: Session) -> set[str]:
    rows = session.execute(text("SELECT name FROM sqlite_master WHERE type = 'trigger'"))
    return {row[0] for row in rows}


# --------------------------------------------------------------------------- vectors


def to_blob(vector: Any) -> bytes:
    """1-D vector -> little-endian float32 bytes."""
    import numpy as np

    arr = np.asarray(vector, dtype="<f4")
    if arr.ndim != 1:
        raise ValueError(f"expected a 1-D vector, got shape {arr.shape}")
    return arr.tobytes()


def from_blob(blob: bytes | bytearray | memoryview | None) -> np.ndarray | None:
    """float32 bytes -> writable 1-D float32 array (None stays None)."""
    import numpy as np

    if blob is None:
        return None
    if len(blob) % 4:
        raise ValueError(f"blob length {len(blob)} is not a multiple of 4 (float32)")
    return np.frombuffer(blob, dtype="<f4").astype(np.float32)
