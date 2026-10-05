"""Tests for the Edge TTS helper without requiring the optional package."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "edge_tts_words.py"


class FakeCommunicate:
    calls: list[dict[str, object]] = []

    def __init__(self, text: str, voice: str, **options: object) -> None:
        self.calls.append({"text": text, "voice": voice, **options})

    async def stream(self):
        if False:
            yield None


fake_edge_tts = types.ModuleType("edge_tts")
fake_edge_tts.Communicate = FakeCommunicate
sys.modules["edge_tts"] = fake_edge_tts
spec = importlib.util.spec_from_file_location("edge_tts_words", SCRIPT_PATH)
assert spec and spec.loader
edge_tts_words = importlib.util.module_from_spec(spec)
spec.loader.exec_module(edge_tts_words)


class GenerateTests(unittest.TestCase):
    def test_passes_signed_rate_to_edge_tts(self) -> None:
        for rate, expected in ((-50, "-50%"), (0, "+0%"), (100, "+100%")):
            with self.subTest(rate=rate), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                text_file = root / "input.txt"
                text_file.write_text("Hola", encoding="utf-8")
                asyncio.run(
                    edge_tts_words.generate(
                        text_file,
                        root / "audio.mp3",
                        root / "words.json",
                        "es-AR-ElenaNeural",
                        rate,
                    )
                )

                self.assertEqual(FakeCommunicate.calls[-1]["rate"], expected)
                self.assertEqual(FakeCommunicate.calls[-1]["boundary"], "WordBoundary")


if __name__ == "__main__":
    unittest.main()
