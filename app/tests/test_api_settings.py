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
    def test_every_launch_starts_on_the_legacy_defaults(self):
        settings.save_settings({"theme": "light", "speed": 150,
                                "speech_voice": "es-AR-TomasNeural",
                                "selected_model": "allam-2-7b"},
                               self.settings_dir)
        summary = self.api.initialize_settings()
        # txt.ps1 parity: the saved model is ignored on purpose; every launch
        # starts on openai/gpt-oss-120b.
        self.assertEqual(self.api.get_selected_model(), "openai/gpt-oss-120b")
        self.assertEqual(summary["selected_model"], "openai/gpt-oss-120b")
        # txt.ps1 never reads theme, speed or voice back either.
        self.assertEqual(summary["theme"], "dark")
        self.assertEqual(summary["speed"], 100)
        self.assertEqual(summary["speech_voice"], "es-CR-JuanNeural")
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
    def test_without_api_key_lists_static_catalog_and_probes_bridges(self):
        """txt.ps1 parity: a subscription bridge alone is a valid setup, so
        no Groq key still lists the static catalog and checks the bridges."""
        with mock.patch.object(models, "fetch_models") as fetch, \
                mock.patch.object(main, "_tcp_listening", return_value=False):
            result = self.api.update_models()
        fetch.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertNotIn("error", result)
        self.assertEqual([m["id"] for m in result["models"]],
                         sorted(m.id for m in models.DEFAULT_GROQ_MODELS))
        self.assertEqual(result["bridge_status"],
                         {"claude": "Apagado", "codex": "Apagado", "gemini": "Apagado"})

    def test_saving_a_key_drops_the_cached_catalog(self):
        with mock.patch.object(main, "_tcp_listening", return_value=False):
            self.api.update_models()
        self.api.set_api_key("gsk_guard_test")
        only = [models.ModelInfo("openai/gpt-oss-120b", "OpenAI", 131072)]
        with mock.patch.object(models, "fetch_models", return_value=only), \
                mock.patch.object(main, "_tcp_listening", return_value=False):
            result = self.api.update_models()
        self.assertEqual([m["id"] for m in result["models"]], ["openai/gpt-oss-120b"])

    def test_catalog_rows_carry_the_legacy_list_columns(self):
        self.api.set_api_key("gsk_rows")
        only = [models.ModelInfo("openai/gpt-oss-120b", "OpenAI", 131072)]
        with mock.patch.object(models, "fetch_models", return_value=only), \
                mock.patch.object(main, "_tcp_listening", return_value=False):
            row = self.api.update_models()["models"][0]
        self.assertEqual(row["owned_by"], "OpenAI")
        self.assertEqual(row["context"], "131.072")
        self.assertEqual(
            row["capabilities"]["summary"],
            "Texto · Razonamiento · Búsqueda web · Documentos (texto, PDF, Word, PowerPoint)")


class TestSettingsForm(ApiSettingsTestCase):
    """Configuración buttons, with the txt.ps1 messages."""

    OFF = "Bridges: Claude Apagado · Codex Apagado · Gemini Apagado"

    def test_save_requires_a_key_or_a_bridge_password(self):
        result = self.api.save_settings_form("  ", {"claude": " "})
        self.assertEqual(result, {
            "ok": False, "level": "error", "message":
            "No se pudo guardar: Ingresá una API key de Groq o la contraseña de un bridge."})

    def test_save_persists_key_and_bridge_passwords_and_rechecks_bridges(self):
        with mock.patch.object(main, "_tcp_listening", return_value=False), \
                mock.patch.object(main.sys, "platform", "win32"):
            result = self.api.save_settings_form(" gsk_saved ", {"claude": " pw1 ", "codex": ""})
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["message"],
            "Configuración guardada de forma segura para este usuario de Windows. " + self.OFF)
        self.assertEqual(settings.get_api_key(self.settings_dir, decrypt=self.decrypt),
                         "gsk_saved")
        self.assertEqual(
            settings.get_bridge_passwords(["claude", "codex", "gemini"],
                                          self.settings_dir, decrypt=self.decrypt),
            {"claude": "pw1"})
        self.assertEqual(self.api.get_settings_secrets(), {
            "api_key": "gsk_saved",
            "bridge_passwords": {"claude": "pw1", "codex": "", "gemini": ""}})

    def test_bridge_password_alone_can_be_saved(self):
        with mock.patch.object(main, "_tcp_listening", return_value=False):
            result = self.api.save_settings_form("", {"gemini": "pw"})
        self.assertTrue(result["ok"])

    def test_saved_bridge_passwords_are_loaded_at_startup(self):
        settings.set_bridge_passwords({"codex": "pw2"}, self.settings_dir, encrypt=self.encrypt)
        self.api.initialize_settings()
        self.assertEqual(self.api._bridge_passwords.get("codex"), "pw2")

    def test_refresh_models_reports_the_count_and_saves_the_key(self):
        listed = [models.ModelInfo("b-model", "B", 10), models.ModelInfo("a-model", "A", 20)]
        with mock.patch.object(models, "fetch_models", return_value=listed) as fetch, \
                mock.patch.object(main, "_tcp_listening", return_value=False):
            result = self.api.refresh_models("gsk_box", {})
        fetch.assert_called_once_with("gsk_box")
        self.assertEqual(result["level"], "info")
        self.assertEqual(result["message"],
                         "2 modelos activos cargados desde Groq. " + self.OFF)
        self.assertEqual([m["id"] for m in result["models"]], ["a-model", "b-model"])
        self.assertEqual(settings.get_api_key(self.settings_dir, decrypt=self.decrypt),
                         "gsk_box")

    def test_refresh_models_failure_still_probes_bridges(self):
        with mock.patch.object(main, "_tcp_listening", return_value=False):
            result = self.api.refresh_models("", {})
        self.assertTrue(result["ok"])
        self.assertEqual(result["level"], "warning")
        self.assertEqual(
            result["message"],
            "No se pudieron actualizar los modelos de Groq: Ingresá una API key de Groq. "
            + self.OFF)
        self.assertEqual(settings.get_api_key(self.settings_dir, decrypt=self.decrypt), "")

    def test_recheck_bridges_uses_the_typed_passwords(self):
        seen = []

        def fake_http(bridge, method, path, body, timeout, password):
            seen.append((bridge.key, password))
            return 200, "[]"

        with mock.patch.object(main, "_tcp_listening", return_value=True), \
                mock.patch.object(main.bridges, "bridge_http", side_effect=fake_http), \
                mock.patch.dict("os.environ", {}, clear=False), \
                mock.patch.object(main.bridges, "bridge_password_file",
                                  return_value=self.settings_dir + "/none.txt"):
            for name in ("CLAUDE_BRIDGE_PASSWORD", "CODEX_BRIDGE_PASSWORD",
                         "GEMINI_BRIDGE_PASSWORD"):
                main.os.environ.pop(name, None)
            result = self.api.recheck_bridges({"claude": "typed"})
        self.assertIn(("claude", "typed"), seen)
        self.assertEqual(result["bridge_status"]["claude"], "Conectado (0 modelos)")

    def test_edge_tts_version_label(self):
        self.api.engine.python_command = "python"
        ok = mock.Mock(returncode=0, stdout="7.3.1\n")
        self.assertEqual(self.api.edge_tts_version_label(runner=lambda *a, **k: ok),
                         "Voces Edge: edge-tts v7.3.1")
        missing = mock.Mock(returncode=1, stdout="")
        self.assertEqual(self.api.edge_tts_version_label(runner=lambda *a, **k: missing),
                         "Voces Edge: edge-tts no instalado")
        self.api.engine.python_command = None
        self.assertEqual(self.api.edge_tts_version_label(), "Voces Edge: sin Python")


class TestUpdateModelsBridges(ApiSettingsTestCase):
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

    def test_tls_failure_falls_back_to_catalog_without_traceback(self):
        """S17/T24: an end-to-end TLS failure on /models (Mac incident) must
        return ok with the static catalog plus the controlled error — never an
        uncaught URLError traceback through pywebview."""
        import ssl
        import urllib.error
        self.api.set_api_key("gsk_tls")
        reason = ssl.SSLCertVerificationError(
            20, "Basic Constraints of CA cert not marked critical")
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError(reason)), \
                mock.patch.object(main, "_tcp_listening", return_value=False):
            result = self.api.update_models()
        self.assertTrue(result["ok"])
        self.assertIn("No se pudo conectar con Groq", result["error"])
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

    def test_safeguard_web_capability_never_enables_chat(self):
        """T25/S18: the safeguard model is a safety classifier with browser
        search, never an ordinary chat model; the ask_ai chat gate stays
        authoritative for it."""
        caps = models.model_capabilities("openai/gpt-oss-safeguard-20b")
        self.assertFalse(caps.chat)
        self.assertFalse(caps.text_files)

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
    """Micrófono: the Api hands the dictation to txt_core.dictation with the
    chosen language and microphone; Cerrar destroys the window. No real
    listener, microphone or closing happen in tests."""

    def setUp(self):
        super().setUp()
        self.api._dictation = mock.Mock()

    def test_start_dictation_uses_the_language_and_the_saved_microphone(self):
        self.api._dictation.start.return_value = {"ok": True, "state": "loading"}
        self.api.set_microphone("JBL Tune 520BT")
        self.assertEqual(self.api.start_dictation("en"), {"ok": True, "state": "loading"})
        self.api._dictation.start.assert_called_once_with("en", "JBL Tune 520BT")

    def test_start_dictation_defaults_to_spanish_and_the_system_microphone(self):
        self.api.start_dictation()
        self.api._dictation.start.assert_called_once_with("es", "")

    def test_stop_and_tick_go_to_the_dictation(self):
        self.api._dictation.stop.return_value = {"ok": True, "state": "stopping"}
        self.api._dictation.poll.return_value = {"state": "listening", "text": " hola"}
        self.assertEqual(self.api.stop_dictation()["state"], "stopping")
        self.assertEqual(self.api.dictation_tick()["text"], " hola")

    def test_microphone_choice_is_saved_and_listed(self):
        with mock.patch.object(main.dictation, "list_microphones",
                               return_value=["Micrófono (G432)", "JBL Tune 520BT"]):
            self.assertEqual(self.api.list_microphones()["selected"], "")
            result = self.api.set_microphone("JBL Tune 520BT")
            listed = self.api.list_microphones()
        self.assertEqual(result["message"], "Micrófono para el dictado: JBL Tune 520BT.")
        self.assertEqual(listed, {"microphones": ["Micrófono (G432)", "JBL Tune 520BT"],
                                  "selected": "JBL Tune 520BT"})
        self.assertEqual(self.api.set_microphone("")["message"],
                         "Micrófono para el dictado: predeterminado del sistema.")
        self.assertEqual(main.settings.get_microphone(self.api._settings_dir), "")

    def test_close_app_releases_the_microphone(self):
        self.api._window = mock.Mock()
        self.api.close_app()
        self.api._dictation.close.assert_called_once_with()

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

    def test_ask_ai_refuses_safeguard_before_the_network(self):
        """T25/S18: even with a web checkbox, a safeguard selection fails at the
        capability gate — never as a chat request and never a network call."""
        self.api._selected_model = "openai/gpt-oss-safeguard-20b"
        with mock.patch("urllib.request.urlopen") as urlopen:
            result = self.api.ask_ai("consult", True, "hola")
        self.assertFalse(result["ok"])
        self.assertEqual(
            result["error"],
            "El modelo elegido no admite chat de texto. Elegí otro modelo para las acciones de IA.",
        )
        urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class TestEdgeTtsUpdateOffer(ApiSettingsTestCase):
    """txt.ps1 Show-EdgeVoiceError / Update-EdgeTts."""

    def setUp(self):
        super().setUp()
        # A real engine: the speech state is part of what these tests read.
        self.api = main.Api(settings_dir=self.settings_dir)

    OUTDATED = "aiohttp.client_exceptions.WSServerHandshakeError: 403, message='Invalid response status'"

    def test_outdated_edge_tts_error_offers_the_update(self):
        self.assertFalse(self.api._speech_state()["voice_update_offered"])
        self.api._on_engine_message("error", self.OUTDATED)
        state = self.api._speech_state()
        self.assertTrue(state["voice_update_offered"])
        self.assertEqual(
            state["message"],
            "Las voces Edge necesitan una versión nueva de edge-tts. "
            "Tocá «Actualizar voces» en Configuración.")

    def test_other_errors_do_not_offer_the_update(self):
        self.api._on_engine_message("error", "No se encontró ffplay (error 4035).")
        state = self.api._speech_state()
        self.assertFalse(state["voice_update_offered"])
        self.assertEqual(state["message"], "No se encontró ffplay (error 4035).")

    def test_update_runs_pip_upgrade_and_withdraws_the_offer(self):
        self.api.engine.python_command = "python"
        self.api._voice_update_offered = True
        calls = []

        def runner(argv, **kwargs):
            calls.append(argv)
            return mock.Mock(returncode=0, stdout="7.3.1\n", stderr="")

        result = self.api.update_edge_tts(runner=runner)
        self.assertEqual(calls[0], ["python", "-m", "pip", "install", "--user",
                                    "--quiet", "--upgrade", "edge-tts"])
        self.assertEqual(result, {"ok": True, "label": "Voces Edge: edge-tts v7.3.1",
                                  "message": "Voces Edge actualizadas: edge-tts v7.3.1."})
        self.assertFalse(self.api._speech_state()["voice_update_offered"])

    def test_failed_update_reports_the_last_pip_line_and_keeps_the_offer(self):
        self.api.engine.python_command = "python"
        self.api._voice_update_offered = True

        def runner(argv, **kwargs):
            if "pip" in argv:
                return mock.Mock(returncode=1, stdout="", stderr="x\nERROR: sin red\n")
            return mock.Mock(returncode=0, stdout="7.2.8\n", stderr="")

        result = self.api.update_edge_tts(runner=runner)
        self.assertEqual(result["ok"], False)
        self.assertEqual(result["message"],
                         "No se pudieron actualizar las voces Edge: ERROR: sin red")
        self.assertTrue(self.api._speech_state()["voice_update_offered"])


class TestPreviewContent(ApiSettingsTestCase):
    def test_empty_preview_shows_the_legacy_placeholder(self):
        html = self.api.render_preview("  ")
        self.assertIn("No hay contenido para mostrar.", html)
        self.assertEqual(self.api.get_preview_text(), "  ")

    def test_exports_follow_the_content_handed_by_the_ui(self):
        self.api.set_preview_content("# Respuesta")
        self.assertEqual(self.api.get_preview_text(), "# Respuesta")
        self.assertEqual(self.api.get_preview_plain_text(), "Respuesta")


class TestModelChangeDropsImages(ApiSettingsTestCase):
    def test_images_are_removed_when_the_new_model_has_no_vision(self):
        from txt_core.attachments import Attachment, Kind
        self.api._selected_model = "qwen/qwen3.8-27b"  # vision model
        self.api._attachments = [Attachment(Kind.IMAGE, "foto.png", "/x/foto.png"),
                                 Attachment(Kind.TEXT, "nota.txt", "/x/nota.txt", "hola")]
        self.api.set_selected_model("openai/gpt-oss-120b")  # no vision
        self.assertEqual([a.name for a in self.api._attachments], ["nota.txt"])

    def test_images_stay_on_a_vision_model(self):
        from txt_core.attachments import Attachment, Kind
        self.api._attachments = [Attachment(Kind.IMAGE, "foto.png", "/x/foto.png")]
        self.api.set_selected_model("qwen/qwen3.8-27b")
        self.assertEqual([a.name for a in self.api._attachments], ["foto.png"])


class TestSpeechMessagesAreDeliveredOnce(ApiSettingsTestCase):
    def setUp(self):
        super().setUp()
        self.api = main.Api(settings_dir=self.settings_dir)

    def test_state_poll_does_not_repeat_a_message(self):
        self.api._on_engine_message("info", "Reproduciendo bloque 1 de 2 · Juan")
        self.assertEqual(self.api._speech_state()["message"],
                         "Reproduciendo bloque 1 de 2 · Juan")
        self.assertEqual(self.api._speech_state()["message"], "")

    def test_stop_reports_lectura_detenida_and_drops_the_playing_message(self):
        self.api._on_engine_message("info", "Reproduciendo bloque 1 de 2 · Juan")
        self.assertEqual(self.api.stop_speech(),
                         {"ok": True, "message": "Lectura detenida."})
        self.assertEqual(self.api._speech_state()["message"], "")


class TestAttachmentLinksAndPreview(ApiSettingsTestCase):
    def _attach(self):
        from txt_core.attachments import Attachment, Kind
        image = Path(self.settings_dir) / "foto.png"
        image.write_bytes(b"PNGDATA")
        self.api._attachments = [
            Attachment(Kind.TEXT, "nota.txt", "/x/nota.txt", "hola\nmundo"),
            Attachment(Kind.IMAGE, "foto.png", str(image)),
        ]

    def test_get_attachments_lists_names_for_the_links(self):
        self.assertEqual(self.api.get_attachments(), {
            "summary": "Sin archivos adjuntos para la próxima solicitud", "items": []})
        self._attach()
        self.assertEqual(self.api.get_attachments(), {
            "summary": "Se enviarán a Groq (2): nota.txt, foto.png",
            "items": [{"name": "nota.txt", "kind": "text"},
                      {"name": "foto.png", "kind": "image"}]})

    def test_preview_of_a_document_is_the_text_that_will_be_sent(self):
        self._attach()
        self.assertEqual(self.api.get_attachment_preview(0), {
            "ok": True, "name": "nota.txt", "kind": "text", "text": "hola\nmundo"})

    def test_preview_of_an_image_is_a_data_url(self):
        self._attach()
        preview = self.api.get_attachment_preview(1)
        self.assertEqual(preview["kind"], "image")
        self.assertEqual(preview["data_url"], "data:image/png;base64,UE5HREFUQQ==")

    def test_preview_of_a_missing_attachment_is_refused(self):
        self.assertEqual(self.api.get_attachment_preview(3), {
            "ok": False, "message": "El adjunto ya no está en la lista."})

    def test_dialog_offers_images_only_to_vision_models(self):
        calls = []
        window = mock.Mock()
        window.create_file_dialog.side_effect = lambda *a, **k: calls.append(k) or None
        self.api._window = window
        self.api._selected_model = "openai/gpt-oss-120b"  # no vision
        self.api.open_attachment_dialog()
        self.api._selected_model = "qwen/qwen3.8-27b"  # vision
        self.api.open_attachment_dialog()
        without, with_vision = (call["file_types"][0] for call in calls)
        self.assertTrue(without.startswith("Documentos (*.pdf;"))
        self.assertNotIn("*.png", without)
        self.assertIn("*.json", without)
        self.assertTrue(with_vision.startswith("Documentos e imágenes ("))
        self.assertIn("*.png", with_vision)


class TestSpeedMessages(ApiSettingsTestCase):
    """txt.ps1 Set-SpeechSpeed status texts."""

    def setUp(self):
        super().setUp()
        self.api = main.Api(settings_dir=self.settings_dir)

    def test_idle_change_reports_the_reading_speed(self):
        self.assertEqual(self.api.set_speech_speed(150),
                         {"ok": True, "message": "Velocidad de lectura: 1,50x."})

    def test_same_speed_reports_nothing(self):
        self.assertEqual(self.api.set_speech_speed(100), {"ok": True, "message": ""})

    def test_startup_default_is_silent(self):
        self.api.set_speech_speed(150, announce=False)
        self.assertEqual(self.api._speech_state()["message"], "")

    def test_change_during_repetir_reports_the_new_speed(self):
        engine = mock.Mock()
        engine.provider, engine.mode, engine.applied_speed = "Replay", "Playing", 100
        self.api.engine = engine
        with mock.patch.object(self.api, "_replay_position", return_value=2.0):
            result = self.api.set_speech_speed(125)
        self.assertEqual(result, {"ok": True, "message": "Velocidad cambiada a 1,25x."})
        engine.start_replay_playback.assert_called_once_with(2.0)


class TestCloseApp(ApiSettingsTestCase):
    def test_window_is_destroyed_without_holding_the_speech_lock(self):
        """Destroying the window runs its closing handler on the UI thread,
        which stops the speech again and needs the lock."""
        import threading
        lock_was_free = []

        def destroy():
            def probe():
                got = self.api._speech_lock.acquire(timeout=2)
                lock_was_free.append(got)
                if got:
                    self.api._speech_lock.release()
            other = threading.Thread(target=probe)  # stands in for the UI thread
            other.start()
            other.join(5)

        self.api._window = mock.Mock(destroy=destroy)
        self.assertEqual(self.api.close_app(), {"ok": True})
        self.assertEqual(lock_was_free, [True])
        self.api.engine.stop_voice_playback.assert_called()


class TestVoiceChangeDuringReading(unittest.TestCase):
    """txt.ps1 Switch-ActiveSpeechVoice."""

    def setUp(self):
        from txt_core.speech.engine import SpeechEngine
        self.messages = []
        self.engine = SpeechEngine(emit=lambda level, text: self.messages.append((level, text)))
        self.engine.voice_name = "es-CR-JuanNeural"

    def test_idle_engine_ignores_the_change(self):
        with mock.patch.object(self.engine, "_restart_active_playback") as restart:
            self.engine.set_voice("Edge · es-ES-ElviraNeural (Female)", "es-ES-ElviraNeural")
        restart.assert_not_called()
        self.assertEqual(self.messages, [])

    def test_live_reading_restarts_with_the_new_voice(self):
        self.engine.mode, self.engine.provider = "Playing", "Edge"
        with mock.patch.object(self.engine, "_restart_active_playback") as restart:
            self.engine.set_voice("Edge · es-ES-ElviraNeural (Female)", "es-ES-ElviraNeural")
        restart.assert_called_once_with(
            "Voz cambiada a Edge · es-ES-ElviraNeural (Female).",
            "Edge · es-ES-ElviraNeural (Female)", "es-ES-ElviraNeural")

    def test_same_voice_does_not_restart(self):
        self.engine.mode, self.engine.provider = "Playing", "Edge"
        with mock.patch.object(self.engine, "_restart_active_playback") as restart:
            self.engine.set_voice("Edge · es-CR-JuanNeural (Male)", "es-CR-JuanNeural")
        restart.assert_not_called()

    def test_repetir_keeps_its_audio_and_warns(self):
        self.engine.mode, self.engine.provider = "Playing", "Replay"
        with mock.patch.object(self.engine, "_restart_active_playback") as restart:
            self.engine.set_voice("Edge · es-ES-ElviraNeural (Female)", "es-ES-ElviraNeural")
        restart.assert_not_called()
        self.assertEqual(self.messages, [(
            "warning",
            "Repetir usa el audio ya generado; el cambio se aplica en la próxima lectura con Play.")])


class TestQuitOnClose(ApiSettingsTestCase):
    """Cerrar quits for certain (macOS kept the app alive in the Dock)."""

    def test_close_schedules_the_process_exit_only_in_the_real_app(self):
        self.api._window = mock.Mock()
        with mock.patch.object(main.threading, "Timer") as timer:
            self.api.close_app()
            timer.assert_not_called()  # tests and embedders never get killed
            self.api._quit_on_close = True
            self.api.close_app()
        self.assertEqual(timer.call_args[0][:2], (1.5, main.os._exit))
        self.assertEqual(timer.call_args[1]["args"], (0,))
        timer.return_value.start.assert_called_once()


class TestMacPauseSignals(unittest.TestCase):
    def test_suspend_and_resume_use_named_signals(self):
        """Signal numbers differ per system: 19 is SIGCONT on macOS."""
        import signal
        from txt_core.speech import engine
        if not hasattr(signal, "SIGSTOP"):
            self.skipTest("POSIX signals only")
        with mock.patch.object(engine.sys, "platform", "darwin"), \
                mock.patch.object(engine.os, "kill") as kill:
            engine.SuspendResume.suspend(4321)
            engine.SuspendResume.resume(4321)
        self.assertEqual(kill.call_args_list,
                         [mock.call(4321, signal.SIGSTOP), mock.call(4321, signal.SIGCONT)])

    def test_source_never_uses_signal_numbers(self):
        source = (Path(main.__file__).parent / "txt_core" / "speech" / "engine.py").read_text(
            encoding="utf-8")
        self.assertIn("os.kill(pid, signal.SIGSTOP)", source)
        self.assertIn("os.kill(pid, signal.SIGCONT)", source)
        self.assertNotRegex(source, r"os\.kill\(pid, \d+\)")


class TestRepetirWithANewVoice(ApiSettingsTestCase):
    def setUp(self):
        super().setUp()
        self.api.engine.replay.voice_display = "Edge · es-CR-JuanNeural (Male)"
        self.api.engine.provider = None
        self.api.engine.mode = "Idle"
        self.api._replay_source = ("hola mundo", "hola\nmundo")

    def test_same_voice_replays_the_recorded_audio(self):
        self.api.replay_start(3.0)
        self.api.engine.start_replay_playback.assert_called_once_with(3.0)
        self.api.engine.start_edge_session.assert_not_called()

    def test_changed_voice_reads_the_text_again_with_the_new_voice(self):
        self.api._speech_voice = "es-ES-ElviraNeural"
        with mock.patch.object(self.api, "_auto_switch_voice_for_text", return_value=None):
            result = self.api.replay_start(3.0)
        self.api.engine.start_replay_playback.assert_not_called()
        args = self.api.engine.start_edge_session.call_args[0]
        self.assertEqual(args[0], "hola mundo")
        self.assertEqual(args[2], "es-ES-ElviraNeural")
        self.assertEqual(result["message"], "Repitiendo con la voz nueva · es-ES-ElviraNeural")

    def test_changing_the_voice_while_repetir_plays_starts_over_with_it(self):
        self.api.engine.provider, self.api.engine.mode = "Replay", "Playing"
        with mock.patch.object(self.api, "_auto_switch_voice_for_text", return_value=None):
            result = self.api.set_speech_voice("es-ES-ElviraNeural")
        self.assertEqual(self.api.engine.start_edge_session.call_args[0][2], "es-ES-ElviraNeural")
        self.api.engine.set_voice.assert_not_called()
        self.assertEqual(result["message"], "Repitiendo con la voz nueva · es-ES-ElviraNeural")


class TestVolumeAndRepetirApi(ApiSettingsTestCase):
    def test_volume_goes_in_steps_of_ten_between_0_and_100(self):
        for asked, applied in ((55, 60), (0, 0), (-5, 0), (140, 100), (70, 70)):
            result = self.api.set_speech_volume(asked)
            self.assertEqual(result["volume"], applied)
            self.assertEqual(result["message"], f"Volumen: {applied}%.")
            self.api.engine.set_volume.assert_called_with(applied)

    def test_repetir_during_a_reading_stops_it_first(self):
        """Legacy Start-ReplayPlayback: stopping saves a fully generated
        reading as the Repetir audio."""
        self.api.engine.provider = "Edge"
        self.api.engine.replay.voice_display = ""
        self.api.replay_start(0)
        self.api.engine.stop_voice_playback.assert_called_once_with()
        self.api.engine.start_replay_playback.assert_called_once_with(0.0)


class TestPasteClipboardImage(ApiSettingsTestCase):
    def fake_image(self, path):
        with open(path, "wb") as handle:
            handle.write(b"\x89PNG\r\n\x1a\nfake")
        return True

    def test_no_image_means_paste_the_text(self):
        result = self.api.paste_clipboard_image(platform="darwin", mac_reader=lambda path: False)
        self.assertEqual(result, {"ok": True, "image": False})

    def test_model_without_vision_says_to_change_the_model(self):
        saved = []
        with mock.patch.object(self.api, "_selected_capabilities",
                               return_value=mock.Mock(vision=False)):
            result = self.api.paste_clipboard_image(
                platform="darwin", mac_reader=lambda path: saved.append(path) or self.fake_image(path))
        self.assertFalse(result["ok"])
        self.assertTrue(result["image"])
        self.assertIn("debés cambiar a un modelo con visión", result["error"])
        self.assertFalse(os.path.exists(saved[0]))  # the temporary PNG is removed

    def test_model_with_vision_attaches_the_image(self):
        with mock.patch.object(self.api, "_selected_capabilities",
                               return_value=mock.Mock(vision=True, text_files=True)):
            result = self.api.paste_clipboard_image(platform="darwin", mac_reader=self.fake_image)
        self.assertTrue(result["ok"])
        self.assertEqual(result["message"],
                         "Imagen del portapapeles adjuntada para la próxima acción de IA.")
        with self.api._attachments_lock:
            attached = list(self.api._attachments)
        self.assertEqual(len(attached), 1)
        self.assertTrue(attached[0].name.startswith("portapapeles-"))
        os.remove(attached[0].path)


class TestPlayAndPauseButtons(ApiSettingsTestCase):
    def test_a_new_play_resets_repetir_until_the_new_audio_is_whole(self):
        with mock.patch.object(self.api, "_auto_switch_voice_for_text", return_value=None):
            self.api.start_speech("hola mundo", "hola" + chr(10) + "mundo")
        self.api.engine._clear_replay_cache.assert_called_once_with()
        self.api.engine.start_edge_session.assert_called_once()

    def test_pause_button_follows_the_engine_state_not_the_ui(self):
        self.api.engine.mode = "Paused"
        self.api.toggle_pause_speech()
        self.api.engine.resume.assert_called_once_with()
        self.api.engine.pause.assert_not_called()
        self.api.engine.mode = "Playing"
        self.api.toggle_pause_speech()
        self.api.engine.pause.assert_called_once_with()
