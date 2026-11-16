"""Behavior of the editor shortcut and the mark on the last used AI action."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def run_app_snippet(snippet: str) -> list[str]:
    command = (
        "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); "
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
class ClipboardPasteTests(unittest.TestCase):
    SET_IMAGE = (
        "$bitmap = New-Object Drawing.Bitmap 4, 4; $clipboardSet = $false; "
        "for ($attempt = 0; $attempt -lt 10 -and -not $clipboardSet; $attempt++) { "
        "try { [Windows.Forms.Clipboard]::SetImage($bitmap); $clipboardSet = $true } "
        "catch { Start-Sleep -Milliseconds 100 } }; "
        "if (-not $clipboardSet) { throw 'No se pudo preparar el portapapeles de prueba.' }; "
        "Start-Sleep -Milliseconds 150; "
    )

    def test_vision_model_attaches_a_clipboard_image(self) -> None:
        results = run_app_snippet(
            "$script:selectedGroqModel = 'qwen/qwen3.8-27b'; " + self.SET_IMAGE +
            "$textBox.Text = 'previo'; Invoke-ClipboardPaste; $bitmap.Dispose(); "
            "$image = $script:attachedFiles[0]; "
            "'RESULT=' + $script:attachedFiles.Count + ',' + $image.Kind + ',' + "
            "[IO.Path]::GetExtension($image.Path) + ',' + (Test-Path -LiteralPath $image.Path) + ',' + "
            "($image.Size -gt 0) + ',' + $textBox.Text; "
            "if ($image -and $image.Path) { Remove-Item -LiteralPath $image.Path }"
        )
        # The image becomes an attachment and the editor text is left alone.
        self.assertEqual(results[-1], "1,Image,.png,True,True,previo")

    def test_model_without_vision_rejects_a_clipboard_image(self) -> None:
        results = run_app_snippet(
            "$script:selectedGroqModel = 'openai/gpt-oss-120b'; " + self.SET_IMAGE +
            "$textBox.Text = 'previo'; Invoke-ClipboardPaste; $bitmap.Dispose(); "
            "'RESULT=' + $script:attachedFiles.Count + ',' + $textBox.Text"
        )
        self.assertEqual(results[-1], "0,previo")

    def test_clipboard_text_is_still_pasted_into_the_editor(self) -> None:
        results = run_app_snippet(
            "$script:selectedGroqModel = 'qwen/qwen3.8-27b'; "
            "$clipboardSet = $false; "
            "for ($attempt = 0; $attempt -lt 10 -and -not $clipboardSet; $attempt++) { "
            "try { [Windows.Forms.Clipboard]::SetText('hola portapapeles'); $clipboardSet = $true } "
            "catch { Start-Sleep -Milliseconds 100 } }; "
            "if (-not $clipboardSet) { throw 'No se pudo preparar el portapapeles de prueba.' }; "
            "Start-Sleep -Milliseconds 150; Invoke-ClipboardPaste; "
            "'RESULT=' + $script:attachedFiles.Count + ',' + $textBox.Text"
        )
        self.assertEqual(results[-1], "0,hola portapapeles")


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "needs Windows and PowerShell 7")
class LastAiActionMarkTests(unittest.TestCase):
    def test_only_the_clicked_ai_action_is_lit(self) -> None:
        results = run_app_snippet(
            "Set-Theme $true; "
            "$accent = (Get-ThemeColor 'Accent').ToArgb(); "
            "function Lit($b) { $b.BackColor.ToArgb() -eq $accent }; "
            "$script:lastAiButton = $null; Update-AiButtonTones; "
            "'RESULT=' + (Lit $btnPreguntar) + ',' + (Lit $btnResumir); "
            "Set-LastAiButton $btnResumir; "
            "'RESULT=' + (Lit $btnResumir) + ',' + (Lit $btnCorregir) + ',' + (Lit $btnPreguntar); "
            "Set-LastAiButton $btnCorregir; "
            "'RESULT=' + (Lit $btnResumir) + ',' + (Lit $btnCorregir); "
            "Set-Theme $false; $accent = (Get-ThemeColor 'Accent').ToArgb(); "
            "'RESULT=' + (Lit $btnCorregir)"
        )
        # Nothing is lit until a click (Consultar IA included); then only the clicked one,
        # and the mark survives a theme change.
        self.assertEqual(results, ["False,False", "True,False,False", "False,True", "True"])


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "needs Windows and PowerShell 7")
class AudioButtonFillTests(unittest.TestCase):
    def test_fill_shows_what_the_audio_is_doing(self) -> None:
        results = run_app_snippet(
            "Set-Theme $true; $idle = (Get-ThemeColor 'Elevated').ToArgb(); "
            "function Lit { (@($btnLeer, $btnPauseVoice, $btnStopVoice, $btnReplay) | "
            "ForEach-Object { $_.BackColor.ToArgb() -ne $idle }) -join ',' }; "
            "$speechState.Provider = 'Edge'; Set-AudioControlState 'Play'; 'RESULT=' + (Lit); "
            "Set-AudioControlState 'Pause'; 'RESULT=' + (Lit); "
            "Set-AudioControlState 'Stop'; 'RESULT=' + (Lit); "
            "$speechState.Provider = 'Replay'; Set-AudioControlState 'Play'; 'RESULT=' + (Lit); "
            "Set-AudioControlState 'Pause'; 'RESULT=' + (Lit); "
            "$speechState.Provider = $null; Set-AudioControlState 'Idle'; 'RESULT=' + (Lit)"
        )
        # Order: Play, Pausar/Continuar, Detener, Repetir.
        self.assertEqual(results, [
            "True,False,False,False",   # reading: Play
            "False,True,False,False",   # paused: Continuar
            "False,False,False,False",  # Detener lights nothing
            "True,False,False,True",    # repeating: Play + Repetir
            "False,True,False,True",    # repetition paused: Continuar + Repetir
            "False,False,False,False",
        ])


# The dictation tests never touch the real settings file.
DICTATION_SETTINGS = (
    "$settingsDirectory = Join-Path ([IO.Path]::GetTempPath()) ('txt-dictation-test-' + $PID); "
    "$settingsPath = Join-Path $settingsDirectory 'settings.json'; "
)
DICTATION_MODEL = ROOT / "models" / "nemotron-3.5-asr-streaming-0.6b-Q8_0.gguf"


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "needs Windows and PowerShell 7")
class DictationTests(unittest.TestCase):
    def test_listener_lines_write_into_the_editor_and_end_the_dictation(self) -> None:
        results = run_app_snippet(
            "$textBox.Text = 'Hola'; $textBox.SelectionStart = 4; "
            "$script:dictation.State = 'Loading'; Update-DictationButton; "
            "$ready = Receive-DictationLine 'ready'; "
            "'RESULT=' + $ready + ',' + $script:dictation.State + ',' + $btnMic.Text + ',' + $msgBox.Text; "
            "[void](Receive-DictationLine 'text 1  esto es'); [void](Receive-DictationLine 'text 1 .'); "
            "[void](Receive-DictationLine 'partial 2 y sig'); "
            "'RESULT=' + $textBox.Text + '|' + $msgBox.Text; "
            "$done = Receive-DictationLine 'done'; "
            "'RESULT=' + $done + ',' + $script:dictation.State + ',' + $btnMic.Text + ',' + $msgBox.Text"
        )
        self.assertEqual(results, [
            "False,Listening,Mic <Esc>,Dictando. Presioná Esc o Micrófono para detenerlo.",
            # The "." sticks to the last word; what is still a guess only shows as status.
            "Hola esto es.|Dictando: y sig",
            "True,Idle,Micrófono,Dictado detenido.",
        ])

    def test_first_piece_drops_its_space_at_the_start_and_after_a_space(self) -> None:
        results = run_app_snippet(
            "$textBox.Text = ''; Add-DictatedText ' Primera'; Add-DictatedText ' frase'; "
            "'RESULT=' + $textBox.Text; "
            "$textBox.Text = \"uno`r`n\"; $textBox.SelectionStart = $textBox.Text.Length; "
            "Add-DictatedText ' dos'; 'RESULT=' + ($textBox.Text -replace \"`r`n\", '/')"
        )
        self.assertEqual(results, ["Primera frase", "uno/dos"])

    def test_escape_stops_only_while_dictating(self) -> None:
        results = run_app_snippet(
            "$script:dictation.Control = Join-Path ([IO.Path]::GetTempPath()) ('txt-dictation-esc-' + $PID + '.txt'); "
            "$idle = Invoke-EditorShortcut ([Windows.Forms.Keys]::Escape); "
            "$script:dictation.State = 'Listening'; "
            "$busy = Invoke-EditorShortcut ([Windows.Forms.Keys]::Escape); "
            "'RESULT=' + $idle + ',' + $busy + ',' + $script:dictation.State + ',' + "
            "(Get-Content -LiteralPath $script:dictation.Control -Raw); "
            "Remove-Item -LiteralPath $script:dictation.Control"
        )
        self.assertEqual(results, ["False,True,Stopping,stop"])

    def test_listener_error_names_the_fix_and_frees_the_button(self) -> None:
        results = run_app_snippet(
            "$script:dictation.State = 'Loading'; Update-DictationButton; "
            "$ended = Receive-DictationLine 'error falta el modelo de dictado: ejecutá el instalador (install.ps1 o install.sh)'; "
            "'RESULT=' + $ended + ',' + $script:dictation.State + ',' + $btnMic.Text; 'RESULT=' + $msgBox.Text"
        )
        self.assertEqual(results, [
            "True,Idle,Micrófono",
            "No se pudo dictar: falta el modelo de dictado: ejecutá el instalador (install.ps1 o install.sh). "
            "El editor quedó listo para escribir.",
        ])

    def test_microphone_choice_is_listed_saved_and_kept_when_unplugged(self) -> None:
        results = run_app_snippet(
            DICTATION_SETTINGS +
            "[void][IO.Directory]::CreateDirectory($settingsDirectory); "
            "[IO.File]::WriteAllText($settingsPath, '{\"theme\":\"dark\",\"EncryptedApiKey\":\"abc\"}'); "
            "Update-MicrophoneList @('Mic A', 'Mic B'); "
            "'RESULT=' + ($micCombo.Items -join ';') + '|' + $micCombo.SelectedIndex; "
            "$micCombo.SelectedIndex = 2; "
            "$saved = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json; "
            "'RESULT=' + $saved.microphone + ',' + $saved.theme + ',' + $saved.EncryptedApiKey + '|' + $settingsStatus.Text; "
            "Update-MicrophoneList @('Mic A'); 'RESULT=' + ($micCombo.Items -join ';') + '|' + $micCombo.SelectedItem; "
            "$micCombo.SelectedIndex = 0; 'RESULT=[' + (Get-SavedMicrophone) + ']|' + $settingsStatus.Text; "
            "Remove-Item -LiteralPath $settingsDirectory -Recurse -Force"
        )
        self.assertEqual(results, [
            "Predeterminado del sistema;Mic A;Mic B|0",
            "Mic B,dark,abc|Micrófono para el dictado: Mic B.",
            "Predeterminado del sistema;Mic A;Mic B|Mic B",
            "[]|Micrófono para el dictado: predeterminado del sistema.",
        ])

    def test_settings_row_sits_above_the_models_list(self) -> None:
        results = run_app_snippet(
            "'RESULT=' + ($micCombo.Top -gt $txtApiKey.Bottom) + ',' + ($micCombo.Bottom -le $modelsList.Top)"
        )
        self.assertEqual(results, ["True,True"])

    @unittest.skipUnless(DICTATION_MODEL.exists(), "needs the dictation model (installer)")
    def test_real_listener_dictates_a_recording_into_the_editor(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            speech = os.path.join(folder, "speech.mp3")
            audio = os.path.join(folder, "speech.raw")
            subprocess.run([sys.executable, "-m", "edge_tts", "--voice", "es-AR-TomasNeural", "--text",
                            "Hola, esta es una prueba del dictado.", "--write-media", speech],
                           check=True, capture_output=True, timeout=60)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", speech, "-af", "apad=pad_dur=2",
                            "-f", "f32le", "-ac", "1", "-ar", "16000", audio], check=True, timeout=60)
            results = run_app_snippet(
                DICTATION_SETTINGS +
                f"$env:TXT_DICTATION_AUDIO = '{audio}'; $textBox.Text = ''; Start-Dictation; "
                "'RESULT=' + $script:dictation.State + ',' + $btnMic.Text; "
                "$limit = [DateTime]::UtcNow.AddSeconds(60); $asked = $false; "
                "while ($script:dictation.State -ne 'Idle' -and [DateTime]::UtcNow -lt $limit) { "
                "  Update-Dictation; "
                "  if (-not $asked -and $textBox.Text -match 'dictado') { Stop-Dictation; $asked = $true }; "
                "  Start-Sleep -Milliseconds 100 }; "
                "'RESULT=' + $script:dictation.State + ',' + $btnMic.Text + ',' + $msgBox.Text; "
                "'RESULT=' + $textBox.Text"
            )
        self.assertEqual(results[0], "Loading,Mic <Esc>")
        self.assertEqual(results[1], "Idle,Micrófono,Dictado detenido.")
        self.assertRegex(results[2].lower(), r"^hola.*prueba del dictado")


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

    def test_drop_downs_keep_the_height_of_their_row(self) -> None:
        results = run_app_snippet(
            "$modelCombo.CreateControl(); $voiceCombo.CreateControl(); "
            "'RESULT=' + $modelCombo.Height + ',' + $btnNavSettings.Height + ',' + $voiceCombo.Height + ',' + $modelCombo.ListItemHeight"
        )
        # The model selector lines up with the 26 px header buttons; list rows stay roomy.
        self.assertEqual(results[-1], "26,26,34,26")


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "needs Windows and PowerShell 7")
class AttachmentLinkTests(unittest.TestCase):
    def test_every_attached_file_name_is_a_link_to_its_attachment(self) -> None:
        results = run_app_snippet(
            "$script:attachedFiles.Add([pscustomobject]@{ Name = 'a.txt'; Kind = 'Text'; Content = 'x' }); "
            "$script:attachedFiles.Add([pscustomobject]@{ Name = 'informe final.pdf'; Kind = 'Pdf'; Content = 'y' }); "
            "Update-AttachmentSummary; "
            "'RESULT=' + $lblAttachments.Text; "
            "'RESULT=' + $lblAttachments.Links.Count; "
            "foreach ($link in $lblAttachments.Links) { "
            "'RESULT=' + $lblAttachments.Text.Substring($link.Start, $link.Length) + '|' + $link.LinkData.Name }; "
            "$script:attachedFiles.Clear(); Update-AttachmentSummary; "
            "'RESULT=' + $lblAttachments.Links.Count"
        )
        self.assertEqual(results, [
            "Se enviarán a Groq (2): a.txt, informe final.pdf",
            "2",
            "a.txt|a.txt",
            "informe final.pdf|informe final.pdf",
            "0",
        ])


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "needs Windows and PowerShell 7")
class CopyTeamsTests(unittest.TestCase):
    def test_teams_html_has_inline_styles_and_a_valid_clipboard_header(self) -> None:
        results = run_app_snippet(
            "$md = \"# Titulo`n`n| A | B |`n|---|---|`n| 1 | [link](https://example.com) |`n`nusa ``x```n\"; "
            "$html = Convert-MarkdownToTeamsHtml $md; "
            "'RESULT=' + ($html -match '<table style=\"border-collapse:collapse;margin:8px 0\"'); "
            "'RESULT=' + ($html -match '<th style=\"border:1px solid #8A8A8A;padding:6px 10px;text-align:left\"><span style=\"color:#7579EB\">A</span></th>'); "
            "'RESULT=' + ($html -match '<h1 style=\"font-size:22px;font-weight:600;margin:12px 0 6px\"[^>]*><span style=\"color:#7579EB\">Titulo</span></h1>'); "
            "'RESULT=' + ($html -match '<a style=\"text-decoration:underline\" href=\"https://example.com\"'); "
            "'RESULT=' + ($html -match '<code style=\"[^\"]*padding:1px 4px\">x</code>'); "
            "$payload = ConvertTo-ClipboardHtml '<p>año</p>'; "
            "$bytes = [Text.Encoding]::UTF8.GetBytes($payload); "
            "$null = $payload -match 'StartFragment:([0-9]+)'; $start = [int]$Matches[1]; "
            "$null = $payload -match 'EndFragment:([0-9]+)'; $end = [int]$Matches[1]; "
            "'RESULT=' + [Text.Encoding]::UTF8.GetString($bytes, $start, $end - $start); "
            "'RESULT=' + $btnCopyTeams.Text + '|' + ($btnCopyTeams.Left -gt $btnCopyTxt.Left) + '|' + ($btnMic.Left -gt $btnCopyTeams.Left)"
        )
        self.assertEqual(results, ["True", "True", "True", "True", "True", "<p>año</p>",
                                   "Copiar Teams|True|True"])


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "needs Windows and PowerShell 7")
class VersionLabelTests(unittest.TestCase):
    def test_version_uses_the_accent_color_in_both_themes(self) -> None:
        results = run_app_snippet(
            "Set-Theme $true; 'RESULT=' + ($versionLabel.ForeColor -eq (Get-ThemeColor 'Accent')) + '|' + $versionLabel.Font.Bold; "
            "Set-Theme $false; 'RESULT=' + ($versionLabel.ForeColor -eq (Get-ThemeColor 'Accent')) + '|' + ($lblAppVersion.ForeColor -eq (Get-ThemeColor 'Accent'))"
        )
        self.assertEqual(results, ["True|True", "True|True"])


class VolumeSliderTests(unittest.TestCase):
    def test_volume_goes_in_steps_of_ten_and_reaches_the_players(self) -> None:
        results = run_app_snippet(
            "'RESULT=' + $volumeSlider.Minimum + '|' + $volumeSlider.Maximum + '|' + $volumeSlider.Value + '|' + $lblVolumeValue.Text; "
            "$volumeSlider.Value = 47; 'RESULT=' + $volumeSlider.Value + '|' + $lblVolumeValue.Text; "
            "Set-SpeechVolume; 'RESULT=' + $speechState.Volume + '|' + ((Get-PlayerVolumeArguments) -join ' ') + '|' + $msgBox.Text; "
            "'RESULT=' + ($lblVolume.Left -gt $lblReplayTime.Left) + '|' + ($lblVolumeValue.Right -lt ($versionLabel.Right - [Windows.Forms.TextRenderer]::MeasureText($versionLabel.Text, $versionLabel.Font).Width))"
        )
        self.assertEqual(results[0], "0|100|100|100%")
        self.assertEqual(results[1], "50|50%")
        self.assertTrue(results[2].startswith("50|-volume 50|"), results[2])
        self.assertEqual(results[3], "True|True")


class PasteImageTests(unittest.TestCase):
    def test_a_model_without_vision_says_to_change_the_model(self) -> None:
        results = run_app_snippet("'RESULT=' + $pasteImageNeedsVisionMessage")
        self.assertIn("debés cambiar a un modelo con visión", results[0])
