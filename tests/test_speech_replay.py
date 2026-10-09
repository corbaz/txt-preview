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


class SpeechReplayTests(unittest.TestCase):
    def test_replay_controls_exist_in_the_speed_row(self) -> None:
        self.assertIn('$btnReplay.Text = "Repetir"', SCRIPT)
        self.assertIn("$replaySlider = New-Object Windows.Forms.TrackBar", SCRIPT)
        self.assertIn("$panel.Controls.Add($btnReplay)", SCRIPT)
        self.assertIn("$panel.Controls.Add($replaySlider)", SCRIPT)
        self.assertIn("$panel.Controls.Add($lblReplayTime)", SCRIPT)

    def test_replay_is_disabled_without_cached_audio(self) -> None:
        body = function_body("Update-ReplayControls")
        self.assertIn("$speechState.ReplayFile", body)
        self.assertIn("$btnReplay.Enabled", body)
        self.assertIn("$replaySlider.Enabled", body)

    def test_full_generations_are_cached_for_both_providers(self) -> None:
        save = function_body("Save-SpeechReplayCache")
        self.assertIn("$speechState.CacheEligible", save)
        # Edge chunks are raw MP3 frames, so concatenating them yields one playable file.
        self.assertIn("ReadAllBytes", save)
        windows = function_body("Start-WindowsSpeechSession")
        self.assertIn("SetOutputToWaveFile", windows)
        stop = function_body("Stop-VoicePlayback")
        self.assertIn("Save-SpeechReplayCache", stop)
        self.assertLess(stop.index("Save-SpeechReplayCache"), stop.index("Remove-SpeechChunkFiles"))

    def test_played_edge_chunks_are_kept_until_the_session_ends(self) -> None:
        update = function_body("Update-EdgeVoicePlayback")
        self.assertNotIn("Remove-Item -LiteralPath $completedChunk.MediaFile", update)

    def test_replay_plays_cached_file_with_ffplay_seek(self) -> None:
        body = function_body("Start-ReplayPlayback")
        self.assertIn('"-ss"', body)
        self.assertIn("$speechState.ReplayFile", body)
        self.assertIn('$speechState.Provider = "Replay"', body)
        self.assertNotIn("Start-EdgeChunkGeneration", body)
        self.assertNotIn("SpeakAsync", body)

    def test_replay_button_and_slider_are_wired(self) -> None:
        self.assertIn("$btnReplay.Add_Click(", SCRIPT)
        self.assertIn("$replaySlider.Add_MouseUp(", SCRIPT)
        tick = block(r"\$edgeVoiceTimer\.Add_Tick\(\{(?P<body>.*?)\n\}\)")
        self.assertIn("Update-ReplayPlayback", tick)

    def test_voice_or_speed_changes_do_not_resynthesize_a_replay(self) -> None:
        body = function_body("Restart-ActiveSpeechPlayback")
        self.assertIn('$speechState.Provider -eq "Replay"', body)

    def test_cached_audio_is_removed_on_close(self) -> None:
        closed = block(r"\$form\.Add_FormClosed\(\{(?P<body>.*?)\n\}\)")
        self.assertIn("Clear-SpeechReplayCache", closed)


if __name__ == "__main__":
    unittest.main()
