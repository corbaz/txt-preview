"""edge-tts stays current: the installer always upgrades it and the app offers an update on a 403."""

from __future__ import annotations

import os
import shutil
import unittest
from pathlib import Path

from test_editor_actions import run_app_snippet

ROOT = Path(__file__).parents[1]
USER_ERROR = (
    "aiohttp.client_exceptions.WSServerHandshakeError: 403, message='Invalid response status', "
    "url='wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken=x'"
)

# Records every external process the app starts and answers like pip and python would.
FAKE_PROCESS = (
    "$script:calls = [Collections.Generic.List[string]]::new(); $script:pipExit = 0; $script:installed = '7.2.8'; "
    "function Invoke-ProcessWithEvents { param([string]$fileName, [string[]]$arguments) "
    "$script:calls.Add($arguments -join ' '); "
    "if ($arguments -contains 'pip') { if ($script:pipExit -eq 0) { $script:installed = '7.3.1' }; "
    "return [pscustomobject]@{ ExitCode = $script:pipExit; Error = 'ERROR: sin red'; Output = '' } }; "
    "return [pscustomobject]@{ ExitCode = 0; Error = ''; Output = $script:installed } }; "
    "$pythonCommand = 'python.exe'; "
)


class InstallerTests(unittest.TestCase):
    def test_installer_always_upgrades_edge_tts(self) -> None:
        script = (ROOT / "install.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('@("-m", "pip", "install", "--user", "--quiet", "--upgrade", "edge-tts")', script)
        # No "already installed" shortcut: the latest version is fetched every time.
        self.assertNotIn('"import edge_tts"', script)


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "needs Windows and PowerShell 7")
class VoiceUpdateTests(unittest.TestCase):
    def test_only_the_outdated_handshake_error_counts_as_outdated(self) -> None:
        results = run_app_snippet(
            f"'RESULT=' + (Test-EdgeTtsOutdatedError \"{USER_ERROR}\"); "
            "'RESULT=' + (Test-EdgeTtsOutdatedError 'No module named edge_tts'); "
            "'RESULT=' + (Test-EdgeTtsOutdatedError 'TimeoutError: 403 seconds')"
        )
        self.assertEqual(results, ["True", "False", "False"])

    def test_a_403_offers_the_voice_update_in_configuracion(self) -> None:
        results = run_app_snippet(
            FAKE_PROCESS + "Update-EdgeTtsVersionLabel; "
            "'RESULT=' + $script:voiceUpdateOffered + ',' + $lblEdgeTtsVersion.Text; "
            f"Show-EdgeVoiceError \"{USER_ERROR}\"; "
            "'RESULT=' + $script:voiceUpdateOffered + ',' + $tabSettings.Controls.Contains($btnUpdateVoices) + ',' + $msgBox.Text"
        )
        self.assertEqual(results, [
            "False,Voces Edge: edge-tts v7.2.8",
            "True,True,Las voces Edge necesitan una versión nueva de edge-tts. "
            "Tocá «Actualizar voces» en Configuración.",
        ])

    def test_other_voice_errors_keep_their_message_and_offer_nothing(self) -> None:
        results = run_app_snippet(
            FAKE_PROCESS + "Show-EdgeVoiceError 'Edge no generó el bloque de audio.'; "
            "'RESULT=' + $script:voiceUpdateOffered + ',' + $msgBox.Text"
        )
        self.assertEqual(results, ["False,No se pudo generar la voz Edge: Edge no generó el bloque de audio."])

    def test_update_button_upgrades_edge_tts_and_shows_the_new_version(self) -> None:
        results = run_app_snippet(
            FAKE_PROCESS + f"Show-EdgeVoiceError \"{USER_ERROR}\"; Update-EdgeTts; "
            "'RESULT=' + ($script:calls -match 'pip') + '|' + $lblEdgeTtsVersion.Text + '|' + "
            "$script:voiceUpdateOffered + '|' + $msgBox.Text"
        )
        self.assertEqual(results, [
            "-m pip install --user --quiet --upgrade edge-tts|Voces Edge: edge-tts v7.3.1|False|"
            "Voces Edge actualizadas: edge-tts v7.3.1."
        ])

    def test_failed_update_keeps_the_offer_and_says_why(self) -> None:
        results = run_app_snippet(
            FAKE_PROCESS + f"$script:pipExit = 1; Show-EdgeVoiceError \"{USER_ERROR}\"; Update-EdgeTts; "
            "'RESULT=' + $lblEdgeTtsVersion.Text + '|' + $script:voiceUpdateOffered + '|' + $msgBox.Text"
        )
        self.assertEqual(results, [
            "Voces Edge: edge-tts v7.2.8|True|No se pudieron actualizar las voces Edge: ERROR: sin red"
        ])

    def test_version_label_without_python_or_package(self) -> None:
        results = run_app_snippet(
            "$pythonCommand = $null; Update-EdgeTtsVersionLabel; 'RESULT=' + $lblEdgeTtsVersion.Text; "
            + FAKE_PROCESS + "$script:installed = ''; Update-EdgeTtsVersionLabel; 'RESULT=' + $lblEdgeTtsVersion.Text"
        )
        self.assertEqual(results, ["Voces Edge: sin Python", "Voces Edge: edge-tts no instalado"])


if __name__ == "__main__":
    unittest.main()
