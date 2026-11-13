"""Tests for Groq/bridge request bodies and headers (legacy parity, S1)."""
import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt_core import groq

CAPS_WEB = {"web": True}
CAPS_NOWEB = {"web": False}


class TestGroqBody(unittest.TestCase):
    def test_plain_groq_body(self):
        body = groq.build_groq_body("hola", "openai/gpt-oss-120b", False, CAPS_WEB)
        self.assertEqual(
            body,
            {"model": "openai/gpt-oss-120b", "messages": [{"role": "user", "content": "hola"}]},
        )

    def test_web_search_only_when_capable(self):
        body = groq.build_groq_body("hola", "openai/gpt-oss-120b", True, CAPS_WEB)
        self.assertEqual(body["tools"], [{"type": "browser_search"}])
        self.assertEqual(body["tool_choice"], "auto")

    def test_web_search_suppressed_without_capability(self):
        body = groq.build_groq_body("hola", "allam-2-7b", True, CAPS_NOWEB)
        self.assertNotIn("tools", body)
        self.assertNotIn("tool_choice", body)

    def test_text_attachments_legacy_format(self):
        body = groq.build_groq_body(
            "resumí",
            "openai/gpt-oss-120b",
            False,
            CAPS_WEB,
            text_attachments=[{"name": "notas.txt", "content": "línea"}],
        )
        expected = "resumí\n\n---\nArchivo adjunto: notas.txt\n---\nlínea"
        self.assertEqual(body["messages"][0]["content"], expected)

    def test_image_attachments_data_urls(self):
        image = Path(__file__).parent / "fixtures" / "pixel.png"
        image.parent.mkdir(exist_ok=True)
        image.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        try:
            body = groq.build_groq_body(
                "mirá", "qwen/qwen3.8-27b", False, CAPS_NOWEB, image_paths=[str(image)],
            )
            content = body["messages"][0]["content"]
            self.assertEqual(content[0], {"type": "text", "text": "mirá"})
            self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/png;base64,"))
        finally:
            image.unlink()

    def test_bridge_body_strips_prefix(self):
        body = groq.build_bridge_body("hola", "claude:claude-sonnet-4", "claude")
        self.assertEqual(body, {"model": "claude-sonnet-4", "message": "hola"})


class TestGroqHeadersAndPost(unittest.TestCase):
    def test_headers_bearer(self):
        headers = groq.groq_headers(" gsk_test ")
        self.assertEqual(headers["Authorization"], "Bearer gsk_test")
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_missing_api_key_raises_legacy_message(self):
        with self.assertRaisesRegex(RuntimeError, "Falta configurar la API key de Groq."):
            groq.groq_headers("   ")

    def test_post_chat_http_error_message(self):
        import urllib.error
        error = urllib.error.HTTPError(
            groq.GROQ_CHAT_URL, 401, "Unauthorized", {}, None,
        )
        with mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "Groq devolvió el estado HTTP 401."):
                groq.post_chat("key", {"model": "m", "messages": []})

    def test_extract_response_text_strips_citations(self):
        response = {"choices": [{"message": {"content": "respuesta 【2†L3-L4】."}}]}
        self.assertEqual(groq.extract_response_text(response), "respuesta.")


if __name__ == "__main__":
    unittest.main()


class TestUserAgent(unittest.TestCase):
    """Cloudflare (error 1010) rejects Python's default UA; every Groq call must identify the app."""

    def test_post_chat_sends_user_agent(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"choices": []}'

        def fake_urlopen(request, timeout=None):
            captured["ua"] = request.get_header("User-agent")
            return FakeResponse()

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            groq.post_chat("key", {"model": "m", "messages": []})
        self.assertTrue(captured["ua"].startswith("txt-preview/"))

    def test_fetch_models_sends_user_agent(self):
        from txt_core import models
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"data": []}'

        def fake_urlopen(request, timeout=None):
            captured["ua"] = request.get_header("User-agent")
            return FakeResponse()

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            models.fetch_models("key")
        self.assertTrue(captured["ua"].startswith("txt-preview/"))
