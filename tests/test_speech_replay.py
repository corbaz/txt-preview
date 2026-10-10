"""Static contract tests for reading the preview selection and replaying cached speech."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
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
        self.assertIn("$replaySlider = New-Object ModernSlider", SCRIPT)
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


class TrackingHighlightTests(unittest.TestCase):
    def test_tracking_highlight_is_bubblegum_pink_in_both_themes(self) -> None:
        self.assertEqual(SCRIPT.count('SpeechBackground = "#FF69B4"'), 2)
        self.assertEqual(SCRIPT.count('SpeechForeground = "#2B0016"'), 2)
        self.assertIn(".speech-active::selection", SCRIPT)

    def test_selection_is_cleared_once_captured(self) -> None:
        self.assertIn("function clearSpeechSelection()", SCRIPT)
        body = function_body("Get-PreviewSpeechSelection")
        # The native selection paints over the tracking highlight, so it is dropped after capture.
        self.assertIn('InvokeScript("clearSpeechSelection")', body)

    def test_tracked_word_is_kept_near_the_top(self) -> None:
        scroll = block(r"function keepSpeechWordInView\(element\) \{(?P<body>.*?)\n\}")
        self.assertIn("viewHeight * 0.2", scroll)
        self.assertIn("viewHeight * 0.5", scroll)


class ClickPositionTests(unittest.TestCase):
    def test_preview_records_plain_clicks_not_drags(self) -> None:
        self.assertIn("function findSpeechWordAtPoint(x, y)", SCRIPT)
        self.assertIn("function takeSpeechClick()", SCRIPT)
        self.assertIn("function getSpeechTextFrom(wordIndex)", SCRIPT)
        handler = block(r"function recordSpeechClick\(event\) \{(?P<body>.*?)\n\}")
        # A drag that leaves a selection is not a caret click.
        self.assertIn("isCollapsed", handler)
        self.assertIn("speechClickMoveLimit", handler)

    def test_play_starts_from_the_clicked_word(self) -> None:
        handler = block(r"\$btnLeer\.Add_Click\(\{(?P<body>.*?)\n\}\)")
        self.assertIn("Get-PreviewSpeechClick", handler)
        self.assertIn("Get-PreviewSpeechTextFrom", handler)
        self.assertLess(handler.index("Get-PreviewSpeechClick"), handler.index("Open-MarkdownPreview"))

    def test_clicks_while_reading_jump_voice_and_highlight(self) -> None:
        tick = block(r"\$edgeVoiceTimer\.Add_Tick\(\{(?P<body>.*?)\n\}\)")
        self.assertIn("Get-PreviewSpeechClick", tick)
        self.assertIn("Move-SpeechToWord", tick)
        body = function_body("Move-SpeechToWord")
        self.assertIn("Stop-VoicePlayback -KeepHighlight", body)
        self.assertIn("Reset-SpeechAlignment ($wordIndex - 1)", body)
        self.assertIn("Start-SelectedVoicePlayback $text -ContinueHighlight", body)
        # Replays have no word marks, so clicks do not move them.
        self.assertIn('$speechState.Provider -eq "Replay"', body)

    def test_jumped_readings_never_replace_the_cache(self) -> None:
        body = function_body("Start-SelectedVoicePlayback")
        self.assertIn("$speechState.CacheEligible = -not $ContinueHighlight", body)


class ReplayHighlightTests(unittest.TestCase):
    def test_aligner_core_is_shared_by_live_reading_and_cache(self) -> None:
        self.assertIn("function Get-NextAlignmentCursor {", SCRIPT)
        self.assertIn("Get-NextAlignmentCursor", function_body("Step-SpeechAlignment"))
        self.assertIn("Get-NextAlignmentCursor", function_body("Get-ReplayWordTimings"))

    def test_reading_records_its_preview_words_and_start(self) -> None:
        self.assertIn("$speechState.AlignWordsKey", function_body("Initialize-SpeechAlignment"))
        self.assertIn("$speechState.CacheStartCursor", function_body("Start-SelectedVoicePlayback"))

    def test_timings_are_cached_for_both_providers(self) -> None:
        save = function_body("Save-SpeechReplayCache")
        self.assertIn("Get-ReplayWordTimings", save)
        self.assertIn("$speechState.AlignWordsKey", save)
        # Edge marks are offset by the duration of the chunks joined before them.
        self.assertIn("$chunkOffset + $mark.StartSeconds", save)
        self.assertIn("$chunkOffset += $chunk.DurationSeconds", save)
        windows = function_body("Start-WindowsSpeechSession")
        # Render events can arrive on worker threads, so a compiled collector records them.
        self.assertIn("[SpeechRenderTrack]::new($renderSynth)", windows)
        self.assertIn("seconds.Add(e.AudioPosition.TotalSeconds)", SCRIPT)
        self.assertNotIn("$renderSynth.add_SpeakProgress", SCRIPT)
        # SAPI reports AudioPosition on a 16 kHz clock; other WAV rates skew the word times.
        self.assertIn("SpeechAudioFormatInfo]::new(16000", windows)
        # Timings that run past the audio are dropped rather than marking the wrong words.
        self.assertIn("$markSeconds[$markSeconds.Count - 1] -gt $duration", save)

    def test_replay_highlight_follows_position_and_seeks(self) -> None:
        self.assertIn("Update-ReplayHighlight", function_body("Update-ReplayPlayback"))
        start = function_body("Start-ReplayPlayback")
        self.assertIn("$speechState.ReplayHighlightChecked = $false", start)
        self.assertIn("Update-ReplayHighlight $offset", start)
        self.assertIn("Update-ReplayHighlight", block(r"\$replaySlider\.Add_ValueChanged\(\{(?P<body>.*?)\n\}\)"))

    def test_replay_highlight_is_disabled_when_the_preview_changed(self) -> None:
        body = function_body("Update-ReplayHighlight")
        self.assertIn("$speechState.ReplayWordsKey", body)
        self.assertIn("Clear-PreviewSpeechProgress", body)
        completed = block(r"\$preview\.Add_DocumentCompleted\(\{(?P<body>.*?)\n\}\)")
        self.assertIn("$speechState.ReplayHighlightChecked = $false", completed)

    def test_clicks_still_do_not_move_a_replay(self) -> None:
        self.assertIn('$speechState.Provider -eq "Replay"', function_body("Move-SpeechToWord"))


class ReplayClickLeakTests(unittest.TestCase):
    def test_clicks_during_repetir_are_discarded(self) -> None:
        self.assertIn('InvokeScript("takeSpeechClick")', function_body("Clear-PreviewSpeechClick"))
        tick = block(r"\$edgeVoiceTimer\.Add_Tick\(\{(?P<body>.*?)\n\}\)")
        self.assertIn('if ($speechState.Provider -eq "Replay") {\n        Clear-PreviewSpeechClick', tick)

    def test_replay_start_and_stop_drop_pending_clicks(self) -> None:
        start = function_body("Start-ReplayPlayback")
        self.assertLess(start.index("Stop-VoicePlayback"), start.index("Clear-PreviewSpeechClick"))
        stop = function_body("Stop-VoicePlayback")
        self.assertIn('$wasReplay = $speechState.Provider -eq "Replay"', stop)
        self.assertIn("if ($wasReplay) {\n        Clear-PreviewSpeechClick", stop)

    def test_play_ignores_a_click_made_during_repetir(self) -> None:
        handler = block(r"\$btnLeer\.Add_Click\(\{(?P<body>.*?)\n\}\)")
        self.assertLess(handler.index("Clear-PreviewSpeechClick"), handler.index("Get-PreviewSpeechClick"))


class ReplayCacheOwnershipTests(unittest.TestCase):
    def test_a_different_preview_deletes_the_cache(self) -> None:
        body = function_body("Update-ReplayCacheForPreview")
        self.assertIn("Get-ReplayCacheDecision", body)
        # A replay of the old text is stopped before its file is removed.
        self.assertLess(body.index("Stop-VoicePlayback"), body.index("Clear-SpeechReplayCache"))
        completed = block(r"\$preview\.Add_DocumentCompleted\(\{(?P<body>.*?)\n\}\)")
        self.assertIn("Update-ReplayCacheForPreview", completed)
        # A cache saved after the preview already changed is checked right away too.
        self.assertIn("Update-ReplayCacheForPreview", function_body("Save-SpeechReplayCache"))

    def test_every_cache_records_its_preview(self) -> None:
        save = function_body("Save-SpeechReplayCache")
        self.assertIn("$speechState.ReplayWordsKey = $wordsKey", save)
        # The key is stored for every cache, not only for caches that carry word timings.
        self.assertNotIn("$speechState.ReplayWordsKey = $wordsKey\n        }", save)


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "needs Windows and PowerShell 7")
class ReplayCacheDecisionBehaviorTests(unittest.TestCase):
    def test_decision_for_same_changed_unknown_and_unkeyed_previews(self) -> None:
        command = (
            "$env:TXT_PREVIEW_TEST_MODE = '1'; "
            f". '{ROOT / 'txt.ps1'}'; "
            "$key = Get-SpeechWordsKey \"Hola`nmundo\"; "
            "@("
            "(Get-ReplayCacheDecision $key \"Hola`nmundo\"), "
            "(Get-ReplayCacheDecision $key \"Otro`ntexto\"), "
            "(Get-ReplayCacheDecision $key ''), "
            "(Get-ReplayCacheDecision $null \"Hola`nmundo\")"
            ") -join ','"
        )
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-STA", "-Command", command],
            capture_output=True, timeout=120, encoding="utf-8", errors="replace",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # Same text keeps; other text deletes; a page still loading decides nothing;
        # a cache that never learned its preview cannot be trusted.
        self.assertEqual(result.stdout.strip().splitlines()[-1], "Keep,Delete,Unknown,Delete")


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "needs Windows and PowerShell 7")
class ReplaySpeedBehaviorTests(unittest.TestCase):
    """Repetir plays audio rendered at one speed; the slider must still set how fast it sounds."""

    def run_snippet(self, snippet: str) -> str:
        command = f"$env:TXT_PREVIEW_TEST_MODE = '1'; . '{ROOT / 'txt.ps1'}'; {snippet}"
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-STA", "-Command", command],
            capture_output=True, timeout=120, encoding="utf-8", errors="replace",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout.strip().splitlines()[-1]

    def test_tempo_is_the_current_speed_over_the_rendered_speed(self) -> None:
        output = self.run_snippet(
            "$speechState.ReplaySpeed = 100; $speedSlider.Value = 150; $a = Get-ReplayTempo; "
            "$speechState.ReplaySpeed = 150; $speedSlider.Value = 75; $b = Get-ReplayTempo; "
            "'' + $a + ',' + $b"
        )
        self.assertEqual(output, "1.5,0.5")

    def test_atempo_chain_stays_inside_the_filter_range(self) -> None:
        output = self.run_snippet(
            "@((Get-AtempoFilter 1.0), (Get-AtempoFilter 1.5), (Get-AtempoFilter 3.0), (Get-AtempoFilter 0.25)) -join '|'"
        )
        # 1.0 needs no filter; each atempo stage must stay between 0.5 and 2.
        self.assertEqual(output, "|atempo=1.5|atempo=2,atempo=1.5|atempo=0.5,atempo=0.5")

    def test_position_advances_at_the_replay_tempo(self) -> None:
        output = self.run_snippet(
            "$speechState.ReplayDuration = 60; $speechState.ReplayOffset = 10; $speechState.ReplayTempo = 2.0; "
            "$speechState.PlayerProcess = [Diagnostics.Process]::GetCurrentProcess(); "
            "$now = [DateTime]::UtcNow; $speechState.PlayerStartedAt = $now.AddSeconds(-3); $speechState.PauseStartedAt = $now; "
            "[Math]::Round((Get-ReplayPositionSeconds), 2)"
        )
        self.assertEqual(output, "16")

    def test_changing_speed_during_repetir_continues_from_the_same_point(self) -> None:
        output = self.run_snippet(
            "$script:restartedAt = $null; function Start-ReplayPlayback { param($offsetSeconds) $script:restartedAt = $offsetSeconds }; "
            "function Get-ReplayPositionSeconds { 12.5 }; "
            "$speechState.Provider = 'Replay'; $speechState.Mode = 'Playing'; "
            "$speedSlider.Value = 150; Set-SpeechSpeed; $afterSpeed = $script:restartedAt; "
            "$script:restartedAt = $null; Restart-ActiveSpeechPlayback 'Voz cambiada'; "
            "'' + $afterSpeed + ',' + ($null -eq $script:restartedAt)"
        )
        # A new voice cannot apply to audio that already exists, so only speed restarts Repetir.
        self.assertEqual(output, "12.5,True")


if __name__ == "__main__":
    unittest.main()
