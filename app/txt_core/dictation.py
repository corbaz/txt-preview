"""Micrófono: dictation by a speech model on this machine.

Runs dictation_listen.py (repo root, shared with txt.ps1) and turns its lines
into state the page polls. The system dictation is not used: macOS cannot
start it from the app, and the button must know whether it is dictating."""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[2]
LISTEN_SCRIPT = REPO / "dictation_listen.py"
LIST_TIMEOUT_SECONDS = 20
STOP_WAIT_SECONDS = 8

MSG_LOADING = "Preparando el dictado..."
MSG_LISTENING = "Dictando. Presioná Esc o Micrófono para detenerlo."
MSG_STOPPED = "Dictado detenido."
MSG_NO_PYTHON = "No se encontró Python para el dictado."
MSG_FAILED = "No se pudo dictar: {detail}. El editor quedó listo para escribir."
MSG_ENDED = "el dictado terminó sin avisar"


def _hidden() -> dict:
    """No console window on Windows."""
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def list_microphones(python_command: str | None,
                     runner: Callable[..., Any] | None = None) -> list[str]:
    """Names of the microphones, as the system gives them; empty when the
    dictation packages are missing."""
    if not python_command:
        return []
    run = runner or subprocess.run
    try:
        done = run([python_command, str(LISTEN_SCRIPT), "--list"], capture_output=True,
                   timeout=LIST_TIMEOUT_SECONDS, **_hidden())
    except Exception:
        return []
    names = []
    for line in (done.stdout or b"").decode("utf-8", errors="replace").splitlines():
        if line.startswith("mic "):
            names.append(line[4:].strip())
    return names


class Dictation:
    """One dictation at a time: idle → loading → listening → idle."""

    def __init__(self, python_command: str | None,
                 runner: Callable[..., Any] | None = None) -> None:
        self.python_command = python_command
        self._runner = runner or subprocess.Popen
        self._lock = threading.Lock()
        self._process: Any = None
        self._control = ""
        self._state = "idle"
        self._text = ""       # committed words not handed to the page yet
        self._partial = ""    # what the model still guesses at
        self._message = ""
        self._level = "info"

    @property
    def active(self) -> bool:
        return self._state != "idle"

    def start(self, language: str, microphone: str = "") -> dict:
        with self._lock:
            if self._state != "idle":
                return {"ok": True, "state": self._state}
            if not self.python_command:
                return {"ok": False, "message": MSG_FAILED.format(detail=MSG_NO_PYTHON)}
            self._control = os.path.join(
                tempfile.gettempdir(), f"txt-dictation-{os.getpid()}-{int(time.time() * 1000)}.txt")
            arguments = [self.python_command, str(LISTEN_SCRIPT), language or "es", self._control]
            if microphone:
                arguments.append(microphone)
            try:
                self._process = self._runner(
                    arguments, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL, **_hidden())
            except Exception as error:
                return {"ok": False, "message": MSG_FAILED.format(detail=error)}
            self._state = "loading"
            self._text = ""
            self._partial = ""
            self._message = MSG_LOADING
            self._level = "info"
            threading.Thread(target=self._read, args=(self._process,), daemon=True).start()
            return {"ok": True, "state": self._state}

    def stop(self) -> dict:
        """Ask the listener to finish: the phrase under way is still written."""
        with self._lock:
            if self._state == "idle":
                return {"ok": True, "state": "idle"}
            process, control = self._process, self._control
            self._state = "stopping"
        try:
            with open(control, "w", encoding="utf-8") as handle:
                handle.write("stop")
        except OSError:
            pass
        threading.Thread(target=self._kill_if_stuck, args=(process,), daemon=True).start()
        return {"ok": True, "state": "stopping"}

    def close(self) -> None:
        """App is closing: no listener is left behind holding the microphone."""
        with self._lock:
            process = self._process
            self._state = "idle"
        if process is not None:
            try:
                if process.poll() is None:
                    process.kill()
            except Exception:
                pass

    def poll(self) -> dict:
        """State for the page; the committed text and the message are handed
        over once."""
        with self._lock:
            result = {"state": self._state, "text": self._text, "partial": self._partial,
                      "message": self._message, "level": self._level}
            self._text = ""
            self._message = ""
            return result

    # ---- Listener output ------------------------------------------------------
    def _kill_if_stuck(self, process: Any) -> None:
        try:
            process.wait(timeout=STOP_WAIT_SECONDS)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def _read(self, process: Any) -> None:
        finished = False
        try:
            for raw in process.stdout:
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if self._take(line):
                    finished = True
        except Exception:
            pass
        with self._lock:
            if self._process is not process:
                return  # a newer dictation owns the state
            if not finished and self._state != "idle":
                if self._state == "stopping":
                    self._message, self._level = MSG_STOPPED, "info"
                else:
                    self._message = MSG_FAILED.format(detail=MSG_ENDED)
                    self._level = "error"
            self._state = "idle"
            self._partial = ""
            self._process = None

    def _take(self, line: str) -> bool:
        """Apply one listener line; True when it ends the dictation."""
        kind, _, rest = line.partition(" ")
        with self._lock:
            if kind == "ready":
                if self._state == "loading":
                    self._state = "listening"
                    self._message, self._level = MSG_LISTENING, "info"
            elif kind == "text":
                # "text <n> <words>": the words keep their leading space.
                self._text += rest.partition(" ")[2]
                self._partial = ""
            elif kind == "partial":
                self._partial = rest.partition(" ")[2].strip()
            elif kind == "done":
                self._message, self._level = MSG_STOPPED, "info"
                return True
            elif kind == "error":
                self._message = MSG_FAILED.format(detail=rest.strip() or "error desconocido")
                self._level = "error"
                return True
        return False
