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


class CitationStripStaticTests(unittest.TestCase):
    def test_every_answer_goes_through_one_cleanup(self) -> None:
        body = block(r"function Get-AiResponseText \{(?P<body>.*?)\n\}")
        self.assertIn("Remove-AiCitationMarkers", body)
        # The raw model text is read in exactly one place.
        self.assertEqual(SCRIPT.count("message.content"), 1)
        self.assertEqual(SCRIPT.count("Get-AiResponseText $response"), len(AI_REQUEST_BLOCKS))


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "needs Windows and PowerShell 7")
class CitationStripBehaviorTests(unittest.TestCase):
    CASES = [
        (
            "Experiencia previa Puestos de supervisión, subgerencia o gerencia en el sector retail【2†L58-L62】",
            "Experiencia previa Puestos de supervisión, subgerencia o gerencia en el sector retail",
        ),
        ("Texto con fuente 【0†source】.", "Texto con fuente."),
        ("Uno【3†L10】, dos【1†L2-L4】 y tres", "Uno, dos y tres"),
        ("Antes 【4†L1】 después", "Antes después"),
        ("Fin de frase【5†L9】 .", "Fin de frase."),
        ("Línea 1【2†L1】\nLínea 2", "Línea 1\nLínea 2"),
        ("Ver [enlace](https://example.com/a) y [nota] sin cambios.", "Ver [enlace](https://example.com/a) y [nota] sin cambios."),
        ("Corchetes 【sin daga】 se mantienen.", "Corchetes 【sin daga】 se mantienen."),
    ]

    def test_markers_are_removed_and_everything_else_is_kept(self) -> None:
        payload = base64.b64encode(json.dumps([case[0] for case in self.CASES]).encode("utf-8")).decode("ascii")
        command = (
            "$env:TXT_PREVIEW_TEST_MODE = '1'; "
            f". '{ROOT / 'txt.ps1'}'; "
            f"$inputs = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload}')) | ConvertFrom-Json; "
            "$outputs = @($inputs | ForEach-Object { Remove-AiCitationMarkers $_ }); "
            "'RESULT:' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -InputObject $outputs -Compress)))"
        )
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-STA", "-Command", command],
            capture_output=True, timeout=120, encoding="utf-8", errors="replace",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        line = [text for text in result.stdout.splitlines() if text.startswith("RESULT:")][-1]
        outputs = json.loads(base64.b64decode(line[len("RESULT:"):]).decode("utf-8"))
        for (source, expected), actual in zip(self.CASES, outputs):
            with self.subTest(source=source):
                self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
