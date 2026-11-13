"""Edge voice catalog, ported from txt.ps1 (ConvertFrom-EdgeVoiceCatalogText
2285, Invoke-EdgeVoiceCatalogProcess 2297, Save-/Read-EdgeVoiceCatalogCache
2339/2364, edge-voices.json under the settings dir).

The catalog runs `python -m edge_tts --list-voices` with a 15 second timeout,
parses the es/en Female/Male lines, and caches the result atomically so the
Configuración selector works offline on the next launch.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from typing import Any, Callable

from ..settings import settings_dir

VOICE_CATALOG_FILE = "edge-voices.json"
VOICE_CATALOG_VERSION = 1
VOICE_CATALOG_TIMEOUT_SECONDS = 15

# Legacy per-line filter: only es|en cultures with a Female|Male gender, and
# the line must carry trailing columns (the "\s+" after the gender).
_CATALOG_LINE = re.compile(
    r"^(?P<name>(?P<culture>(?:es|en)-[A-Z]{2})-\S+)\s+(?P<gender>Female|Male)\s+")
_CACHED_NAME = re.compile(r"^(?:es|en)-[A-Z]{2}-\S+$")
_CACHED_CULTURE = re.compile(r"^(?:es|en)-[A-Z]{2}$")

MSG_NO_PYTHON = "No se encontró Python para cargar las voces Edge."
MSG_NO_EDGE_TTS = ("Voces Edge: edge-tts no está instalado en el Python detectado. "
                   "Ejecutá install.ps1 y reabrí TXT.")
MSG_CATALOG_FAILED = "No se pudo cargar el catálogo de voces Edge ({detail})."
MSG_TIMEOUT = ("La consulta de voces Edge superó "
               f"{round(VOICE_CATALOG_TIMEOUT_SECONDS)} segundos.")
MSG_NO_VOICES = "La consulta no devolvió voces compatibles."


def _voice_record(name: str, culture: str, gender: str) -> dict[str, str]:
    return {
        "name": name,
        "culture": culture,
        "gender": gender,
        "display_name": f"Edge · {name} ({gender})",
    }


def parse_voice_catalog(text: str | None) -> list[dict[str, str]]:
    """Legacy ConvertFrom-EdgeVoiceCatalogText: {name, culture, gender,
    display_name} records for every es/en Female|Male line."""
    voices: list[dict[str, str]] = []
    for line in (text or "").splitlines():
        match = _CATALOG_LINE.match(line)
        if match:
            voices.append(_voice_record(match.group("name"),
                                        match.group("culture"),
                                        match.group("gender")))
    return voices


def fetch_voice_catalog(python_command: str, runner: Callable[..., Any] | None = None,
                        timeout_seconds: float = VOICE_CATALOG_TIMEOUT_SECONDS,
                        ) -> list[dict[str, str]]:
    """Legacy Invoke-EdgeVoiceCatalogProcess + ConvertFrom-EdgeVoiceCatalogText:
    run edge_tts --list-voices, parse the output; RuntimeError on any failure."""
    if not python_command:
        raise RuntimeError(MSG_NO_PYTHON)
    run = runner or subprocess.run
    try:
        completed = run(
            [python_command, "-m", "edge_tts", "--list-voices"],
            capture_output=True, text=True, timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(MSG_CATALOG_FAILED.format(detail=MSG_TIMEOUT)) from error
    except OSError as error:
        raise RuntimeError(MSG_CATALOG_FAILED.format(detail=str(error))) from error
    error_text = (completed.stderr or "").strip()
    if "No module named" in error_text and "edge_tts" in error_text:
        raise RuntimeError(MSG_NO_EDGE_TTS)
    voices = parse_voice_catalog(completed.stdout or "")
    if not voices:
        detail = MSG_NO_VOICES
        if (completed.returncode or 0) != 0:
            last_line = (error_text.splitlines() or [""])[-1]
            detail = last_line or f"el proceso terminó con código {completed.returncode}."
        raise RuntimeError(MSG_CATALOG_FAILED.format(detail=detail))
    return voices


def voice_cache_path(directory: str | None = None) -> str:
    """Legacy edge-voices.json location: the app settings dir."""
    return os.path.join(directory or settings_dir(), VOICE_CATALOG_FILE)


def load_voice_cache(directory: str | None = None) -> list[dict[str, str]]:
    """Legacy Read-EdgeVoiceCatalogCache: [] on missing/corrupt/wrong version."""
    try:
        with open(voice_cache_path(directory), encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict) or data.get("version") != VOICE_CATALOG_VERSION:
        return []
    stored = data.get("voices")
    if not isinstance(stored, list):
        return []
    voices: list[dict[str, str]] = []
    for entry in stored:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", ""))
        culture = str(entry.get("culture", ""))
        gender = str(entry.get("gender", ""))
        if not (_CACHED_NAME.match(name) and _CACHED_CULTURE.match(culture)
                and gender in ("Female", "Male")):
            continue
        voices.append(_voice_record(name, culture, gender))
    return voices


def save_voice_cache(voices_list: list[dict[str, str]],
                     directory: str | None = None) -> bool:
    """Legacy Save-EdgeVoiceCatalogCache: versioned schema, atomic write."""
    if not voices_list:
        return False
    path = voice_cache_path(directory)
    target_dir = os.path.dirname(path) or "."
    os.makedirs(target_dir, exist_ok=True)
    payload = {
        "version": VOICE_CATALOG_VERSION,
        "voices": [
            {"name": voice["name"], "culture": voice["culture"],
             "gender": voice["gender"], "display_name": voice["display_name"]}
            for voice in voices_list
        ],
    }
    descriptor, temp_path = tempfile.mkstemp(prefix=".edge-voices-",
                                             suffix=".tmp", dir=target_dir)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        os.replace(temp_path, path)
        return True
    except OSError:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        return False
