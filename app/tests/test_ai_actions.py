"""Api AI-action wiring (S1): prompts, Groq/bridge routing, legacy post-actions
and error strings, ported from txt.ps1 regions 6340-6580."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt_core import bridges, groq


def api_with_env(test, **environ):
    import main
    # Temp settings dir so persistence never touches the real user folder.
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    api = main.Api(settings_dir=tmp.name, legacy_dir=tmp.name + "-legacy")
    patcher = mock.patch.dict(os.environ, environ, clear=False)
    patcher.start()
    test.addCleanup(patcher.stop)
    # A stale GROQ_API_KEY must not leak between tests.
    os.environ.pop("GROQ_API_KEY", None)
    for key, value in environ.items():
        os.environ[key] = value
    return api


class TestSelectedModel(unittest.TestCase):
    def test_default_model(self):
        api = api_with_env(self)
        self.assertEqual(api.get_selected_model(), "openai/gpt-oss-120b")

    def test_set_selected_model(self):
        api = api_with_env(self)
        api.set_selected_model("claude:claude-sonnet-4")
        self.assertEqual(api.get_selected_model(), "claude:claude-sonnet-4")


class TestAskAiInput(unittest.TestCase):
    def test_empty_input_rejected_with_legacy_message(self):
        api = api_with_env(self)
        result = api.ask_ai("consult", False, "")
        self.assertEqual(
            result,
            {"ok": False, "error": "Ingresá una consulta en el Editor o adjuntá al menos un archivo."},
        )

    def test_whitespace_only_input_rejected(self):
        api = api_with_env(self)
        result = api.ask_ai("summarize", False, "   \n  ")
        self.assertEqual(
            result["error"],
            "Ingresá contenido en el Editor o adjuntá al menos un archivo.",
        )

    def test_unknown_action(self):
        api = api_with_env(self)
        result = api.ask_ai("translate", False, "hola")
        self.assertFalse(result["ok"])

    def test_attachments_satisfy_the_input_check(self):
        api = api_with_env(self)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "notas.txt")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("contenido")
            api.add_attachments([path])
        with mock.patch.object(groq, "post_chat", return_value={"text": "x"}):
            api.ask_ai("consult", False, "")
        # no exception: the attachment replaced the editor text requirement


class TestAskAiGroqRouting(unittest.TestCase):
    def test_missing_api_key_message(self):
        api = api_with_env(self)
        result = api.ask_ai("consult", False, "hola")
        self.assertEqual(result, {"ok": False, "error": groq.ERR_MISSING_API_KEY})

    def test_consult_keeps_editor_and_shows_result(self):
        api = api_with_env(self, GROQ_API_KEY="gsk_test")
        response = {"choices": [{"message": {"content": "respuesta"}}]}
        with mock.patch.object(groq, "post_chat", return_value=response) as post:
            result = api.ask_ai("consult", False, "mi consulta")
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "respuesta")
        self.assertEqual(result["editor_action"], "keep")
        self.assertEqual(
            result["message"],
            "Respuesta lista en Vista previa. Tu consulta sigue en el Editor.",
        )
        body = post.call_args[0][1]
        self.assertIn("Consulta:", body["messages"][0]["content"])
        self.assertEqual(body["model"], "openai/gpt-oss-120b")

    def test_web_search_flag_reaches_the_body(self):
        api = api_with_env(self, GROQ_API_KEY="gsk_test")
        with mock.patch.object(groq, "post_chat", return_value={"text": "x"}) as post:
            api.ask_ai("consult", True, "hola")
        self.assertEqual(post.call_args[0][1]["tools"], [{"type": "browser_search"}])

    def test_text_attachment_reaches_the_prompt(self):
        api = api_with_env(self, GROQ_API_KEY="gsk_test")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "notas.txt")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("datos adjuntos")
            api.add_attachments([path])
        with mock.patch.object(groq, "post_chat", return_value={"text": "x"}) as post:
            api.ask_ai("summarize", False, "")
        content = post.call_args[0][1]["messages"][0]["content"]
        self.assertIn("Archivo adjunto: notas.txt", content)
        self.assertIn("datos adjuntos", content)

    def test_image_attachment_reaches_the_body_as_data_url(self):
        api = api_with_env(self, GROQ_API_KEY="gsk_test")
        api.set_selected_model("qwen/qwen3.8-27b")  # vision-capable Groq model
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "foto.png")
            with open(path, "wb") as fh:
                fh.write(b"png")
            api.add_attachments([path])
            with mock.patch.object(groq, "post_chat", return_value={"text": "x"}) as post:
                api.ask_ai("consult", False, "")
            content = post.call_args[0][1]["messages"][0]["content"]
        self.assertEqual(content[0]["type"], "text")
        self.assertEqual(content[1]["type"], "image_url")
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_network_error_uses_legacy_message(self):
        api = api_with_env(self, GROQ_API_KEY="gsk_test")
        with mock.patch.object(groq, "post_chat", side_effect=RuntimeError("boom")):
            result = api.ask_ai("correct", False, "texto")
        self.assertEqual(result, {"ok": False, "error": "Error al conectar con la API."})


class TestAskAiPostActions(unittest.TestCase):
    def test_summarize_replaces_editor(self):
        api = api_with_env(self, GROQ_API_KEY="gsk_test")
        with mock.patch.object(groq, "post_chat", return_value={"text": "resumen"}):
            result = api.ask_ai("summarize", False, "texto largo")
        self.assertEqual(result["editor_action"], "replace")
        self.assertEqual(result["message"], "Resumen profesional listo en Vista previa.")

    def test_correct_replaces_editor_and_copies(self):
        api = api_with_env(self, GROQ_API_KEY="gsk_test")
        with mock.patch.object(groq, "post_chat", return_value={"text": "corregido"}):
            result = api.ask_ai("correct", False, "texto")
        self.assertEqual(result["editor_action"], "replace")
        self.assertTrue(result["clipboard"])
        self.assertEqual(
            result["message"],
            "Se copió al portapapeles. Usá Ctrl+V para pegarlo en cualquier lugar.",
        )

    def test_translate_es_en_sets_voice_language_en(self):
        api = api_with_env(self, GROQ_API_KEY="gsk_test")
        with mock.patch.object(groq, "post_chat", return_value={"text": "hello"}) as post:
            result = api.ask_ai("translate_es_en", False, "hola")
        self.assertEqual(result["editor_action"], "replace")
        self.assertEqual(result["speech_language"], "en")
        self.assertIn("español", post.call_args[0][1]["messages"][0]["content"])
        self.assertIn("inglés", post.call_args[0][1]["messages"][0]["content"])

    def test_translate_en_es_sets_voice_language_es(self):
        api = api_with_env(self, GROQ_API_KEY="gsk_test")
        with mock.patch.object(groq, "post_chat", return_value={"text": "hola"}):
            result = api.ask_ai("translate_en_es", False, "hello")
        self.assertEqual(result["speech_language"], "es")


class TestAskAiBridgeRouting(unittest.TestCase):
    def test_missing_bridge_password_message(self):
        api = api_with_env(self)
        api.set_selected_model("claude:claude-sonnet-4")
        with mock.patch.object(bridges, "get_bridge_password", return_value=""):
            result = api.ask_ai("consult", False, "hola")
        self.assertEqual(
            result,
            {"ok": False, "error": "Falta la contraseña del bridge de Claude (CLAUDE_BRIDGE_PASSWORD)."},
        )

    def test_bridge_chat_used_for_bridge_models(self):
        api = api_with_env(self)
        api.set_selected_model("claude:claude-sonnet-4")
        response = {"text": "respuesta"}
        with mock.patch.object(bridges, "get_bridge_password", return_value="secreta"), \
             mock.patch.object(bridges, "bridge_chat", return_value=response) as chat:
            result = api.ask_ai("summarize", False, "texto")
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "respuesta")
        bridge, body, password = chat.call_args[0]
        self.assertEqual(bridge.key, "claude")
        self.assertEqual(body["model"], "claude-sonnet-4")
        self.assertEqual(password, "secreta")

    def test_bridge_password_env_is_read_when_no_memory_entry(self):
        api = api_with_env(self, CLAUDE_BRIDGE_PASSWORD="des-env")
        api.set_selected_model("claude:claude-sonnet-4")
        with mock.patch.object(bridges, "bridge_chat", return_value={"text": "ok"}) as chat:
            api.ask_ai("consult", False, "hola")
        self.assertEqual(chat.call_args[0][2], "des-env")

    def test_in_memory_password_dict_used_when_env_absent(self):
        # Legacy resolution order: env first, then the session dict, then the file.
        api = api_with_env(self)
        api.set_selected_model("claude:claude-sonnet-4")
        api._bridge_passwords["claude"] = "des-memoria"
        with mock.patch.object(bridges, "bridge_chat", return_value={"text": "ok"}) as chat:
            api.ask_ai("consult", False, "hola")
        self.assertEqual(chat.call_args[0][2], "des-memoria")


class TestAttachmentsApi(unittest.TestCase):
    def setUp(self):
        self.api = api_with_env(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name, data="contenido"):
        path = os.path.join(self.tmp.name, name)
        if isinstance(data, bytes):
            with open(path, "wb") as fh:
                fh.write(data)
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(data)
        return path

    def test_add_and_summary(self):
        result = self.api.add_attachments([self.path("notas.txt")])
        self.assertEqual(result["added"], ["notas.txt"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(
            result["summary"],
            "Se enviarán a Groq (1): notas.txt",
        )
        self.assertEqual(self.api.get_attachment_summary(), result["summary"])

    def test_empty_summary(self):
        self.assertEqual(
            self.api.get_attachment_summary(),
            "Sin archivos adjuntos para la próxima solicitud",
        )

    def test_error_returns_legacy_prefixed_message(self):
        result = self.api.add_attachments([self.path("datos.xlsx")])
        self.assertEqual(result["added"], [])
        self.assertEqual(
            result["errors"],
            ["No se pudo adjuntar: Tipo de archivo no compatible: .xlsx"],
        )

    def test_clear_attachments(self):
        self.api.add_attachments([self.path("notas.txt")])
        result = self.api.clear_attachments()
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["summary"],
            "Sin archivos adjuntos para la próxima solicitud",
        )

    def test_image_rejected_for_non_vision_model(self):
        result = self.api.add_attachments([self.path("foto.png", b"png")])
        self.assertEqual(result["added"], [])
        self.assertEqual(
            result["errors"],
            ["No se pudo adjuntar: El modelo elegido no admite imágenes."],
        )

    def test_image_accepted_for_vision_model(self):
        self.api.set_selected_model("qwen/qwen3.8-27b")
        result = self.api.add_attachments([self.path("foto.png", b"png")])
        self.assertEqual(result["added"], ["foto.png"])


if __name__ == "__main__":
    unittest.main()
