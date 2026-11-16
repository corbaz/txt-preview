"""Diagnostic trace of the reading controls, written to speech.log.

Off on Windows unless TXT_SPEECH_TRACE=1: it exists to see, on a Mac that
cannot be debugged from here, what Pausar/Continuar and the dictation do.
Never raises: a broken trace must not break the reading."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

LOG_FILE = Path(__file__).resolve().parents[2] / "speech.log"
MAX_BYTES = 512 * 1024


def enabled() -> bool:
    flag = os.environ.get("TXT_SPEECH_TRACE")
    if flag is not None:
        return flag == "1"
    return sys.platform != "win32"


def _run(arguments: list[str]) -> str:
    try:
        done = subprocess.run(arguments, capture_output=True, text=True, timeout=2)
        return " ".join(done.stdout.split())
    except Exception as error:  # diagnostics only
        return f"<{type(error).__name__}>"


def process_state(pid: int | None) -> str:
    """`ps` state of the player: T means stopped (paused), R/S running."""
    if pid is None or sys.platform == "win32":
        return "-"
    return _run(["ps", "-o", "stat=", "-p", str(pid)]) or "gone"


def players() -> str:
    """Every ffplay alive: more than one means an audio nobody controls."""
    if sys.platform == "win32":
        return "-"
    return _run(["pgrep", "-l", "ffplay"]) or "none"


def trace(event: str, **fields: object) -> None:
    if not enabled():
        return
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_BYTES:
            LOG_FILE.unlink()
        details = " ".join(f"{key}={value}" for key, value in fields.items())
        stamp = time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"
        with open(LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(f"{stamp} {event} {details}\n")
    except Exception:
        pass
