"""Static contract tests for the editable Vista previa synced back to its source."""

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


def js_function(name: str) -> str:
    return block(r"function " + re.escape(name) + r"\([^)]*\) \{(?P<body>.*?)\n\}")


class EditablePreviewTests(unittest.TestCase):
    def test_preview_body_is_editable_with_a_visible_caret(self) -> None:
        # The template's JS has its own column-0 braces, so slice up to the next function.
        html = block(r"function Get-MarkdownPreviewHtml \{(?P<body>.*?)\nfunction Show-MarkdownPreview")
        self.assertIn('<body contenteditable="true" spellcheck="false">', html)
        self.assertIn("caret-color: $foreground", html)

    def test_caret_starts_at_the_beginning_of_new_content(self) -> None:
        self.assertIn("function placePreviewCaretAtStart()", SCRIPT)
        completed = block(r"\$preview\.Add_DocumentCompleted\(\{(?P<body>.*?)\n\}\)")
        self.assertIn('InvokeScript("placePreviewCaretAtStart")', completed)
        self.assertIn("$preview.Focus()", completed)

    def test_empty_placeholder_is_replaced_when_typing(self) -> None:
        self.assertIn('<p class="preview-empty">', function_body("ConvertTo-PreviewBodyHtml"))
        self.assertIn("function dropPreviewPlaceholder()", SCRIPT)

    def test_links_open_with_ctrl_click(self) -> None:
        body = js_function("openPreviewLinkOnCtrlClick")
        self.assertIn("ctrlKey", body)
        self.assertIn("window.location.href", body)
        self.assertIn("Ctrl+clic para abrir el enlace", SCRIPT)


class SpeechWordsAfterEditTests(unittest.TestCase):
    def test_edits_mark_word_spans_stale_and_rebuild_lazily(self) -> None:
        check = js_function("checkPreviewEdit")
        self.assertIn("speechWordsStale = true", check)
        ensure = js_function("ensureSpeechWords")
        self.assertIn("unwrapSpeechWords()", ensure)
        self.assertIn("saveCaretOffsets()", ensure)
        self.assertIn("restoreCaretOffsets(", ensure)
        # Highlight updates never rebuild under the user's caret; the reading is stopped instead.
        self.assertIn("if (speechWordsStale) { return; }", js_function("setSpeechWordIndex"))

    def test_editing_during_a_reading_stops_it(self) -> None:
        body = function_body("Update-PreviewEditSync")
        self.assertIn("Stop-VoicePlayback", body)
        self.assertIn('InvokeScript("getPreviewEditState")', body)
        self.assertIn("Sync-PreviewEdits", body)


class SyncBackTests(unittest.TestCase):
    def test_markdown_conversion_covers_common_blocks(self) -> None:
        converter = js_function("mdBlocks")
        for tag in ('"PRE"', '"BLOCKQUOTE"', '"HR"', '"TABLE"', '"UL"', '"OL"'):
            self.assertIn(tag, converter)
        inline = js_function("mdInline")
        for tag in ('"STRONG"', '"EM"', '"CODE"', '"A"', '"IMG"', '"BR"'):
            self.assertIn(tag, inline)
        # A raw backtick would be an escape character inside the PowerShell here-string.
        self.assertIn("String.fromCharCode(96)", SCRIPT)
        self.assertIn("String.fromCharCode(0xFE0F, 0x20E3)", SCRIPT)

    def test_edits_go_to_the_answer_or_the_editor(self) -> None:
        body = function_body("Sync-PreviewEdits")
        self.assertIn('InvokeScript("takePreviewEdit")', body)
        self.assertIn("$script:aiResult = $markdown", body)
        self.assertIn("Set-EditorText $markdown", body)

    def test_every_consumer_sees_synced_content(self) -> None:
        self.assertIn("Sync-PreviewEdits", function_body("Get-PreviewContent"))
        tab_change = block(r"\$tabs\.Add_SelectedIndexChanged\(\{(?P<body>.*?)\n\}\)")
        self.assertIn("Sync-PreviewEdits", tab_change)
        self.assertIn("$button.Add_MouseDown({ [void](Sync-PreviewEdits) })", SCRIPT)
        self.assertIn("$previewSyncTimer.Add_Tick({ Update-PreviewEditSync })", SCRIPT)


if __name__ == "__main__":
    unittest.main()
