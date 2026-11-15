"""Edge-only speech engine, ported from txt.ps1's Edge pipeline (S6).

Responsibilities: chunk generation via edge_tts_words.py, ffplay playback,
pause/resume by suspending the player process, the elapsed audio clock that
excludes paused time, replay cache (concatenated chunk MP3s + cumulative mark
times), replay seek with the atempo chain, and speed handling.

The engine is UI-agnostic: it reports progress through an `emit` callback and
takes the preview word list from the caller (Initialize-SpeechAlignment).
Processes are created through `runner` so tests can inject fakes.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from .alignment import next_alignment_cursor
from .marks import (
    EdgeWordMark,
    edge_word_marks,
    get_mark_index_at,
    speech_alignment_key,
    speech_words_key,
)
from .replay import build_atempo_filter, format_replay_time, get_replay_word_timings  # noqa: F401 (re-exported)

HIGHLIGHT_LEAD_SECONDS = 0.06


def get_remaining_speech_text(texts: Sequence[str], current_index: int,
                              char_position: int) -> str:
    """Legacy Get-RemainingSpeechText: the current chunk from the first
    whitespace boundary at/after the character position plus every later
    chunk, joined by blank lines. Empty once the reading is exhausted."""
    if current_index < 0 or current_index >= len(texts):
        return ""
    current = texts[current_index]
    position = max(0, min(char_position, len(current)))
    while position < len(current) and not current[position].isspace():
        position += 1
    parts: list[str] = []
    remaining = current[position:].lstrip()
    if remaining:
        parts.append(remaining)
    parts.extend(texts[current_index + 1:])
    return "\n\n".join(parts)


def _speed_label(percent: int) -> str:
    """Legacy lblSpeedValue factor, es-AR decimal comma ('1,50x')."""
    return f"{percent / 100:.2f}".replace(".", ",") + "x"

REPO = Path(__file__).resolve().parents[3]
EDGE_TTS_WORDS_SCRIPT = REPO / "edge_tts_words.py"
TERMINATE_WAIT_SECONDS = 3


def _terminate_process(process: Any) -> None:
    """Kill a still-running (possibly suspended) process and reap it, so a
    restart or a close never leaves the old audio playing (S12). None or
    already-dead processes are ignored; errors are suppressed so a half-dead
    process cannot keep the shell from stopping the audio."""
    if process is None:
        return
    try:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=TERMINATE_WAIT_SECONDS)
    except Exception:
        pass


class SuspendResume:
    """Cross-platform process suspension for the audio player."""

    @staticmethod
    def suspend(pid: int) -> None:
        if sys.platform == "win32":
            import ctypes
            ntdll = ctypes.WinDLL("ntdll")  # type: ignore[attr-defined]
            handle = ctypes.WinDLL("kernel32").OpenProcess(0x1F0FFF, False, pid)  # type: ignore[attr-defined]
            if not handle:
                raise OSError(f"OpenProcess falló para el PID {pid}.")
            try:
                status = ntdll.NtSuspendProcess(handle)
                if status != 0:
                    raise OSError(f"Windows devolvió el código {status} al pausar el audio.")
            finally:
                ctypes.WinDLL("kernel32").CloseHandle(handle)  # type: ignore[attr-defined]
        else:
            os.kill(pid, 19)  # SIGSTOP

    @staticmethod
    def resume(pid: int) -> None:
        if sys.platform == "win32":
            import ctypes
            ntdll = ctypes.WinDLL("ntdll")  # type: ignore[attr-defined]
            handle = ctypes.WinDLL("kernel32").OpenProcess(0x1F0FFF, False, pid)  # type: ignore[attr-defined]
            if not handle:
                raise OSError(f"OpenProcess falló para el PID {pid}.")
            try:
                status = ntdll.NtResumeProcess(handle)
                if status != 0:
                    raise OSError(f"Windows devolvió el código {status} al continuar el audio.")
            finally:
                ctypes.WinDLL("kernel32").CloseHandle(handle)  # type: ignore[attr-defined]
        else:
            os.kill(pid, 18)  # SIGCONT


@dataclass
class Chunk:
    index: int
    text: str
    text_file: str
    media_file: str
    timing_file: str
    start_word_index: int
    process: Any = None
    status: str = "Pending"  # Pending | Generating | Ready | Playing | Played | Failed
    error_text: str = ""
    duration_seconds: float = 0.0
    word_timings: list[dict[str, Any]] = field(default_factory=list)
    word_marks: list[EdgeWordMark] = field(default_factory=list)
    aligned_marks: int = 0


@dataclass
class ReplayCache:
    file: str = ""
    duration: float = 0.0
    voice_display: str = ""
    words_key: str = ""
    mark_seconds: list[float] = field(default_factory=list)
    mark_words: list[int] = field(default_factory=list)
    eligible: bool = False


class SpeechEngine:
    """State machine for Edge reading and replay (legacy speechState)."""

    def __init__(self, python_command: str | None = None, ffplay_command: str | None = None,
                 ffprobe_command: str | None = None, emit: Callable[[str, str], None] | None = None,
                 runner: Callable[..., Any] | None = None) -> None:
        self.python_command = python_command or _find_command("python", "python3")
        self.ffplay_command = ffplay_command or _find_command("ffplay", "ffplay")
        self.ffprobe_command = ffprobe_command or _find_command("ffprobe", "ffprobe")
        self.emit = emit or (lambda level, message: None)
        self._runner = runner or subprocess.Popen

        self.mode = "Idle"  # Idle | Generating | Playing | Paused
        self.provider: str | None = None  # Edge | Replay
        self.voice_display: str | None = None
        self.voice_name: str | None = None
        self.session_id = 0
        self.chunks: list[Chunk] = []
        self.current_index = 0
        self.player_process: Any = None
        self.player_started_at: float | None = None
        self.pause_started_at: float | None = None
        self.applied_speed = 100

        self.align_words: list[str] = []
        self.align_words_key: str | None = None
        self.align_cursor = -1
        self.align_floor = -1
        self.align_misses = 0
        self._align_raw_words = ""
        # Legacy CacheStartCursor: preview cursor this session started from;
        # Repetir timings are offset by it (None until a session starts).
        self.session_start_cursor: int | None = None

        self.replay = ReplayCache()
        self.replay_offset = 0.0
        self.replay_tempo = 1.0
        self.replay_highlight_checked = False
        self.replay_highlight_valid = False

    # ---- Alignment ---------------------------------------------------------
    def initialize_alignment(self, raw_words: str) -> bool:
        if self.align_words:
            return True
        if not raw_words:
            return False
        self._align_raw_words = raw_words
        self.align_words = [speech_alignment_key(w) for w in raw_words.split("\n")]
        self.align_words_key = speech_words_key(raw_words)
        return True

    def reset_alignment(self, start_cursor: int = -1) -> None:
        self.align_words = []
        self.align_words_key = None
        self._align_raw_words = ""
        self.align_cursor = max(-1, start_cursor)
        self.align_floor = self.align_cursor
        self.align_misses = 0
        self.session_start_cursor = None

    def step_alignment(self, spoken_word: str) -> None:
        self.align_cursor, self.align_misses = next_alignment_cursor(
            self.align_words, self.align_cursor, self.align_misses, spoken_word,
        )

    def sync_chunk_alignment(self, chunk: Chunk, target_mark: int) -> None:
        if not self.align_words:
            return
        marks = chunk.word_marks
        target_mark = min(target_mark, len(marks) - 1)
        for i in range(chunk.aligned_marks, target_mark + 1):
            self.step_alignment(marks[i].text)
        chunk.aligned_marks = max(chunk.aligned_marks, target_mark + 1)

    # ---- Clock -------------------------------------------------------------
    def elapsed_seconds(self) -> float | None:
        if self.player_process is None or self.player_started_at is None:
            return None
        position_time = self.pause_started_at if self.pause_started_at is not None else time.time()
        return max(0.0, position_time - self.player_started_at)

    def get_mark_index(self, chunk: Chunk, elapsed: float) -> int:
        return get_mark_index_at(chunk.word_marks, elapsed, lead=HIGHLIGHT_LEAD_SECONDS)

    # ---- Session -----------------------------------------------------------
    def start_edge_session(self, text: str, voice_display: str, voice_name: str,
                           rate_percent: int = 100, start_cursor: int | None = None,
                           cache_eligible: bool = True) -> None:
        self._require_tools()
        self.session_id += 1
        self.provider = "Edge"
        self.voice_display = voice_display
        self.voice_name = voice_name
        self.current_index = 0
        self.player_process = None
        self.player_started_at = None
        self.pause_started_at = None
        self.chunks = []
        texts = _split_chunks(text, 6)
        start_word = 0
        temp = tempfile.gettempdir()
        for index, chunk_text in enumerate(texts):
            base = f"txt-preview-speech-{os.getpid()}-{self.session_id}-{index}"
            self.chunks.append(Chunk(
                index=index, text=chunk_text,
                text_file=os.path.join(temp, base + ".txt"),
                media_file=os.path.join(temp, base + ".mp3"),
                timing_file=os.path.join(temp, base + ".words.json"),
                start_word_index=start_word,
            ))
            start_word += len(chunk_text.split())
        for chunk in self.chunks:
            self._start_chunk_generation(chunk, voice_name, rate_percent)
        # Legacy CacheStartCursor: the alignment floor this session starts
        # from (a Move-SpeechToWord jump passes wordIndex - 1).
        self.session_start_cursor = (max(-1, int(start_cursor))
                                     if start_cursor is not None else self.align_floor)
        # Legacy: only a reading started by Play is a new generation; voice or
        # speed restarts are partial and never replace the Repetir cache.
        self.replay.eligible = cache_eligible
        self.mode = "Generating"
        self.emit("info", f"Preparando {len(self.chunks)} bloques; el primero se reproducirá apenas esté listo...")

    def _require_tools(self) -> None:
        if not self.python_command:
            raise RuntimeError("No se encontró Python para generar la voz Edge.")
        if not EDGE_TTS_WORDS_SCRIPT.exists():
            raise RuntimeError("No se encontró el generador de sincronización WordBoundary.")
        if not self.ffplay_command:
            raise RuntimeError("No se encontró ffplay para reproducir la voz Edge.")

    def _start_chunk_generation(self, chunk: Chunk, voice_name: str, rate_percent: int) -> None:
        with open(chunk.text_file, "w", encoding="utf-8", newline="") as handle:
            handle.write(chunk.text)
        chunk.process = self._runner(
            [self.python_command, str(EDGE_TTS_WORDS_SCRIPT),
             "--voice", voice_name,
             "--rate", str(rate_percent - 100),
             "--text-file", chunk.text_file,
             "--media-file", chunk.media_file,
             "--timings-file", chunk.timing_file],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        chunk.status = "Generating"

    # ---- Tick (legacy Update-EdgeVoicePlayback + Start-CurrentEdgeChunk) ----
    def poll(self) -> None:
        for chunk in self.chunks:
            if chunk.status != "Generating" or chunk.process is None or chunk.process.poll() is None:
                continue
            exit_code = chunk.process.returncode
            error_text = ""
            try:
                error_text = (chunk.process.stderr.read() or b"").decode("utf-8", errors="replace").strip()
            except (OSError, ValueError):
                pass
            chunk.process = None
            _remove_file(chunk.text_file)
            if (exit_code == 0 and os.path.isfile(chunk.media_file)
                    and os.path.isfile(chunk.timing_file)):
                chunk.duration_seconds = self._audio_duration(chunk.media_file, chunk.text)
                with open(chunk.timing_file, encoding="utf-8") as handle:
                    import json
                    chunk.word_timings = json.load(handle)
                _remove_file(chunk.timing_file)
                chunk.word_marks = edge_word_marks(chunk.text, chunk.word_timings)
                chunk.status = "Ready"
            else:
                chunk.status = "Failed"
                chunk.error_text = (error_text.splitlines() or [""])[-1] or f"El bloque {chunk.index + 1} no pudo generarse."

        player = self.player_process
        if player is not None and player.poll() is not None:
            exit_code = player.returncode
            self.player_process = None
            self.player_started_at = None
            self.pause_started_at = None
            if self.provider == "Replay":
                # Legacy txt.ps1:4457: a finished repetition returns to Idle
                # (the replay cache stays for another Repetir).
                self.mode = "Idle"
                if exit_code == 0:
                    self.emit("info", "Repetición finalizada.")
                else:
                    self.emit("error", "No se pudo repetir el audio: el reproductor terminó con un error.")
            else:
                completed = self.chunks[self.current_index]
                if self.align_words:
                    self.sync_chunk_alignment(completed, len(completed.word_marks) - 1)
                completed.status = "Played"
                if exit_code != 0:
                    self.stop_voice_playback()
                    self.emit("error", "No se pudo reproducir la voz Edge: el reproductor terminó con un error.")
                    return
                self.current_index += 1

        self._start_current_chunk()
        self._sync_alignment_tick()

    def _audio_duration(self, media_file: str, text: str) -> float:
        """Real duration via ffprobe, else the legacy word-count estimate."""
        if self.ffprobe_command:
            try:
                result = subprocess.run(
                    [self.ffprobe_command, "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", media_file],
                    capture_output=True, text=True, timeout=30,
                )
                duration = float((result.stdout or "").strip())
                if duration > 0:
                    return duration
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        word_count = len(re.findall(r"\S+", text))
        return max(1.0, word_count / 2.5)

    def _clear_replay_cache(self) -> None:
        if self.replay.file:
            _remove_file(self.replay.file)
        self.replay = ReplayCache()

    # ---- Replay playback (legacy Start-ReplayPlayback) ----------------------
    def start_replay_playback(self, offset_seconds: float = 0.0) -> None:
        if not self.ffplay_command:
            self.emit("error", "No se encontró ffplay para repetir el audio.")
            return
        if not self.replay.file or not os.path.isfile(self.replay.file):
            self._clear_replay_cache()
            self.emit("warning", "No hay audio generado para repetir. Usá Play primero.")
            return
        offset = min(max(0.0, offset_seconds), max(0.0, self.replay.duration - 0.2))
        tempo = max(1, self.applied_speed) / 100.0
        arguments = [self.ffplay_command, "-nodisp", "-autoexit", "-loglevel", "error"]
        if offset > 0:
            arguments += ["-ss", f"{offset:.3f}"]
        tempo_filter = build_atempo_filter(tempo)
        if tempo_filter:
            arguments += ["-af", tempo_filter]
        arguments.append(self.replay.file)
        _terminate_process(self.player_process)
        self.player_process = self._runner(
            arguments, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.player_started_at = time.time()
        self.pause_started_at = None
        self.replay_offset = offset
        self.replay_tempo = tempo
        self.provider = "Replay"
        self.voice_display = self.replay.voice_display
        self.mode = "Playing"
        self.replay_highlight_checked = False
        self.emit("info", f"Repitiendo el último audio desde {format_replay_time(offset)} · {self.replay.voice_display}")

    def _start_current_chunk(self) -> None:
        if self.mode == "Paused" or self.player_process is not None:
            return
        if self.current_index >= len(self.chunks):
            self._finish_edge_reading()
            return
        chunk = self.chunks[self.current_index]
        if chunk.status != "Ready":
            return
        self.player_process = self._runner(
            [self.ffplay_command, "-nodisp", "-autoexit", "-loglevel", "error", chunk.media_file],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.player_started_at = time.time()
        self.pause_started_at = None
        self.mode = "Playing"
        chunk.status = "Playing"
        self.emit("info", f"Reproduciendo bloque {self.current_index + 1} de {len(self.chunks)} · {self.voice_display}")

    def _finish_edge_reading(self) -> None:
        """Natural end of an Edge reading (legacy Start-CurrentEdgeChunk tail):
        save the Repetir cache exactly like a manual stop does, drop the chunk
        audio and go back to Idle, so a later preview click never restarts the
        reading by itself (S12)."""
        if self.provider != "Edge" or self.mode != "Playing":
            return
        if self.player_process is not None or not self.chunks:
            return
        if self.current_index < len(self.chunks):
            return
        if any(chunk.status != "Played" for chunk in self.chunks):
            return
        self._save_replay_cache()
        self.cache_clear_files()
        self.cache_eligible_off()
        self.mode = "Idle"
        self.emit("info", "Lectura con voz Edge finalizada.")

    def _sync_alignment_tick(self) -> None:
        if self.provider != "Edge" or self.current_index >= len(self.chunks):
            return
        chunk = self.chunks[self.current_index]
        elapsed = self.elapsed_seconds()
        if elapsed is None or not chunk.word_marks:
            return
        self.sync_chunk_alignment(chunk, self.get_mark_index(chunk, elapsed))

    # ---- Pause / resume / stop ---------------------------------------------
    def pause(self) -> None:
        if self.mode == "Idle":
            self.emit("warning", "No hay una lectura activa para pausar.")
            return
        if self.player_process is not None and self.player_process.poll() is None:
            SuspendResume.suspend(self.player_process.pid)
            self.pause_started_at = time.time()
        self.mode = "Paused"
        self.emit("info", "Lectura pausada.")

    def resume(self) -> None:
        if self.mode != "Paused":
            self.emit("warning", "La lectura no está pausada.")
            return
        if self.player_process is not None and self.player_process.poll() is None:
            SuspendResume.resume(self.player_process.pid)
            if self.pause_started_at is not None and self.player_started_at is not None:
                self.player_started_at += time.time() - self.pause_started_at
            self.pause_started_at = None
            self.mode = "Playing"
        else:
            self.mode = "Generating"
        self.emit("info", "Continuando la lectura desde la posición pausada.")

    def set_speed(self, percent: int) -> None:
        """Legacy Set-SpeechSpeed + Restart-ActiveSpeechPlayback: a live Edge
        reading restarts from the current position with the remaining text at
        the new rate, keeping the highlight; a paused reading stays paused.
        Replay keeps the caller-side restart (same audio, new tempo)."""
        percent = int(percent)
        self.applied_speed = percent
        if self.provider == "Replay" or self.provider is None:
            return
        # Idle with leftover chunks means the reading just finished naturally:
        # the restart path runs and reports the legacy already-finished warning.
        finished = self.mode == "Idle" and bool(self.chunks)
        if not finished and self.mode not in ("Playing", "Paused"):
            return
        self._restart_active_playback(
            f"Velocidad cambiada a {_speed_label(percent)}.",
            self.voice_display, self.voice_name)

    def set_voice(self, voice_display: str, voice_name: str) -> None:
        """Legacy Switch-ActiveSpeechVoice: a live Edge reading restarts from
        the current position with the new voice. Repetir plays audio that is
        already generated, so the new voice only applies to the next Play."""
        if self.mode not in ("Playing", "Paused") or voice_name == self.voice_name:
            return
        if self.provider == "Replay":
            self.emit("warning", "Repetir usa el audio ya generado; el cambio se aplica "
                                 "en la próxima lectura con Play.")
            return
        self._restart_active_playback(f"Voz cambiada a {voice_display}.",
                                      voice_display, voice_name)

    def _restart_active_playback(self, message: str, voice_display: str | None,
                                 voice_name: str | None) -> None:
        """Legacy Restart-ActiveSpeechPlayback: read the remaining text again
        from the current position, keeping the highlight and the pause."""
        was_paused = self.mode == "Paused"
        char_position = self._edge_character_position()
        texts = [chunk.text for chunk in self.chunks]
        remaining = get_remaining_speech_text(texts, self.current_index, char_position)
        cursor = self.align_cursor
        raw_words = self._align_raw_words
        self.stop_voice_playback()
        if not remaining.strip():
            self.emit("warning", "La lectura ya había finalizado.")
            return
        # Keep the highlight where it was: the floor moves to the current
        # word cursor and the restarted reading advances from there.
        self.reset_alignment(cursor)
        self.initialize_alignment(raw_words)
        self.start_edge_session(remaining, voice_display, voice_name,
                                rate_percent=self.applied_speed)
        # Voice/speed restarts are partial readings: never replace Repetir.
        self.replay.eligible = False
        if was_paused:
            self.pause()
            self.emit("info", f"{message} La lectura permanece pausada.")
        else:
            self.emit("info", f"{message} Continuando desde la posición actual.")

    def _edge_character_position(self) -> int:
        """Legacy Get-EdgeChunkCharacterPosition: character offset of the word
        the audio clock is currently on, within the current chunk text."""
        if self.current_index >= len(self.chunks):
            return 0
        chunk = self.chunks[self.current_index]
        elapsed = self.elapsed_seconds()
        if elapsed is None or not chunk.word_marks:
            return 0
        mark_index = self.get_mark_index(chunk, elapsed)
        if mark_index < 0:
            return 0
        return chunk.word_marks[mark_index].character

    def stop_voice_playback(self) -> None:
        was_replay = self.provider == "Replay"
        # The replay cache reads the chunk media files, not the processes:
        # save it first, then terminate every live audio process (S12).
        self._save_replay_cache()
        _terminate_process(self.player_process)
        for chunk in self.chunks:
            _terminate_process(chunk.process)
        self.cache_clear_files()
        self.cache_eligible_off()
        self.mode = "Idle"
        self.provider = None
        self.voice_display = None
        self.voice_name = None
        self.chunks = []
        self.current_index = 0
        self.player_process = None
        self.player_started_at = None
        self.pause_started_at = None
        self.reset_alignment()
        if was_replay:
            self.replay_highlight_checked = False

    # ---- Replay cache ------------------------------------------------------
    def cache_clear_files(self) -> None:
        for chunk in self.chunks:
            _remove_file(chunk.media_file)

    def cache_eligible_off(self) -> None:
        self.replay.eligible = False

    def _save_replay_cache(self) -> None:
        if not self.replay.eligible or not self.ffplay_command:
            return
        ready = [c for c in self.chunks if c.status in ("Ready", "Playing", "Played")]
        if len(ready) != len(self.chunks) or not self.chunks:
            return
        if not all(os.path.isfile(c.media_file) for c in self.chunks):
            return
        replay_file = os.path.join(tempfile.gettempdir(),
                                   f"txt-preview-replay-{os.getpid()}-{self.session_id}.mp3")
        try:
            with open(replay_file, "wb") as out:
                for chunk in self.chunks:
                    with open(chunk.media_file, "rb") as src:
                        out.write(src.read())
        except OSError as error:
            self.emit("warning", f"No se pudo preparar Repetir: {error}")
            return
        mark_seconds: list[float] = []
        spoken_words: list[str] = []
        chunk_offset = 0.0
        duration = 0.0
        for chunk in self.chunks:
            duration += chunk.duration_seconds
            for mark in chunk.word_marks:
                mark_seconds.append(chunk_offset + mark.start_seconds)
                spoken_words.append(mark.text)
            chunk_offset += chunk.duration_seconds
        if duration <= 0:
            self.emit("warning", "El audio generado está vacío.")
            _remove_file(replay_file)
            return
        if mark_seconds and mark_seconds[-1] > duration + 0.05:
            # Word times beyond the audio mean a clock mismatch: keep the audio, drop the marks.
            mark_seconds.clear()
            spoken_words.clear()
        # Legacy Get-ReplayWordTimings: re-run the live aligner over every
        # spoken word so Repetir marks the same preview words the reading did.
        timings: dict[str, list] | None = None
        if (mark_seconds and self.session_start_cursor is not None
                and self.align_words and self.align_words_key):
            timings = get_replay_word_timings(
                mark_seconds, spoken_words, self.align_words, self.session_start_cursor)
        mark_words = list(timings["words"]) if timings else []
        mark_seconds = list(timings["seconds"]) if timings else []
        self.replay = ReplayCache(
            file=replay_file, duration=duration,
            voice_display=self.voice_display or "",
            words_key=self.align_words_key or "",
            mark_seconds=mark_seconds, mark_words=mark_words,
            eligible=False,
        )


def _find_command(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def _remove_file(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _split_chunks(text: str, desired: int) -> list[str]:
    from .chunker import split_text_into_speech_chunks
    return split_text_into_speech_chunks(text, desired)
