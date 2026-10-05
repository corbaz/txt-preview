"""Generate Edge TTS audio plus exact WordBoundary timing metadata."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import edge_tts


async def generate(
    text_file: Path,
    media_file: Path,
    timings_file: Path,
    voice: str,
    rate: int = 0,
) -> None:
    """Write the synthesized MP3 and a JSON list of per-word audio offsets."""
    text = text_file.read_text(encoding="utf-8")
    communicator = edge_tts.Communicate(
        text,
        voice,
        rate=f"{rate:+d}%",
        boundary="WordBoundary",
    )
    timings: list[dict[str, object]] = []

    with media_file.open("wb") as audio:
        async for chunk in communicator.stream():
            # TTSChunk keys are optional per chunk type, so read them defensively.
            chunk_type = chunk.get("type")
            if chunk_type == "audio":
                data = chunk.get("data")
                if data:
                    audio.write(data)
            elif chunk_type == "WordBoundary":
                offset = chunk.get("offset")
                duration = chunk.get("duration")
                word = chunk.get("text")
                if offset is None or duration is None or word is None:
                    continue
                # Edge reports offsets in 100-nanosecond ticks.
                timings.append(
                    {
                        "start_seconds": offset / 10_000_000,
                        "duration_seconds": duration / 10_000_000,
                        "text": word,
                    }
                )

    timings_file.write_text(
        json.dumps(timings, ensure_ascii=False),
        encoding="utf-8",
    )


def main() -> None:
    """Parse command-line arguments and run the generator."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice", required=True)
    parser.add_argument("--rate", type=int, default=0)
    parser.add_argument("--text-file", type=Path, required=True)
    parser.add_argument("--media-file", type=Path, required=True)
    parser.add_argument("--timings-file", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(
        generate(
            args.text_file,
            args.media_file,
            args.timings_file,
            args.voice,
            args.rate,
        )
    )


if __name__ == "__main__":
    main()
