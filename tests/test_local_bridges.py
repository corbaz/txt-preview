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
            "$script:bridgePasswords = @{}; "
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
        self.assertEqual(results, ["Contraseña incorrecta o faltante|0"])

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

    def test_groq_requests_keep_the_openai_format(self) -> None:
        results = self.snippet(
            "$script:selectedGroqModel = 'openai/gpt-oss-120b'; $script:groqApiKey = 'gsk_test'; "
            "$json = New-GroqRequestJson 'hola' | ConvertFrom-Json; "
            "'RESULT=' + $json.model + ',' + $json.messages[0].content + ',' + (Get-GroqHeaders)['Authorization']"
        )
        self.assertEqual(results, ["openai/gpt-oss-120b,hola,Bearer gsk_test"])


if __name__ == "__main__":
    unittest.main()
