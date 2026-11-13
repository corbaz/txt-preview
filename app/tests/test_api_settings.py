"""Api settings wiring (T10/S2): startup migration + settings application,
masked key, update_models guard/bridge probing/status strings, model and key
persistence, and the stored-key-with-env-fallback order for ask_ai.

No network and no real DPAPI in these tests: crypto is injected, bridge
HTTP is mocked, and the TCP listening probe is stubbed.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from txt_core import models, settings


def fake_crypto_pair():
    def encrypt(data: bytes) -> bytes:
        return b"ENC:" + data

    def decrypt(data: bytes) -> bytes:
        assert data.startswith(b"ENC:")
        return data[len(b"ENC:"):]
    return encrypt, decrypt


class ApiSettingsTestCase(unittest.TestCase):
    """Api against a temp settings dir with injected crypto and no env key."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.settings_dir = self._tmp.name
        encrypt, decrypt = fake_crypto_pair()
        self.encrypt, self.decrypt = encrypt, decrypt
        self.api = main.Api(settings_dir=self.settings_dir,
                            legacy_dir=self._tmp.name + "-legacy",
                            api_encrypt=encrypt, api_decrypt=decrypt)
        self.api.engine = mock.Mock()
        self.api.engine.applied_speed = 100
        env_patcher = mock.patch.dict(os.environ, {}, clear=False)
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        os.environ.pop("GROQ_API_KEY", None)


class TestStartupWiring(ApiSettingsTestCase):
    def test_initialize_settings_applies_theme_speed_voice_and_model(self):
        settings.save_settings({"theme": "light", "speed": 150,
                                "speech_voice": "es-AR-TomasNeural",
                                "selected_model": "allam-2-7b"},
                               self.settings_dir)
        summary = self.api.initialize_settings()
        self.assertEqual(self.api.get_selected_model(), "allam-2-7b")
        self.assertEqual(summary["theme"], "light")
        self.assertEqual(summary["speed"], 150)
        self.assertEqual(summary["speech_voice"], "es-AR-TomasNeural")
        self.assertFalse(summary["migrated"])

    def test_initialize_settings_runs_legacy_migration(self):
        legacy = Path(self.settings_dir + "-legacy")
        legacy.mkdir(exist_ok=True)
        (legacy / "settings.json").write_text(
            json.dumps({"EncryptedApiKey": "gsk_legacy_key"}), encoding="utf-8")
        summary = self.api.initialize_settings()
        self.assertTrue(summary["migrated"])
        self.assertEqual(self.api.get_api_key_masked(), "gsk_..._key")


class TestApiKeyHandling(ApiSettingsTestCase):
    def test_set_api_key_persists_and_masks(self):
        result = self.api.set_api_key("gsk_abcdefgh1234")
        self.assertEqual(result["masked"], "gsk_...1234")
        self.assertEqual(
            settings.get_api_key(self.settings_dir, decrypt=self.decrypt),
            "gsk_abcdefgh1234")

    def test_get_api_key_masked_empty_when_no_key(self):
        self.assertEqual(self.api.get_api_key_masked(), "")

    def test_get_settings_reports_masked_key(self):
        self.api.set_api_key("gsk_abcdefgh1234")
        self.assertEqual(self.api.get_settings()["api_key_masked"], "gsk_...1234")


class TestUpdateModels(ApiSettingsTestCase):
    def test_guard_without_api_key(self):
        result = self.api.update_models()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "Ingresá una API key de Groq.")

    def test_guard_failure_is_not_cached(self):
        self.assertFalse(self.api.update_models()["ok"])
        self.api.set_api_key("gsk_guard_test")
        with mock.patch.object(models, "fetch_models",
                               return_value=list(models.DEFAULT_GROQ_MODELS)), \
                mock.patch.object(main, "_tcp_listening", return_value=False):
            result = self.api.update_models()
        self.assertTrue(result["ok"])

    def test_merges_groq_and_bridge_models_with_status(self):
        self.api.set_api_key("gsk_bridge_test")
        groq_model = models.ModelInfo("openai/gpt-oss-120b", "OpenAI", 131072)
        with mock.patch.object(models, "fetch_models", return_value=[groq_model]), \
                mock.patch.object(main, "_tcp_listening", return_value=True), \
                mock.patch.object(main.bridges, "bridge_http") as bridge_http:
            def fake_http(bridge, method, path, body, timeout, password):
                self.assertEqual(method, "GET")
                self.assertEqual(path, "/models")
                if bridge.key == "claude":
                    return 200, json.dumps([
                        {"id": "sonnet-4", "name": "Sonnet 4"},
                        {"id": "opus", "name": "Opus"},
                    ])
                if bridge.key == "codex":
                    return 200, json.dumps([{"id": "o3", "vision": True}])
                return 200, json.dumps([{"id": "pro", "vision": False}])
            bridge_http.side_effect = fake_http
            result = self.api.update_models()
        ids = [entry["id"] for entry in result["models"]]
        self.assertIn("openai/gpt-oss-120b", ids)
        self.assertIn("claude:sonnet-4", ids)
        self.assertIn("claude:opus", ids)
        self.assertIn("codex:o3", ids)
        self.assertIn("gemini:pro", ids)
        self.assertEqual(result["bridge_status"], {
            "claude": "Conectado (2 modelos)",
            "codex": "Conectado (1 modelo)",
            "gemini": "Conectado (1 modelo)",
        })
        vision = {entry["id"]: entry["vision"] for entry in result["models"]}
        self.assertTrue(vision["claude:sonnet-4"])
        self.assertTrue(vision["codex:o3"])
        self.assertFalse(vision["gemini:pro"])

    def test_result_is_cached_for_the_session(self):
        self.api.set_api_key("gsk_cache_test")
        with mock.patch.object(models, "fetch_models",
                               return_value=list(models.DEFAULT_GROQ_MODELS)), \
                mock.patch.object(main, "_tcp_listening", return_value=False):
            first = self.api.update_models()
        with mock.patch.object(models, "fetch_models") as fetch, \
                mock.patch.object(main, "_tcp_listening") as probe:
            second = self.api.update_models()
        self.assertEqual(first, second)
        fetch.assert_not_called()
        probe.assert_not_called()

    def _fresh_api(self):
        """update_models caches per session; status cases need a fresh one."""
        self.api.set_api_key("gsk_status_test")
        self.api._models_cache = None

    def _stub_bridge_password(self, password: str):
        # get_bridge_password also reads %LOCALAPPDATA%\prompting password
        # files; stub it so the test does not depend on this machine.
        return mock.patch.object(main.bridges, "get_bridge_password",
                                 return_value=password)

    def test_bridge_status_strings(self):
        self._fresh_api()
        with mock.patch.object(models, "fetch_models",
                               return_value=list(models.DEFAULT_GROQ_MODELS)), \
                mock.patch.object(main, "_tcp_listening", return_value=False):
            result = self.api.update_models()
            self.assertEqual(result["bridge_status"],
                             {"claude": "Apagado", "codex": "Apagado",
                              "gemini": "Apagado"})
        self._fresh_api()
        with self._stub_bridge_password(""), \
                mock.patch.object(models, "fetch_models",
                                  return_value=list(models.DEFAULT_GROQ_MODELS)), \
                mock.patch.object(main, "_tcp_listening", return_value=True), \
                mock.patch.object(main.bridges, "bridge_http",
                                  return_value=(401, "{}")):
            self.assertEqual(self.api.update_models()["bridge_status"],
                             {"claude": "Falta la contraseña",
                              "codex": "Falta la contraseña",
                              "gemini": "Falta la contraseña"})
        self._fresh_api()
        with self._stub_bridge_password(""), \
                mock.patch.object(models, "fetch_models",
                                  return_value=list(models.DEFAULT_GROQ_MODELS)), \
                mock.patch.object(main, "_tcp_listening", return_value=True), \
                mock.patch.object(main.bridges, "bridge_http",
                                  return_value=(403, "{}")):
            self.assertEqual(self.api.update_models()["bridge_status"],
                             {"claude": "Error HTTP 403",
                              "codex": "Error HTTP 403",
                              "gemini": "Error HTTP 403"})

    def test_wrong_password_reports_contraseña_incorrecta(self):
        self.api.set_api_key("gsk_wrongpw")
        with self._stub_bridge_password("wrong-password"), \
                mock.patch.object(models, "fetch_models",
                                  return_value=list(models.DEFAULT_GROQ_MODELS)), \
                mock.patch.object(main, "_tcp_listening", return_value=True), \
                mock.patch.object(main.bridges, "bridge_http",
                                  return_value=(401, "{}")):
            result = self.api.update_models()
        self.assertEqual(result["bridge_status"]["claude"],
                         "Contraseña incorrecta")

    def test_groq_fetch_error_falls_back_to_catalog_with_error(self):
        self.api.set_api_key("gsk_fallback")
        with mock.patch.object(models, "fetch_models",
                               side_effect=RuntimeError("Groq devolvió el estado HTTP 401.")), \
                mock.patch.object(main, "_tcp_listening", return_value=False):
            result = self.api.update_models()
        self.assertTrue(result["ok"])
        self.assertEqual(result["error"], "Groq devolvió el estado HTTP 401.")
        ids = [entry["id"] for entry in result["models"]]
        self.assertIn("openai/gpt-oss-120b", ids)


class TestS11CatalogCapabilities(ApiSettingsTestCase):
    """S11/T18: the catalog exposes the full capability dict for every item."""

    def test_groq_entries_carry_full_capabilities(self):
        self.api.set_api_key("gsk_caps_groq")
        groq_model = models.ModelInfo("openai/gpt-oss-120b", "OpenAI", 131072)
        with mock.patch.object(models, "fetch_models", return_value=[groq_model]), \
                mock.patch.object(main, "_tcp_listening", return_value=False):
            result = self.api.update_models()
        entry = next(e for e in result["models"] if e["id"] == "openai/gpt-oss-120b")
        caps = entry["capabilities"]
        self.assertEqual(
            (caps["chat"], caps["reasoning"], caps["web"], caps["vision"], caps["text_files"]),
            (True, True, True, False, True))
        self.assertEqual(caps["summary"], models.model_capabilities("openai/gpt-oss-120b").summary)

    def test_bridge_entries_carry_capabilities_with_live_vision(self):
        self.api.set_api_key("gsk_caps_bridge")
        with mock.patch.object(models, "fetch_models", return_value=[]), \
                mock.patch.object(main, "_tcp_listening", return_value=True), \
                mock.patch.object(main.bridges, "bridge_http") as bridge_http:
            def fake_http(bridge, method, path, body, timeout, password):
                if bridge.key == "claude":
                    return 200, json.dumps([{"id": "sonnet-4", "name": "Sonnet 4"}])
                return 200, json.dumps([])
            bridge_http.side_effect = fake_http
            result = self.api.update_models()
        caps = next(e for e in result["models"]
                    if e["id"] == "claude:sonnet-4")["capabilities"]
        self.assertTrue(caps["chat"])
        self.assertTrue(caps["text_files"])
        self.assertFalse(caps["web"])


class TestS11SelectedModelValidation(ApiSettingsTestCase):
    """S11/T18: non-chat and unknown Groq models are refused before any
    persistence or session change; known chat Groq and bridge ids pass."""

    def test_rejects_non_chat_groq_without_persistence_or_change(self):
        # load_settings merges defaults, so persistence is checked on the raw
        # settings file: a rejected selection writes nothing.
        raw_file = Path(settings._settings_file(self.settings_dir))
        result = self.api.set_selected_model("whisper-large-v3")
        self.assertFalse(result["ok"])
        self.assertEqual(self.api.get_selected_model(), "openai/gpt-oss-120b")
        self.assertFalse(raw_file.exists())

    def test_rejects_safeguard_non_chat(self):
        self.assertFalse(self.api.set_selected_model(
            "openai/gpt-oss-safeguard-20b")["ok"])

    def test_rejects_unknown_groq_id(self):
        result = self.api.set_selected_model("moonshotai/kimi-k2")
        self.assertFalse(result["ok"])
        self.assertEqual(self.api.get_selected_model(), "openai/gpt-oss-120b")

    def test_accepts_known_chat_groq_and_persists(self):
        result = self.api.set_selected_model("qwen/qwen3.8-27b")
        self.assertTrue(result["ok"])
        self.assertEqual(self.api.get_selected_model(), "qwen/qwen3.8-27b")
        self.assertEqual(
            settings.load_settings(self.settings_dir)["selected_model"],
            "qwen/qwen3.8-27b")

    def test_accepts_bridge_ids(self):
        result = self.api.set_selected_model("claude:sonnet-4")
        self.assertTrue(result["ok"])
        self.assertEqual(
            settings.load_settings(self.settings_dir)["selected_model"],
            "claude:sonnet-4")


class TestSelectedModelPersistence(ApiSettingsTestCase):
    def test_set_selected_model_persists_to_settings(self):
        self.api.set_selected_model("claude:sonnet-4")
        self.assertEqual(
            settings.load_settings(self.settings_dir)["selected_model"],
            "claude:sonnet-4")


class TestSpeechSpeedWiring(ApiSettingsTestCase):
    """Api.set_speech_speed: Edge sessions restart via engine.set_speed
    (legacy Restart-ActiveSpeechPlayback); Replay keeps restarting the same
    audio at the new tempo from the current position."""

    def test_edge_speed_change_calls_engine_set_speed(self):
        self.api.set_speech_speed(150)
        self.api.engine.set_speed.assert_called_once_with(150)
        self.assertEqual(self.api._speech_speed, 150)

    def test_speed_is_clamped_to_legacy_bounds(self):
        self.api.set_speech_speed(10)
        self.api.engine.set_speed.assert_called_once_with(50)
        self.api.engine.set_speed.reset_mock()
        self.api.set_speech_speed(500)
        self.api.engine.set_speed.assert_called_once_with(200)

    def test_replay_speed_change_restarts_at_current_position(self):
        self.api.engine.provider = "Replay"
        self.api.engine.mode = "Playing"
        with mock.patch.object(main.Api, "_replay_position", return_value=2.5):
            self.api.set_speech_speed(150)
        self.api.engine.set_speed.assert_not_called()
        self.api.engine.start_replay_playback.assert_called_once_with(2.5)
        self.api.engine.pause.assert_not_called()

    def test_replay_speed_change_while_paused_stays_paused(self):
        self.api.engine.provider = "Replay"
        self.api.engine.mode = "Paused"
        with mock.patch.object(main.Api, "_replay_position", return_value=1.0):
            self.api.set_speech_speed(150)
        self.api.engine.start_replay_playback.assert_called_once_with(1.0)
        self.api.engine.pause.assert_called_once_with()


class TestDictationAndClose(ApiSettingsTestCase):
    """Micrófono (T15/S8): legacy Win+H via keybd_event on Windows, a clear
    macOS instruction otherwise; Cerrar destroys the window. No real key
    events, dialogs or closing happen in tests."""

    def test_start_dictation_windows_sends_the_legacy_win_h_sequence(self):
        with mock.patch("sys.platform", "win32"), \
                mock.patch.object(main, "_press_win_h") as press:
            result = self.api.start_dictation()
        press.assert_called_once_with()
        self.assertTrue(result["ok"])
        self.assertEqual(result["message"],
                         "Dictado activado. Presioná Esc para detenerlo.")

    def test_start_dictation_windows_reports_failure(self):
        with mock.patch("sys.platform", "win32"), \
                mock.patch.object(main, "_press_win_h",
                                  side_effect=OSError("sin teclado")):
            result = self.api.start_dictation()
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"],
                         "No se pudo activar el dictado: sin teclado")

    def test_start_dictation_macos_shows_instruction_via_osascript(self):
        with mock.patch("sys.platform", "darwin"), \
                mock.patch.object(main.subprocess, "run") as run:
            result = self.api.start_dictation()
        self.assertEqual(run.call_args.args[0][0], "osascript")
        self.assertTrue(result["ok"])
        self.assertIn("dictado", result["message"])

    def test_start_dictation_macos_reports_osascript_failure(self):
        with mock.patch("sys.platform", "darwin"), \
                mock.patch.object(main.subprocess, "run",
                                  side_effect=OSError("sin osascript")):
            result = self.api.start_dictation()
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"],
                         "No se pudo activar el dictado: sin osascript")

    def test_start_dictation_other_platform_never_pretends_success(self):
        with mock.patch("sys.platform", "linux"):
            result = self.api.start_dictation()
        self.assertFalse(result["ok"])
        self.assertIn("no está disponible", result["message"])

    def test_close_app_destroys_the_window(self):
        window = mock.Mock()
        self.api._window = window
        result = self.api.close_app()
        window.destroy.assert_called_once_with()
        self.assertTrue(result["ok"])

    def test_close_app_without_window_refuses(self):
        try:
            del self.api._window
        except AttributeError:
            pass
        result = self.api.close_app()
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "La ventana no está disponible.")

    def test_close_app_swallows_destroy_errors(self):
        window = mock.Mock()
        window.destroy.side_effect = RuntimeError("boom")
        self.api._window = window
        result = self.api.close_app()
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"],
                         "No se pudo cerrar la ventana: boom")


class TestAskAiKeyOrder(ApiSettingsTestCase):
    def test_stored_settings_key_wins_over_env(self):
        self.api.set_api_key("gsk_stored_key")
        os.environ["GROQ_API_KEY"] = "gsk_env_key"
        captured = {}
        with mock.patch.object(main.groq, "post_chat",
                               side_effect=lambda key, body:
                               captured.setdefault("key", key) or {}):
            self.api.ask_ai("consult", False, "hola")
        self.assertEqual(captured["key"], "gsk_stored_key")

    def test_env_fallback_when_no_stored_key(self):
        os.environ["GROQ_API_KEY"] = "gsk_env_key"
        captured = {}
        with mock.patch.object(main.groq, "post_chat",
                               side_effect=lambda key, body:
                               captured.setdefault("key", key) or {}):
            self.api.ask_ai("consult", False, "hola")
        self.assertEqual(captured["key"], "gsk_env_key")

    def test_bridge_model_uses_stored_capabilities_vision(self):
        self.api.set_selected_model("claude:sonnet-4")
        self.api._bridge_model_vision["claude:sonnet-4"] = True
        caps = self.api._selected_capabilities()
        self.assertTrue(caps.vision)
        self.assertTrue(caps.text_files)
        self.assertFalse(caps.web)


if __name__ == "__main__":
    unittest.main()
