"""Behavior of the editor shortcut and the mark on the last used AI action."""

from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def run_app_snippet(snippet: str) -> list[str]:
    command = (
        "$env:TXT_PREVIEW_TEST_MODE = '1'; "
        f". '{ROOT / 'txt.ps1'}'; "
        f"{snippet}"
    )
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-STA", "-Command", command],
        capture_output=True, timeout=120, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return [line[len("RESULT="):] for line in result.stdout.splitlines() if line.startswith("RESULT=")]


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "needs Windows and PowerShell 7")
class EditorShortcutTests(unittest.TestCase):
    def test_ctrl_enter_asks_the_ai_and_enter_stays_a_new_line(self) -> None:
        results = run_app_snippet(
            "$script:asked = 0; function Invoke-PrimaryAiAction { $script:asked++ }; "
            "$ctrlEnter = Invoke-EditorShortcut ([Windows.Forms.Keys]::Control -bor [Windows.Forms.Keys]::Return); "
            "$enter = Invoke-EditorShortcut ([Windows.Forms.Keys]::Return); "
            "$shiftEnter = Invoke-EditorShortcut ([Windows.Forms.Keys]::Shift -bor [Windows.Forms.Keys]::Return); "
            "'RESULT=' + $ctrlEnter + ',' + $enter + ',' + $shiftEnter + ',' + $script:asked"
        )
        self.assertEqual(results[-1], "True,False,False,1")


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "needs Windows and PowerShell 7")
class LastAiActionMarkTests(unittest.TestCase):
    def test_only_the_last_used_ai_action_is_marked(self) -> None:
        results = run_app_snippet(
            "Set-Theme $true; "
            "$accent = (Get-ThemeColor 'Accent').ToArgb(); "
            "function Marked($b) { $b.FlatAppearance.BorderColor.ToArgb() -eq $accent -and $b.ForeColor.ToArgb() -eq $accent }; "
            "Set-LastAiButton $btnResumir; "
            "'RESULT=' + (Marked $btnResumir) + ',' + (Marked $btnCorregir) + ',' + ($btnPreguntar.BackColor.ToArgb() -eq $accent); "
            "Set-LastAiButton $btnCorregir; "
            "'RESULT=' + (Marked $btnResumir) + ',' + (Marked $btnCorregir); "
            "Set-Theme $false; $accent = (Get-ThemeColor 'Accent').ToArgb(); "
            "'RESULT=' + (Marked $btnCorregir)"
        )
        # Resumir is marked while Consultar IA keeps its primary fill; the mark then moves
        # to Corregir and survives a theme change.
        self.assertEqual(results, ["True,False,True", "False,True", "True"])


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "needs Windows and PowerShell 7")
class ModernControlsTests(unittest.TestCase):
    def test_slider_clamps_raises_value_changed_and_keeps_trackbar_api(self) -> None:
        results = run_app_snippet(
            "$s = New-Object ModernSlider; $s.Minimum = 50; $s.Maximum = 200; $s.Value = 100; "
            "$script:changes = 0; $s.Add_ValueChanged({ $script:changes++ }); "
            "$s.Value = 999; $high = $s.Value; $s.Value = -5; $low = $s.Value; "
            "$s.Value = 100; $s.Maximum = 80; $shrunk = $s.Value; "
            "'RESULT=' + $high + ',' + $low + ',' + $shrunk + ',' + $script:changes + ',' + "
            "($speedSlider -is [ModernSlider]) + ',' + ($replaySlider -is [ModernSlider]) + ',' + ($modelsList -is [ModernListView])"
        )
        self.assertEqual(results[-1], "200,50,80,4,True,True,True")


if __name__ == "__main__":
    unittest.main()
