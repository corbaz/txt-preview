"""Tests for the model catalog and capability mapping (legacy parity, S1)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt_core import models


class TestDefaultCatalog(unittest.TestCase):
    def test_default_model_present_and_catalog_size(self):
        self.assertEqual(models.DEFAULT_MODEL_ID, "openai/gpt-oss-120b")
        self.assertEqual(len(models.DEFAULT_GROQ_MODELS), 11)

    def test_catalog_ids_match_legacy(self):
        ids = [m.id for m in models.DEFAULT_GROQ_MODELS]
        self.assertIn("qwen/qwen3.8-27b", ids)
        self.assertIn("openai/gpt-oss-safeguard-20b", ids)


class TestCapabilities(unittest.TestCase):
    def test_gpt_oss_120b_has_web_but_no_vision(self):
        caps = models.model_capabilities("openai/gpt-oss-120b")
        self.assertEqual((caps.chat, caps.reasoning, caps.web, caps.vision, caps.text_files),
                         (True, True, True, False, True))

    def test_qwen_has_vision_but_no_web(self):
        caps = models.model_capabilities("qwen/qwen3.8-27b")
        self.assertEqual((caps.chat, caps.web, caps.vision), (True, False, True))

    def test_allam_text_only(self):
        caps = models.model_capabilities("allam-2-7b")
        self.assertEqual((caps.chat, caps.reasoning, caps.web, caps.vision), (True, False, False, False))

    def test_safeguard_only_web(self):
        caps = models.model_capabilities("openai/gpt-oss-safeguard-20b")
        self.assertEqual((caps.chat, caps.web), (False, True))

    def test_whisper_non_chat(self):
        self.assertFalse(models.model_capabilities("whisper-large-v3").chat)

    def test_unknown_model_unidentified(self):
        caps = models.model_capabilities("algo/nuevo")
        self.assertFalse(caps.chat)
        self.assertEqual(caps.summary, "Capacidades no catalogadas")

    def test_bridge_capabilities(self):
        caps = models.model_capabilities("claude:x", bridge_label="Claude", bridge_vision=True)
        self.assertTrue(caps.chat)
        self.assertFalse(caps.web)
        self.assertTrue(caps.vision)
        self.assertIn("Suscripción Claude (bridge local)", caps.summary)


class TestFetchModels(unittest.TestCase):
    def test_missing_key_message(self):
        with self.assertRaisesRegex(RuntimeError, "Ingresá una API key de Groq."):
            models.fetch_models("  ")

    def test_filters_inactive(self):
        payload = {"data": [
            {"id": "a", "active": True},
            {"id": "b", "active": False},
            {"id": "c"},
        ]}
        import urllib.error
        import io
        response = io.StringIO()
        class FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return b'{"data": [{"id": "a", "active": true}, {"id": "b", "active": false}, {"id": "c"}]}'
        with unittest.mock.patch("urllib.request.urlopen", return_value=FakeResponse()):
            result = models.fetch_models("key")
        self.assertEqual([m.id for m in result], ["a", "c"])


if __name__ == "__main__":
    unittest.main()
