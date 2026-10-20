"""Run one heavy command at a time on this machine.

Usage:
    python tools/heavy.py [--timeout-min N] -- <cmd...>
    python tools/heavy.py --status

The spec allows only one heavy process at a time (test suite, pip install, front build, batch CLI
commands, model loads). This wrapper takes ``<repo>/var/heavy.lock`` atomically
(``os.open`` with ``O_CREAT | O_EXCL``), writes the holder's pid, command and start time into it,
runs the command with inherited stdio and returns the command's exit code. The lock is always
removed (``finally``), also on Ctrl+C.

While another live process holds the lock, it polls every 2 s and prints a waiting note every 30 s.
``--timeout-min N`` gives up waiting after N minutes (exit code 75). Without it, it waits as long as
the holder is alive.

A lock is stale when its holder is no longer alive:
  * ``psutil.pid_exists`` when psutil can be imported (plus a process create-time check against pid
    reuse);
  * without psutil, on Windows, a ctypes ``OpenProcess``/``GetExitCodeProcess`` query;
    ``os.kill(pid, 0)`` is never used on Windows, because there it sends CTRL_C_EVENT;
  * without psutil, on POSIX, ``os.kill(pid, 0)`` (signal 0 only checks);
  * when liveness cannot be determined, the lock is stale once it is older than 60 minutes.
Stale locks are removed. Standard library only (psutil is optional at runtime).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VAR_DIR = REPO_ROOT / "var"
LOCK_PATH = VAR_DIR / "heavy.lock"

POLL_SECONDS = 2.0
NOTE_EVERY_SECONDS = 30.0
STALE_AGE_SECONDS = 60 * 60  # fallback when liveness cannot be checked
UNREADABLE_GRACE_SECONDS = 30  # an unreadable lock older than this is a crashed half-written lock
EXIT_LOCK_TIMEOUT = 75  # EX_TEMPFAIL
EXIT_NOT_FOUND = 127
EXIT_INTERRUPTED = 130

IS_WINDOWS = os.name == "nt"


def _log(message: str) -> None:
    print(f"[heavy] {message}", file=sys.stderr, flush=True)


def _fmt_time(epoch: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch))


# --------------------------------------------------------------------------- liveness


def _try_import_psutil():
    try:
        import psutil  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 - psutil is optional
        return None
    return psutil


def _process_create_time(pid: int) -> float | None:
    psutil = _try_import_psutil()
    if psutil is None:
        return None
    try:
        return float(psutil.Process(pid).create_time())
    except Exception:  # noqa: BLE001
        return None


def _pid_alive_windows(pid: int) -> bool | None:
    """Ask Windows whether ``pid`` is a running process (never sends a signal)."""
    try:
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        error_access_denied = 5

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        open_process.restype = wintypes.HANDLE
        get_exit_code = kernel32.GetExitCodeProcess
        get_exit_code.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        get_exit_code.restype = wintypes.BOOL
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL

        handle = open_process(process_query_limited_information, False, pid)
        if not handle:
            # Access denied means the process exists but belongs to someone else.
            return ctypes.get_last_error() == error_access_denied
        try:
            code = wintypes.DWORD()
            if not get_exit_code(handle, ctypes.byref(code)):
                return None
            return code.value == still_active
        finally:
            close_handle(handle)
    except Exception:  # noqa: BLE001 - unknown, fall back to the age rule
        return None


def pid_alive(pid: int, create_time: float | None = None) -> bool | None:
    """True/False when liveness is known, None when it cannot be determined."""
    if pid <= 0:
        return False
    psutil = _try_import_psutil()
    if psutil is not None:
        try:
            if not psutil.pid_exists(pid):
                return False
            if create_time is not None:
                current = _process_create_time(pid)
                if current is not None and abs(current - create_time) > 1.0:
                    return False  # the pid was reused by another process
            return True
        except Exception:  # noqa: BLE001
            return None
    if IS_WINDOWS:
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)  # POSIX only: signal 0 performs the permission/existence check
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


# --------------------------------------------------------------------------- lock file


def _read_lock() -> tuple[dict | None, float | None]:
    """Return (content or None when unreadable, file mtime or None when absent)."""
    try:
        mtime = LOCK_PATH.stat().st_mtime
    except FileNotFoundError:
        return None, None
    except OSError:
        return None, time.time()
    try:
        with open(LOCK_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return (data if isinstance(data, dict) else None), mtime
    except (OSError, ValueError):
        return None, mtime


def _holder_alive(info: dict) -> bool | None:
    """Combine the liveness of the holder process and of the command it started."""
    results = []
    for key, ct_key in (("pid", "pid_create_time"), ("child_pid", "child_create_time")):
        pid = info.get(key)
        if isinstance(pid, int):
            results.append(pid_alive(pid, info.get(ct_key)))
    if any(r is True for r in results):
        return True
    if results and all(r is False for r in results):
        return False
    return None


def _is_stale(info: dict | None, mtime: float) -> tuple[bool, str]:
    now = time.time()
    if info is None:
        age = now - mtime
        return age > UNREADABLE_GRACE_SECONDS, f"unreadable lock, {age:.0f}s old"
    alive = _holder_alive(info)
    if alive is False:
        return True, f"holder pid {info.get('pid')} is not alive"
    if alive is None:
        started = info.get("started_epoch")
        age = now - (started if isinstance(started, (int, float)) else mtime)
        if age > STALE_AGE_SECONDS:
            return True, f"liveness unknown and lock is {age / 60:.0f} min old"
    return False, ""


def _remove_path(path: Path, attempts: int = 10) -> bool:
    for _ in range(attempts):
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return True
        except PermissionError:  # Windows: another process has it open for a moment
            time.sleep(0.2)
        except OSError:
            time.sleep(0.2)
    return False


def _remove_stale(expected: dict | None, reason: str) -> None:
    current, _ = _read_lock()
    if expected is not None and current is not None and current.get("token") != expected.get("token"):
        return  # someone replaced it in the meantime; re-evaluate on the next poll
    if _remove_path(LOCK_PATH):
        _log(f"removed stale lock ({reason})")


def _write_new_lock(info: dict) -> bool:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(LOCK_PATH, flags, 0o644)
    except FileExistsError:
        return False
    try:
        os.write(fd, json.dumps(info, ensure_ascii=False).encode("utf-8"))
    finally:
        os.close(fd)
    return True


def _rewrite_lock(info: dict) -> None:
    """Atomically update our own lock (best effort: a failure only loses the extra fields)."""
    tmp = LOCK_PATH.with_name(f"heavy.lock.{info['token']}.tmp")
    try:
        tmp.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
        for _ in range(10):
            try:
                os.replace(tmp, LOCK_PATH)
                return
            except PermissionError:
                time.sleep(0.2)
    except OSError:
        pass
    _remove_path(tmp, attempts=3)


def _release(info: dict) -> None:
    current, _ = _read_lock()
    if current is not None and current.get("token") != info.get("token"):
        _log("lock no longer ours; leaving it in place")
        return
    if not _remove_path(LOCK_PATH):
        _log(f"could not remove {LOCK_PATH}; delete it by hand")


def _describe(info: dict | None) -> str:
    if not info:
        return "unknown holder"
    cmd = info.get("command") or []
    cmd_text = " ".join(str(c) for c in cmd) if isinstance(cmd, list) else str(cmd)
    if len(cmd_text) > 120:
        cmd_text = cmd_text[:117] + "..."
    started = info.get("started_epoch")
    since = _fmt_time(started) if isinstance(started, (int, float)) else "?"
    return f"pid {info.get('pid')} since {since}: {cmd_text}"


def acquire(command: list[str], timeout_min: float | None) -> dict | None:
    """Block until the lock is ours; return its content, or None on timeout."""
    VAR_DIR.mkdir(parents=True, exist_ok=True)
    started_wait = time.monotonic()
    last_note = None
    while True:
        info = {
            "token": uuid.uuid4().hex,
            "pid": os.getpid(),
            "pid_create_time": _process_create_time(os.getpid()),
            "child_pid": None,
            "child_create_time": None,
            "command": command,
            "cwd": os.getcwd(),
            "host": socket.gethostname(),
            "started_epoch": time.time(),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        if _write_new_lock(info):
            return info

        held, mtime = _read_lock()
        if mtime is None:
            continue  # released between our attempt and the read: retry at once
        stale, reason = _is_stale(held, mtime)
        if stale:
            _remove_stale(held, reason)
            continue

        waited = time.monotonic() - started_wait
        if timeout_min is not None and waited >= timeout_min * 60:
            _log(f"gave up after {waited / 60:.1f} min; lock held by {_describe(held)}")
            return None
        if last_note is None or time.monotonic() - last_note >= NOTE_EVERY_SECONDS:
            _log(f"waiting for {LOCK_PATH} (waited {waited:.0f}s); held by {_describe(held)}")
            last_note = time.monotonic()
        time.sleep(POLL_SECONDS)


def _resolve_command(command: list[str]) -> list[str]:
    exe = shutil.which(command[0])
    return [exe, *command[1:]] if exe else list(command)


def run(command: list[str], timeout_min: float | None) -> int:
    info = acquire(command, timeout_min)
    if info is None:
        return EXIT_LOCK_TIMEOUT
    try:
        try:
            proc = subprocess.Popen(_resolve_command(command))
        except FileNotFoundError:
            _log(f"command not found: {command[0]}")
            return EXIT_NOT_FOUND
        except OSError as exc:
            _log(f"could not start {command[0]}: {exc}")
            return EXIT_NOT_FOUND
        info["child_pid"] = proc.pid
        info["child_create_time"] = _process_create_time(proc.pid)
        _rewrite_lock(info)
        try:
            return proc.wait()
        except KeyboardInterrupt:
            # The child got the same Ctrl+C; give it a moment to stop by itself.
            try:
                proc.wait(timeout=5)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                proc.kill()
                proc.wait()
            return EXIT_INTERRUPTED
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    finally:
        _release(info)


def status() -> int:
    held, mtime = _read_lock()
    if mtime is None:
        print("free")
        return 0
    stale, reason = _is_stale(held, mtime)
    print(f"held by {_describe(held)}" + (f" (stale: {reason})" if stale else ""))
    return 0


def _parse(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    if "--" in argv:
        idx = argv.index("--")
        opts, command = argv[:idx], argv[idx + 1 :]
    elif argv and not argv[0].startswith("-"):
        opts, command = [], argv
    else:
        opts, command = argv, []
    parser = argparse.ArgumentParser(
        prog="heavy.py",
        description="Run a command while holding the one-heavy-process lock (<repo>/var/heavy.lock).",
        usage="python tools/heavy.py [--timeout-min N] -- <cmd...>",
    )
    parser.add_argument(
        "--timeout-min",
        type=float,
        default=None,
        help="give up waiting for the lock after N minutes (exit code 75); default: wait",
    )
    parser.add_argument("--status", action="store_true", help="show who holds the lock and exit")
    args = parser.parse_args(opts)
    if not args.status and not command:
        parser.error("missing command after --")
    return args, command


def main(argv: list[str] | None = None) -> int:
    args, command = _parse(list(sys.argv[1:] if argv is None else argv))
    if args.status:
        return status()
    try:
        return run(command, args.timeout_min)
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
