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


class TestS11OfficialCapabilityMap(unittest.TestCase):
    """S11/T18: capabilities mapped conservatively by exact official IDs;
    unknown IDs stay all-false/unclassified."""

    def test_llama_models_chat_with_documents(self):
        for model_id in ("llama-3.1-8b-instant", "llama-3.3-70b-versatile"):
            caps = models.model_capabilities(model_id)
            self.assertEqual(
                (caps.chat, caps.reasoning, caps.web, caps.vision, caps.text_files),
                (True, False, False, False, True),
                model_id)

    def test_minimax_chat_with_reasoning(self):
        caps = models.model_capabilities("minimaxai/minimax-m2.7")
        self.assertEqual(
            (caps.chat, caps.reasoning, caps.web, caps.vision, caps.text_files),
            (True, True, False, False, True))

    def test_muse_spark_chat_reasoning_and_vision(self):
        caps = models.model_capabilities("meta-models/muse-spark-open")
        self.assertEqual(
            (caps.chat, caps.reasoning, caps.web, caps.vision, caps.text_files),
            (True, True, False, True, True))

    def test_gpt_oss_variants_keep_web_search(self):
        for model_id in ("openai/gpt-oss-120b", "openai/gpt-oss-20b"):
            self.assertTrue(models.model_capabilities(model_id).web, model_id)

    def test_unknown_live_id_stays_all_false(self):
        caps = models.model_capabilities("moonshotai/kimi-k2")
        self.assertEqual(
            (caps.chat, caps.reasoning, caps.web, caps.vision, caps.text_files),
            (False, False, False, False, False))
        self.assertEqual(caps.summary, "Capacidades no catalogadas")


class TestFetchModels(unittest.TestCase):
    def test_missing_key_message(self):
        with self.assertRaisesRegex(RuntimeError, "Ingresá una API key de Groq."):
            models.fetch_models("  ")

    def test_tls_error_raises_controlled_message(self):
        """S17/T24: a TLS/URLError on Groq /models startup becomes a controlled
        RuntimeError naming the Groq connection/TLS failure, so update_models
        can fall back without a pywebview traceback."""
        import ssl
        import urllib.error
        from unittest import mock
        reason = ssl.SSLCertVerificationError(
            20, "Basic Constraints of CA cert not marked critical")
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError(reason)):
            with self.assertRaisesRegex(
                    RuntimeError,
                    "No se pudo conectar con Groq para cargar los modelos "
                    "\(fallo de conexión/TLS\):.*") as caught:
                models.fetch_models("key")
        self.assertIn("Basic Constraints of CA cert not marked critical", str(caught.exception))

    def test_url_error_raises_controlled_message(self):
        """S17/T24: any URLError (DNS/refused connection) gets the same treatment."""
        import urllib.error
        from unittest import mock
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("name resolution failed")):
            with self.assertRaisesRegex(RuntimeError, "No se pudo conectar con Groq"):
                models.fetch_models("key")

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
