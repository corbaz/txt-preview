"""Generate an MP3 with Edge TTS using the native system TLS trust (S17/T24).

macOS Python 3.14/Homebrew rejects the bundled certifi CA list
(``Basic Constraints of CA cert not marked critical``), so MP3 synthesis
runs through this wrapper instead of ``python -m edge_tts``: it injects
truststore (native macOS Keychain / Windows CryptoAPI trust) BEFORE
importing edge_tts — edge_tts builds its SSL context at import time — and
then synthesizes the MP3 from a UTF-8 text file.

Certificate verification is never disabled here.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    truststore = None

import edge_tts  # noqa: E402


async def generate(
    text_file: Path,
    media_file: Path,
    voice: str,
    rate: int = 0,
) -> None:
    """Write the synthesized MP3 (audio chunks of edge_tts.Communicate)."""
    text = text_file.read_text(encoding="utf-8")
    communicator = edge_tts.Communicate(text, voice, rate=f"{rate:+d}%")
    # Lazy open: a failed synthesis must not leave an empty media file
    # behind, so the file is created only when real audio arrives.
    audio = None
    try:
        async for chunk in communicator.stream():
            if chunk.get("type") == "audio":
                data = chunk.get("data")
                if data:
                    if audio is None:
                        audio = media_file.open("wb")
                    audio.write(data)
    finally:
        if audio is not None:
            audio.close()


def _discard_partial_media(media_file: Path) -> None:
    """Best-effort removal of a half-written MP3 after a failure."""
    try:
        media_file.unlink()
    except OSError:
        pass


def main() -> int:
    """Synthesize and fail nonzero with a useful stderr on any error."""
    # The parent process decodes our stderr as UTF-8 regardless of the CI
    # locale, so make this child emit UTF-8 explicitly (a legacy cp1252
    # console would otherwise mojibake accented Spanish messages).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice", required=True)
    parser.add_argument("--rate", type=int, default=0)
    parser.add_argument("--text-file", type=Path, required=True)
    parser.add_argument("--media-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        asyncio.run(
            generate(args.text_file, args.media_file, args.voice, args.rate)
        )
    except Exception as error:  # noqa: BLE001 — controlled message for callers
        _discard_partial_media(args.media_file)
        # The last stderr line is the error itself: app/txt_core/exports.py
        # composes the legacy message "No se pudo generar el MP3: <detail>".
        print("No se pudo sintetizar el audio con la voz Edge:", file=sys.stderr)
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
