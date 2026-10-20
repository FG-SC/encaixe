"""Application clock: real UTC time plus an offset in days, persisted for the demo.

Every timestamp in the app comes from ``now()``. This is the only module allowed to read the system
clock (tests grep the code base). The offset lives in ``Setting["clock_offset_days"]``; it is cached
in memory, the cache is dropped whenever the offset is set here, and it expires after a few
seconds so a server also sees an offset changed by the CLI in another process.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.exc import OperationalError
from sqlmodel import Session

from app.db import get_engine
from app.models import Setting

log = logging.getLogger(__name__)

OFFSET_KEY = "clock_offset_days"
CACHE_TTL_SECONDS = 5.0

_lock = threading.Lock()
_cached_offset: float | None = None
_cached_at = 0.0


def _real_utcnow() -> datetime:
    return datetime.now(UTC)


def _read_offset() -> tuple[float, bool]:
    """Return (offset_days, cacheable). Before init_db there is no table: offset 0, not cached."""
    try:
        with Session(get_engine()) as session:
            row = session.get(Setting, OFFSET_KEY)
            value = None if row is None else row.value
    except OperationalError:
        return 0.0, False
    if value is None:
        return 0.0, True
    try:
        offset = float(value)
    except (TypeError, ValueError):
        log.warning("ignoring invalid %s=%r", OFFSET_KEY, value)
        return 0.0, True
    return (offset if math.isfinite(offset) else 0.0), True


def get_offset_days() -> float:
    global _cached_offset, _cached_at
    with _lock:
        if _cached_offset is not None and time.monotonic() - _cached_at < CACHE_TTL_SECONDS:
            return _cached_offset
    offset, cacheable = _read_offset()
    if cacheable:
        with _lock:
            _cached_offset = offset
            _cached_at = time.monotonic()
    return offset


def reset_cache() -> None:
    global _cached_offset, _cached_at
    with _lock:
        _cached_offset = None
        _cached_at = 0.0


def now() -> datetime:
    """Timezone-aware UTC: real time plus the configured offset."""
    return _real_utcnow() + timedelta(days=get_offset_days())


def today() -> date:
    return now().date()


def _check_days(days: float, what: str) -> float:
    value = float(days)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{what} must be a finite number of days >= 0, got {days!r}")
    return value


def set_offset_days(days: float) -> float:
    """Persist the offset (days ahead of the real clock) and drop the cache. Returns the new offset."""
    value = _check_days(days, "offset_days")
    with Session(get_engine()) as session:
        row = session.get(Setting, OFFSET_KEY)
        if row is None:
            session.add(Setting(key=OFFSET_KEY, value=value))
        else:
            row.value = value
            session.add(row)
        session.commit()
    reset_cache()
    return value


def advance_days(days: float) -> float:
    """Move the clock forward by ``days``. Returns the new offset."""
    step = _check_days(days, "advance")
    current, _ = _read_offset()
    return set_offset_days(current + step)
