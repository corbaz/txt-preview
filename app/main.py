"""TXT Preview — cross-platform entry point.

Runs the same application on Windows (WebView2) and macOS (WKWebView)
through pywebview. Legacy Windows-only app: ../txt.ps1.
"""
from __future__ import annotations

import sys
from pathlib import Path

import webview

ROOT = Path(__file__).resolve().parent
APP = ROOT
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from txt_core.markdown import render_markdown
from txt_core.speech.engine import SpeechEngine

REPO = ROOT.parent
WWW = ROOT / "www"

VERSION_FILE = REPO / "VERSION"

# Edge voice catalog lands in a later step; this is the default reading voice.
DEFAULT_SPEECH_VOICE = "es-ES-ElviraNeural"
DEFAULT_SPEECH_VOICE_DISPLAY = "Elvira (es-ES)"
SPEECH_SPEED_MIN = 50
SPEECH_SPEED_MAX = 200


def read_version() -> str:
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    return "dev"


class Api:
    """Bridge exposed to the frontend as window.pywebview.api."""

    def __init__(self) -> None:
        self.engine = SpeechEngine(emit=self._on_engine_message)
        self._pending_click: int | None = None
        self._speech_words = ""
        self._speech_speed = 100
        self._last_message = ""

    # ---- Existing bridge ---------------------------------------------------
    def app_version(self) -> str:
        return read_version()

    def platform(self) -> str:
        return sys.platform

    def render_preview(self, text: str) -> str:
        """Sanitized markdown HTML for Vista previa."""
        return render_markdown(text)

    # ---- Speech (T4/S6) ----------------------------------------------------
    def _on_engine_message(self, level: str, message: str) -> None:
        self._last_message = message

    def start_speech(self, text: str, raw_words: str | None = None) -> dict:
        """Start an Edge reading of the editor text; raw_words are the preview spans."""
        try:
            self.engine.stop_voice_playback()
            self._speech_words = raw_words or ""
            self.engine.initialize_alignment(self._speech_words)
            self.engine.start_edge_session(
                text, DEFAULT_SPEECH_VOICE_DISPLAY, DEFAULT_SPEECH_VOICE,
                rate_percent=self._speech_speed,
            )
            return {"ok": True, "message": self._last_message}
        except Exception as error:  # keep the shell alive; report to the UI
            return {"ok": False, "message": str(error)}

    def stop_speech(self) -> dict:
        self.engine.stop_voice_playback()
        return {"ok": True, "message": self._last_message}

    def pause_speech(self) -> dict:
        self.engine.pause()
        return {"ok": True, "message": self._last_message}

    def resume_speech(self) -> dict:
        self.engine.resume()
        return {"ok": True, "message": self._last_message}

    def set_speech_speed(self, percent: int) -> dict:
        speed = max(SPEECH_SPEED_MIN, min(SPEECH_SPEED_MAX, int(percent)))
        self._speech_speed = speed
        self.engine.applied_speed = speed
        # Replay re-renders the same audio at the new tempo from the current
        # position (legacy Set-SpeechSpeed); an Edge reading picks the rate up
        # on the next jump/play.
        if self.engine.provider == "Replay" and self.engine.mode in ("Playing", "Paused"):
            was_paused = self.engine.mode == "Paused"
            position = self._replay_position()
            self.engine.start_replay_playback(position)
            if was_paused:
                self.engine.pause()
        return {"ok": True, "message": self._last_message}

    def replay_start(self, offset_seconds: float = 0.0) -> dict:
        try:
            self.engine.start_replay_playback(float(offset_seconds))
            return {"ok": True, "message": self._last_message}
        except Exception as error:
            return {"ok": False, "message": str(error)}

    def speech_click(self, word_index: int, text: str | None = None) -> dict:
        """Queue a preview-word click; text is the block-aware tail (legacy getSpeechTextFrom)."""
        try:
            index = int(word_index)
        except (TypeError, ValueError):
            index = -1
        self._pending_click = (index, text) if index >= 0 else None
        return {"ok": True}

    def speech_tick(self) -> dict:
        try:
            self.engine.poll()
        except Exception as error:
            self._last_message = str(error)
        click = self._pending_click
        self._pending_click = None
        if click is not None:
            self._move_speech_to_word(click[0], click[1])
        return self._speech_state()

    # ---- Speech internals --------------------------------------------------
    def _speech_state(self) -> dict:
        engine = self.engine
        cursor = engine.align_cursor
        highlight = cursor if cursor > engine.align_floor else None
        return {
            "mode": engine.mode,
            "provider": engine.provider,
            "highlight_word_index": highlight,
            "replay_position": round(self._replay_position(), 3),
            "replay_duration": round(engine.replay.duration, 3),
            "message": self._last_message,
        }

    def _replay_position(self) -> float:
        engine = self.engine
        if engine.provider != "Replay":
            return 0.0
        elapsed = engine.elapsed_seconds()
        if elapsed is None:
            return engine.replay_offset
        return min(engine.replay.duration,
                   engine.replay_offset + elapsed * engine.replay_tempo)

    def _move_speech_to_word(self, index: int, text: str | None = None) -> None:
        """Legacy Move-SpeechToWord: restart the reading from the clicked word."""
        engine = self.engine
        if engine.mode == "Idle" or engine.provider == "Replay" or index < 0:
            return
        if not text:
            words = self._speech_words.split("\n") if self._speech_words else []
            text = " ".join(words[index:])
        if not text.strip():
            return
        was_paused = engine.mode == "Paused"
        try:
            engine.stop_voice_playback()
            engine.reset_alignment(index - 1)
            engine.initialize_alignment(self._speech_words)
            engine.start_edge_session(
                text, DEFAULT_SPEECH_VOICE_DISPLAY, DEFAULT_SPEECH_VOICE,
                rate_percent=self._speech_speed,
            )
            if was_paused:
                engine.pause()
        except Exception as error:
            self._last_message = f"No se pudo saltar a la palabra elegida: {error}"


def create_app() -> None:
    window = webview.create_window(
        "TXT Preview",
        str(WWW / "index.html"),
        js_api=Api(),  # speech engine lives on the bridge (T4)
        width=1100,
        height=760,
        min_size=(720, 480),
    )
    webview.start(private_mode=False)


if __name__ == "__main__":
    create_app()
