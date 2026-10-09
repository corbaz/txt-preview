"""Tests for AI answer cleanup and for stopping speech when an AI request starts."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = (ROOT / "txt.ps1").read_text(encoding="utf-8")

# The AI request paths: three buttons with their own handler and the shared translation.
AI_REQUEST_BLOCKS = {
    "Corregir": r"\$btnCorregir\.Add_Click\(\{(?P<body>.*?)\n\}\)",
    "Preguntar": r"\$btnPreguntar\.Add_Click\(\{(?P<body>.*?)\n\}\)",
    "Resumir": r"\$btnResumir\.Add_Click\(\{(?P<body>.*?)\n\}\)",
    "Traducir": r"function Invoke-Translation \{(?P<body>.*?)\n\}",
}


def block(pattern: str) -> str:
    match = re.search(pattern, SCRIPT, re.DOTALL)
    if match is None:
        raise AssertionError(f"pattern not found: {pattern}")
    return match.group("body")


class AiRequestStopsSpeechTests(unittest.TestCase):
    def test_every_ai_request_stops_speech_before_it_starts(self) -> None:
        for name, pattern in AI_REQUEST_BLOCKS.items():
            with self.subTest(name):
                body = block(pattern)
                self.assertIn("Stop-SpeechForAiRequest", body)
                self.assertLess(body.index("Stop-SpeechForAiRequest"), body.index("Start-Busy"))
                self.assertLess(body.index("Stop-SpeechForAiRequest"), body.index("Invoke-GroqRequest"))
        # No other request path exists that could skip the helper.
        self.assertEqual(SCRIPT.count("Invoke-GroqRequest -Headers"), len(AI_REQUEST_BLOCKS))

    def test_helper_stops_reading_and_deletes_the_repetir_audio(self) -> None:
        body = block(r"function Stop-SpeechForAiRequest \{(?P<body>.*?)\n\}")
        self.assertIn("Stop-VoicePlayback", body)
        self.assertLess(body.index("Stop-VoicePlayback"), body.index("Clear-SpeechReplayCache"))


if __name__ == "__main__":
    unittest.main()
