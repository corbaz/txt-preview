"""Static contract tests for reading the preview selection and replaying cached speech."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = (ROOT / "txt.ps1").read_text(encoding="utf-8")


def block(pattern: str) -> str:
    match = re.search(pattern, SCRIPT, re.DOTALL)
    if match is None:
        raise AssertionError(f"pattern not found: {pattern}")
    return match.group("body")


def function_body(name: str) -> str:
    return block(r"function " + re.escape(name) + r" \{(?P<body>.*?)\n\}")


class SelectionSpeechTests(unittest.TestCase):
    def test_preview_exposes_selection_text_and_start_word(self) -> None:
        self.assertIn("function getSpeechSelection()", SCRIPT)
        self.assertIn("function getSpeechSelectionStartWord()", SCRIPT)
        # IE11 engine: modern Selection API with the legacy document.selection fallback.
        self.assertIn("window.getSelection", SCRIPT)
        self.assertIn("document.selection.createRange().text", SCRIPT)

    def test_play_reads_selection_before_rerendering_the_preview(self) -> None:
        handler = block(r"\$btnLeer\.Add_Click\(\{(?P<body>.*?)\n\}\)")
        self.assertIn("Get-PreviewSpeechSelection", handler)
        # Re-rendering the preview would drop the selection, so the selection branch keeps it.
        self.assertLess(handler.index("Get-PreviewSpeechSelection"), handler.index("Open-MarkdownPreview"))
        self.assertIn("-SelectionStartWord", handler)

    def test_selection_is_only_read_from_the_preview_tab(self) -> None:
        body = function_body("Get-PreviewSpeechSelection")
        self.assertIn("$tabs.SelectedTab -ne $tabPreview", body)
        self.assertIn('InvokeScript("getSpeechSelection")', body)
        self.assertIn('InvokeScript("getSpeechSelectionStartWord")', body)

    def test_selection_highlight_starts_at_the_selected_word_or_is_disabled(self) -> None:
        body = function_body("Start-SelectedVoicePlayback")
        self.assertIn("[int]$SelectionStartWord = -1", body)
        self.assertIn("$speechState.SelectionOnly", body)
        self.assertIn("Reset-SpeechAlignment ($SelectionStartWord - 1)", body)
        highlight = function_body("Update-SpeechHighlight")
        # Without DOM alignment a ratio over the whole document would mark the wrong words.
        self.assertIn("$speechState.SelectionOnly", highlight)


if __name__ == "__main__":
    unittest.main()
