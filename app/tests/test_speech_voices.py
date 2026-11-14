"""Edge voice catalog (T4/S6): parse + fetch + cache (legacy
ConvertFrom-EdgeVoiceCatalogText / Invoke-EdgeVoiceCatalogProcess /
Save-/Read-EdgeVoiceCatalogCache) and the Api.list_voices wiring.

No network: the catalog process is injected through `runner`.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from txt_core import settings
from txt_core.speech import voices

# Real edge-tts --list-voices lines carry trailing columns (locale, etc.),
# which the legacy filter regex requires after the gender.
CATALOG_SAMPLE = """\
Name, Gender
es-ES-ElviraNeural Female es-ES
es-AR-TomasNeural Male es-AR
en-US-JennyNeural Female en-US
en-GB-RyanNeural Male en-GB
fr-FR-DeniseNeural Female fr-FR
pt-BR-AntonioNeural Male pt-BR
"""


def fake_completed(stdout="", stderr="", returncode=0):
    return mock.Mock(stdout=stdout, stderr=stderr, returncode=returncode)


class TestParseVoiceCatalog(unittest.TestCase):
    def test_keeps_es_en_female_male_with_display(self):
        parsed = voices.parse_voice_catalog(CATALOG_SAMPLE)
        self.assertEqual(parsed, [
            {"name": "es-ES-ElviraNeural", "culture": "es-ES", "gender": "Female",
             "display_name": "Edge · es-ES-ElviraNeural (Female)"},
            {"name": "es-AR-TomasNeural", "culture": "es-AR", "gender": "Male",
             "display_name": "Edge · es-AR-TomasNeural (Male)"},
            {"name": "en-US-JennyNeural", "culture": "en-US", "gender": "Female",
             "display_name": "Edge · en-US-JennyNeural (Female)"},
            {"name": "en-GB-RyanNeural", "culture": "en-GB", "gender": "Male",
             "display_name": "Edge · en-GB-RyanNeural (Male)"},
        ])

    def test_line_without_trailing_columns_is_dropped(self):
        # Legacy regex: '\s+' after the gender is required.
        self.assertEqual(voices.parse_voice_catalog("es-ES-ElviraNeural Female"), [])

    def test_other_cultures_and_headers_are_dropped(self):
        parsed = voices.parse_voice_catalog(CATALOG_SAMPLE)
        names = [voice["name"] for voice in parsed]
        self.assertNotIn("fr-FR-DeniseNeural", names)
        self.assertNotIn("pt-BR-AntonioNeural", names)

    def test_empty_text_gives_empty_list(self):
        self.assertEqual(voices.parse_voice_catalog(""), [])
        self.assertEqual(voices.parse_voice_catalog(None), [])


class TestFetchVoiceCatalog(unittest.TestCase):
    def test_runs_the_repository_wrapper_and_parses(self):
        # S17/T24: the catalog runs app/edge_tts_voices.py (native system TLS
        # trust injected before edge_tts), never `python -m edge_tts`.
        captured = {}

        def runner(args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return fake_completed(stdout=CATALOG_SAMPLE)

        parsed = voices.fetch_voice_catalog("fakepython", runner=runner)
        self.assertEqual(len(parsed), 4)
        self.assertEqual(captured["args"],
                         ["fakepython", str(voices.VOICE_CATALOG_WRAPPER)])
        self.assertEqual(captured["kwargs"]["timeout"], 15)

    def test_wrapper_lives_in_the_app_directory(self):
        self.assertEqual(voices.VOICE_CATALOG_WRAPPER.name, "edge_tts_voices.py")
        self.assertEqual(voices.VOICE_CATALOG_WRAPPER.parent.name, "app")
        self.assertTrue(voices.VOICE_CATALOG_WRAPPER.is_file())

    def test_empty_output_raises_legacy_error(self):
        def runner(args, **kwargs):
            return fake_completed(stdout="", stderr="", returncode=0)
        with self.assertRaises(RuntimeError) as caught:
            voices.fetch_voice_catalog("fakepython", runner=runner)
        self.assertIn("No se pudo cargar el catálogo de voces Edge", str(caught.exception))

    def test_missing_edge_tts_module_raises_install_hint(self):
        def runner(args, **kwargs):
            return fake_completed(stdout="", returncode=1,
                                  stderr="No module named 'edge_tts'")
        with self.assertRaises(RuntimeError) as caught:
            voices.fetch_voice_catalog("fakepython", runner=runner)
        self.assertIn("edge-tts no está instalado", str(caught.exception))

    def test_nonzero_exit_raises_legacy_error(self):
        def runner(args, **kwargs):
            return fake_completed(stdout="", returncode=1, stderr="boom")
        with self.assertRaises(RuntimeError) as caught:
            voices.fetch_voice_catalog("fakepython", runner=runner)
        self.assertIn("No se pudo cargar el catálogo de voces Edge", str(caught.exception))
        self.assertIn("boom", str(caught.exception))

    def test_timeout_raises_legacy_error(self):
        def runner(args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args, timeout=15)
        with self.assertRaises(RuntimeError) as caught:
            voices.fetch_voice_catalog("fakepython", runner=runner)
        self.assertIn("superó 15 segundos", str(caught.exception))

    def test_missing_python_raises(self):
        with self.assertRaises(RuntimeError):
            voices.fetch_voice_catalog("", runner=lambda *a, **k: fake_completed())


class TestVoiceCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = self._tmp.name

    def test_missing_cache_returns_empty(self):
        self.assertEqual(voices.load_voice_cache(self.directory), [])

    def test_save_then_load_roundtrip(self):
        parsed = voices.parse_voice_catalog(CATALOG_SAMPLE)
        self.assertTrue(voices.save_voice_cache(parsed, self.directory))
        self.assertEqual(voices.load_voice_cache(self.directory), parsed)
        path = os.path.join(self.directory, "edge-voices.json")
        with open(path, encoding="utf-8") as handle:
            stored = json.load(handle)
        self.assertEqual(stored["version"], 1)
        self.assertEqual(len(stored["voices"]), 4)

    def test_corrupt_cache_returns_empty(self):
        path = os.path.join(self.directory, "edge-voices.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertEqual(voices.load_voice_cache(self.directory), [])

    def test_wrong_version_returns_empty(self):
        path = os.path.join(self.directory, "edge-voices.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"version": 99, "voices": []}, handle)
        self.assertEqual(voices.load_voice_cache(self.directory), [])

    def test_invalid_entries_are_filtered(self):
        path = os.path.join(self.directory, "edge-voices.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "voices": [
                {"name": "fr-FR-DeniseNeural", "culture": "fr-FR",
                 "gender": "Female", "display_name": "x"},
                {"name": "es-ES-ElviraNeural", "culture": "es-ES",
                 "gender": "Female", "display_name": "Edge · es-ES-ElviraNeural (Female)"},
            ]}, handle)
        loaded = voices.load_voice_cache(self.directory)
        self.assertEqual([voice["name"] for voice in loaded], ["es-ES-ElviraNeural"])

    def test_empty_save_writes_nothing(self):
        self.assertFalse(voices.save_voice_cache([], self.directory))
        self.assertFalse(os.path.isfile(
            os.path.join(self.directory, "edge-voices.json")))


class ApiVoicesTestCase(unittest.TestCase):
    """Api against a temp settings dir with the catalog process injected."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.settings_dir = self._tmp.name
        self.api = main.Api(settings_dir=self.settings_dir,
                            legacy_dir=self._tmp.name + "-legacy")
        self.api.engine = mock.Mock()
        self.calls = []

    def runner(self, stdout=CATALOG_SAMPLE, returncode=0, stderr=""):
        def _run(args, **kwargs):
            self.calls.append(list(args))
            return fake_completed(stdout=stdout, stderr=stderr, returncode=returncode)
        return _run

    def test_list_voices_fetches_and_saves_cache(self):
        result = self.api.list_voices(runner=self.runner())
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["voices"]), 4)
        self.assertTrue(os.path.isfile(
            os.path.join(self.settings_dir, "edge-voices.json")))

    def test_list_voices_uses_cache_without_running_the_process(self):
        self.api.list_voices(runner=self.runner())
        self.calls.clear()
        result = self.api.list_voices(runner=self.runner())
        self.assertTrue(result["ok"])
        self.assertEqual(self.calls, [])

    def test_force_refresh_runs_the_process_again(self):
        self.api.list_voices(runner=self.runner())
        self.calls.clear()
        self.api.list_voices(True, runner=self.runner())
        self.assertEqual(len(self.calls), 1)

    def test_fetch_failure_without_cache_reports_error(self):
        result = self.api.list_voices(runner=self.runner(stdout="", returncode=1))
        self.assertFalse(result["ok"])
        self.assertEqual(result["voices"], [])
        self.assertIn("No se pudo cargar el catálogo de voces Edge", result["error"])

    def test_fetch_failure_with_stale_cache_falls_back(self):
        self.api.list_voices(runner=self.runner())
        result = self.api.list_voices(True, runner=self.runner(stdout="", returncode=1))
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["voices"]), 4)
        self.assertIn("No se pudo actualizar la lista de voces Edge", result["warning"])

    def test_set_speech_voice_persists_via_settings(self):
        result = self.api.set_speech_voice("es-AR-TomasNeural")
        self.assertTrue(result["ok"])
        self.assertEqual(result["voice"], "es-AR-TomasNeural")
        self.assertEqual(
            settings.load_settings(self.settings_dir)["speech_voice"],
            "es-AR-TomasNeural")
        self.assertEqual(self.api._speech_voice, "es-AR-TomasNeural")

    def test_default_voice_display(self):
        self.assertEqual(self.api._speech_voice_display(), "Elvira (es-ES)")

    def test_catalog_voice_display_uses_legacy_format(self):
        self.api.list_voices(runner=self.runner())
        self.api.set_speech_voice("es-AR-TomasNeural")
        self.assertEqual(self.api._speech_voice_display(),
                         "Edge · es-AR-TomasNeural (Male)")

    def test_unknown_voice_display_falls_back_to_the_id(self):
        self.api.list_voices(runner=self.runner())
        self.api.set_speech_voice("xx-XX-UnknownNeural")
        self.assertEqual(self.api._speech_voice_display(), "xx-XX-UnknownNeural")


if __name__ == "__main__":
    unittest.main()
