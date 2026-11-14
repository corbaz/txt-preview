"""List Edge voices using the native system TLS trust (S17/T24).

macOS Python 3.14/Homebrew rejects the bundled certifi CA list
(``Basic Constraints of CA cert not marked critical``), so the voice
catalog and the Doctor probe both run through this wrapper: it injects
truststore (native macOS Keychain / Windows CryptoAPI trust) BEFORE
importing edge_tts — edge_tts builds its SSL context at import time — and
then prints one parser-compatible line per voice (``ShortName Gender
Locale``) for app/txt_core/speech/voices.py.

Certificate verification is never disabled here.
"""
from __future__ import annotations

import asyncio
import sys

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    truststore = None

import edge_tts  # noqa: E402


def format_voice_line(voice: dict) -> str:
    """One parser-compatible line per voice: ShortName Gender Locale."""
    return f"{voice['ShortName']} {voice['Gender']} {voice['Locale']}"


async def collect_voice_lines() -> list[str]:
    """Query the Edge service and return the parser-compatible lines."""
    voices = await edge_tts.list_voices()
    lines = [
        format_voice_line(voice)
        for voice in voices
        if voice.get("ShortName") and voice.get("Gender") and voice.get("Locale")
    ]
    if not lines:
        raise RuntimeError("el servicio no devolvió voces.")
    return lines


def main() -> int:
    """Print the catalog; fail nonzero with a useful stderr on any error."""
    # Voices are parsed by the app with UTF-8 text mode; force UTF-8 output so
    # a legacy locale console cannot corrupt voice names or the error line.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    try:
        for line in asyncio.run(collect_voice_lines()):
            print(line)
        return 0
    except Exception as error:  # noqa: BLE001 — controlled message for callers
        print(f"No se pudo consultar la lista de voces Edge: {error}",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
