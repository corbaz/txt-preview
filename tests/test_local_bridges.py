"""Local subscription bridges (Claude, Codex, Gemini) as AI providers next to Groq."""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from test_editor_actions import run_app_snippet


class FakeBridge(BaseHTTPRequestHandler):
    """Speaks the bridge contract: Basic auth, GET /models and POST /chat."""

    user = "claude"
    password = "secreto"
    models = [{"id": "sonnet", "name": "Claude Sonnet"}]
    reply: dict = {"text": "respuesta del bridge", "isError": False}
    received: list = []

    def log_message(self, *args) -> None:
        pass

    def _authorized(self) -> bool:
        expected = "Basic " + base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
        return self.headers.get("Authorization") == expected

    def _send(self, status: int, payload) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if not self._authorized():
            self._send(401, {"error": "No autorizado."})
        elif self.path == "/models":
            self._send(200, self.models)
        else:
            self._send(404, {"error": "No encontrado."})

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if not self._authorized():
            self._send(401, {"error": "No autorizado."})
            return
        FakeBridge.received.append(json.loads(body))
        if isinstance(self.reply, str):
            data = self.reply.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._send(200, self.reply)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "needs Windows and PowerShell 7")
class LocalBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeBridge.received = []
        FakeBridge.reply = {"text": "respuesta del bridge", "isError": False}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeBridge)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.data_dir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.data_dir, ignore_errors=True)

    def snippet(self, body: str, password: str = "secreto") -> list[str]:
        # Claude points at the fake bridge; Codex and Gemini point at closed ports.
        return run_app_snippet(
            f"$env:LOCALAPPDATA = '{self.data_dir}'; "
            f"$env:CLAUDE_BRIDGE_PASSWORD = '{password}'; "
            "$env:CODEX_BRIDGE_PASSWORD = ''; $env:GEMINI_BRIDGE_PASSWORD = ''; "
            # Startup loaded the real settings.json; forget its bridge passwords.
            "$script:bridgePasswords = @{}; foreach ($box in $bridgePasswordBoxes.Values) { $box.Text = '' }; "
            f"(Get-LocalBridge 'claude:x').Port = {self.port}; "
            f"(Get-LocalBridge 'codex:x').Port = {free_port()}; "
            f"(Get-LocalBridge 'gemini:x').Port = {free_port()}; "
            "Update-BridgeModels; " + body
        )

    def test_running_bridge_lists_its_models_in_the_grouped_selector(self) -> None:
        results = self.snippet(
            "'RESULT=' + (@($script:bridgeModels | ForEach-Object { $_.id }) -join '|'); "
            "'RESULT=' + ($modelCombo.Items -contains 'Claude · Claude Sonnet'); "
            "'RESULT=' + ($modelCombo.Items -contains 'Groq · openai/gpt-oss-120b')"
        )
        self.assertEqual(results, ["claude:sonnet", "True", "True"])

    def test_configuration_shows_each_bridge_status(self) -> None:
        results = self.snippet(
            "foreach ($key in 'claude', 'codex', 'gemini') { 'RESULT=' + $script:bridgeStatus[$key] }"
        )
        self.assertEqual(results, ["Conectado (1 modelo)", "Apagado", "Apagado"])

    def test_wrong_password_is_reported_and_adds_no_models(self) -> None:
        results = self.snippet(
            "'RESULT=' + $script:bridgeStatus['claude'] + '|' + @($script:bridgeModels).Count",
            password="otra",
        )
        self.assertEqual(results, ["Contraseña incorrecta|0"])

    def test_missing_password_is_reported_apart_from_a_wrong_one(self) -> None:
        results = self.snippet("'RESULT=' + $script:bridgeStatus['claude']", password="")
        self.assertEqual(results, ["Falta la contraseña"])

    def test_saving_a_new_password_rechecks_the_bridges(self) -> None:
        settings = Path(self.data_dir, "settings.json")
        results = self.snippet(
            f"$settingsDirectory = '{self.data_dir}'; $settingsPath = '{settings}'; "
            "'RESULT=' + $script:bridgeStatus['claude'] + ',' + ($modelCombo.Items -contains 'Claude · Claude Sonnet'); "
            "$bridgePasswordBoxes['claude'].Text = 'secreto'; Invoke-SaveSettings; "
            "'RESULT=' + $script:bridgeStatus['claude'] + ',' + ($modelCombo.Items -contains 'Claude · Claude Sonnet') + ',' + $settingsStatus.Text",
            password="",
        )
        self.assertEqual(results, [
            "Falta la contraseña,False",
            "Conectado (1 modelo),True,Configuración guardada de forma segura para este usuario de Windows. "
            "Bridges: Claude Conectado (1 modelo) · Codex Apagado · Gemini Apagado",
        ])

    def test_leaving_a_changed_password_box_rechecks_the_bridges(self) -> None:
        results = self.snippet(
            "$box = $bridgePasswordBoxes['claude']; $script:rechecks = 0; "
            "function Update-BridgeModels { $script:rechecks++ }; "
            "$leave = [Windows.Forms.Control].GetMethod('OnLeave', [Reflection.BindingFlags]'NonPublic,Instance'); "
            "$leave.Invoke($box, @([EventArgs]::Empty)); "
            "$box.Text = 'secreto'; $leave.Invoke($box, @([EventArgs]::Empty)); "
            "$leave.Invoke($box, @([EventArgs]::Empty)); "
            "'RESULT=' + $script:rechecks + ',' + $script:bridgePasswords['claude']",
            password="",
        )
        # Only the first leave after an edit rechecks; leaving untouched boxes costs nothing.
        self.assertEqual(results, ["1,secreto"])

    def test_password_precedence_environment_then_settings_then_file(self) -> None:
        bridge_dir = Path(self.data_dir, "prompting", "claude-bridge")
        bridge_dir.mkdir(parents=True)
        (bridge_dir / "password.txt").write_text("del-archivo\n", encoding="utf-8")
        results = self.snippet(
            "$bridge = Get-LocalBridge 'claude:x'; "
            "'RESULT=' + (Get-BridgePassword $bridge); "
            "$env:CLAUDE_BRIDGE_PASSWORD = ''; $script:bridgePasswords['claude'] = 'de-config'; "
            "'RESULT=' + (Get-BridgePassword $bridge); "
            "$script:bridgePasswords = @{}; "
            "'RESULT=' + (Get-BridgePassword $bridge)",
            password="del-entorno",
        )
        self.assertEqual(results, ["del-entorno", "de-config", "del-archivo"])

    def test_actions_send_the_prompt_attachments_and_images_to_the_bridge(self) -> None:
        image = Path(self.data_dir, "foto.png")
        image.write_bytes(b"\x89PNG fake")
        results = self.snippet(
            "$script:selectedGroqModel = 'claude:sonnet'; "
            "$script:attachedFiles.Add([pscustomobject]@{ Name = 'notas.txt'; Kind = 'Text'; Content = 'dato adjunto' }); "
            f"$script:attachedFiles.Add([pscustomobject]@{{ Name = 'foto.png'; Path = '{image}'; Kind = 'Image'; Size = 9 }}); "
            "$response = Invoke-GroqRequest -Headers (Get-GroqHeaders) -Body (New-GroqRequestJson 'Resumí esto'); "
            "'RESULT=' + (Get-AiResponseText $response)"
        )
        self.assertEqual(results, ["respuesta del bridge"])
        sent = FakeBridge.received[-1]
        self.assertEqual(sent["model"], "sonnet")
        self.assertIn("Resumí esto", sent["message"])
        self.assertIn("dato adjunto", sent["message"])
        self.assertEqual(sent["images"], [{"mimeType": "image/png", "data": base64.b64encode(b"\x89PNG fake").decode()}])

    def test_bridge_error_is_raised_with_its_message(self) -> None:
        FakeBridge.reply = {"text": "", "isError": True, "error": "límite de uso alcanzado"}
        results = self.snippet(
            "$script:selectedGroqModel = 'claude:sonnet'; "
            "try { Get-AiResponseText (Invoke-GroqRequest -Headers (Get-GroqHeaders) -Body (New-GroqRequestJson 'hola')) } "
            "catch { 'RESULT=' + $_.Exception.Message }"
        )
        self.assertEqual(results, ["Claude: límite de uso alcanzado"])

    def test_stopped_bridge_and_invalid_answer_are_reported_by_name(self) -> None:
        FakeBridge.reply = "<html>no es json</html>"
        results = self.snippet(
            "$script:selectedGroqModel = 'gemini:pro'; "
            "try { Invoke-GroqRequest -Headers @{} -Body '{}' } catch { 'RESULT=' + $_.Exception.Message }; "
            "$script:selectedGroqModel = 'claude:sonnet'; "
            "try { Get-AiResponseText (Invoke-GroqRequest -Headers @{} -Body '{}') } catch { 'RESULT=' + $_.Exception.Message }",
        )
        self.assertRegex(results[0], r"^Gemini: el bridge no responde en 127\.0\.0\.1:\d+\.$")
        self.assertEqual(results[1], "Claude: el bridge devolvió una respuesta que no es JSON.")

    def test_bridge_capabilities_follow_the_provider(self) -> None:
        FakeBridge.models = [{"id": "sonnet", "name": "Claude Sonnet"}]
        results = self.snippet(
            "$script:bridgeModels.Add([pscustomobject]@{ id = 'codex:gpt-v'; Vision = $true }); "
            "$script:bridgeModels.Add([pscustomobject]@{ id = 'codex:gpt-t'; Vision = $false }); "
            "$script:bridgeModels.Add([pscustomobject]@{ id = 'gemini:pro'; Vision = $false }); "
            "foreach ($id in 'claude:sonnet', 'codex:gpt-v', 'codex:gpt-t', 'gemini:pro') { "
            "$c = Get-GroqModelCapabilities $id; 'RESULT=' + $c.Chat + ',' + $c.Vision + ',' + $c.Web + ',' + $c.TextFiles }"
        )
        self.assertEqual(results, [
            "True,True,False,True", "True,True,False,True", "True,False,False,True", "True,False,False,True",
        ])

    def test_configuration_tab_shows_the_status_next_to_each_bridge(self) -> None:
        results = self.snippet(
            "foreach ($key in 'claude', 'codex', 'gemini') { "
            "'RESULT=' + $tabSettings.Controls.Contains($bridgeStatusLabels[$key]) + ',' + $bridgeStatusLabels[$key].Text + ',' + "
            "$bridgePasswordBoxes[$key].UseSystemPasswordChar }"
        )
        self.assertEqual(results, ["True,Conectado (1 modelo),True", "True,Apagado,True", "True,Apagado,True"])

    def test_bridge_passwords_are_saved_encrypted_without_a_groq_key(self) -> None:
        settings = Path(self.data_dir, "settings.json")
        results = self.snippet(
            f"$settingsDirectory = '{self.data_dir}'; $settingsPath = '{settings}'; "
            "$txtApiKey.Text = ''; $bridgePasswordBoxes['codex'].Text = 'clave-codex'; "
            "Save-AppSettings; $script:bridgePasswords = @{}; $bridgePasswordBoxes['codex'].Text = ''; "
            "Import-AppSettings; "
            "'RESULT=' + $script:bridgePasswords['codex'] + ',' + $bridgePasswordBoxes['codex'].Text"
        )
        self.assertEqual(results[-1], "clave-codex,clave-codex")
        saved = settings.read_text(encoding="utf-8")
        self.assertNotIn("clave-codex", saved)
        self.assertIn("codex", json.loads(saved)["EncryptedBridgePasswords"])

    def test_saving_with_nothing_configured_still_asks_for_a_key(self) -> None:
        settings = Path(self.data_dir, "settings.json")
        results = self.snippet(
            f"$settingsDirectory = '{self.data_dir}'; $settingsPath = '{settings}'; $txtApiKey.Text = ''; "
            "try { Save-AppSettings; 'RESULT=saved' } catch { 'RESULT=' + $_.Exception.Message }"
        )
        self.assertEqual(results[-1], "Ingresá una API key de Groq o la contraseña de un bridge.")
        self.assertFalse(settings.exists())

    def test_attachment_notice_names_the_selected_provider(self) -> None:
        results = self.snippet(
            "$script:attachedFiles.Add([pscustomobject]@{ Name = 'a.txt'; Kind = 'Text'; Content = 'x' }); "
            "$script:selectedGroqModel = 'claude:sonnet'; Update-AttachmentSummary; 'RESULT=' + $lblAttachments.Text; "
            "$script:selectedGroqModel = 'openai/gpt-oss-120b'; Update-AttachmentSummary; 'RESULT=' + $lblAttachments.Text"
        )
        self.assertEqual(results, ["Se enviarán a Claude (1): a.txt", "Se enviarán a Groq (1): a.txt"])

    def test_models_list_fits_the_settings_tab_so_it_scrolls(self) -> None:
        results = self.snippet(
            "foreach ($size in @([Drawing.Size]::new(1880, 730), [Drawing.Size]::new(1200, 500))) { "
            "$tabSettings.Size = $size; $page = $tabSettings.ClientSize.Height; "
            "'RESULT=' + ($modelsList.Bottom -le $settingsStatus.Top) + ',' + ($settingsStatus.Bottom -le $page) + ',' + "
            "($modelsList.Height -gt 100) + ',' + ($modelsList.Right -le $tabSettings.ClientSize.Width) }"
        )
        self.assertEqual(results, ["True,True,True,True", "True,True,True,True"])

    def test_models_list_shows_each_capability_in_its_own_column(self) -> None:
        results = self.snippet(
            "'RESULT=' + (@($modelsList.Columns | ForEach-Object { $_.Text }) -join '|'); "
            "foreach ($id in 'claude:sonnet', 'openai/gpt-oss-120b', 'whisper-large-v3') { "
            "$row = @($modelsList.Items | Where-Object { $_.Tag -eq $id })[0]; "
            "'RESULT=' + (@($row.SubItems | Select-Object -First 7 | ForEach-Object { $_.Text }) -join '|') }"
        )
        self.assertEqual(results, [
            "Modelo|Proveedor|Contexto|Chat|Visión|Web|Adjuntos|Funciones",
            "Claude Sonnet|Claude (suscripción)|-|✓|✓|—|✓",
            "openai/gpt-oss-120b|OpenAI|131.072|✓|—|✓|✓",
            "whisper-large-v3|OpenAI|448|—|—|—|—",
        ])

    def test_busy_message_names_the_provider_and_model(self) -> None:
        results = self.snippet(
            "$script:selectedGroqModel = 'claude:sonnet'; 'RESULT=' + (Get-SelectedModelDisplay); "
            "$script:selectedGroqModel = 'openai/gpt-oss-120b'; 'RESULT=' + (Get-SelectedModelDisplay)"
        )
        self.assertEqual(results, ["Claude · Claude Sonnet", "Groq · openai/gpt-oss-120b"])
        script = Path(__file__).parents[1].joinpath("txt.ps1").read_text(encoding="utf-8-sig")
        for message in ("Traduciendo con IA", "Corrigiendo gramática y ortografía", "Consultando a la IA", "Creando resumen profesional"):
            self.assertIn(f'Start-Busy "{message} · $(Get-SelectedModelDisplay)..."', script)

    def test_test_mode_startup_never_probes_the_real_bridges(self) -> None:
        # The snippet helper probes the fake bridge on purpose, so this one runs bare.
        results = run_app_snippet("'RESULT=' + $script:bridgeStatus.Count + ',' + $script:bridgeModels.Count")
        self.assertEqual(results, ["0,0"])

    def test_groq_requests_keep_the_openai_format(self) -> None:
        results = self.snippet(
            "$script:selectedGroqModel = 'openai/gpt-oss-120b'; $script:groqApiKey = 'gsk_test'; "
            "$json = New-GroqRequestJson 'hola' | ConvertFrom-Json; "
            "'RESULT=' + $json.model + ',' + $json.messages[0].content + ',' + (Get-GroqHeaders)['Authorization']"
        )
        self.assertEqual(results, ["openai/gpt-oss-120b,hola,Bearer gsk_test"])


if __name__ == "__main__":
    unittest.main()
