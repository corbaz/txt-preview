"""Tests for exports (T6/S1): PDF and MP3 of what Vista previa shows.

Legacy reference: txt.ps1 Export-PreviewPdf / Export-SpeechMp3 (4645-4790)
and the clipboard buttons (6400-6445). The PDF is produced by PyMuPDF so it
stays deterministic and needs neither msedge nor the network; the MP3 runs
through app/edge_tts_export.py (S17/T24), the truststore wrapper launched
by export_mp3 with a pinned argv — never `python -m edge_tts`, which
bypasses the native macOS trust store on Python 3.14 (Edge-only voices,
S6). The tests stub the edge_tts module the real wrapper imports.
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt_core.exports import build_print_html, export_mp3, markdown_to_text

try:
    import pymupdf
    HAVE_PYMUPDF = True
except ImportError:
    HAVE_PYMUPDF = False

from main import Api  # noqa: E402  (imports webview; guarded below)

try:
    import webview  # noqa: F401
    HAVE_WEBVIEW = True
except ImportError:
    HAVE_WEBVIEW = False


SAMPLE_MARKDOWN = "# Título del documento\n\nPárrafo con **negrita**.\n"

# The real app/edge_tts_export.py wrapper, exercised end to end with a
# stubbed edge_tts module (no network, no TLS).
EXPORT_SCRIPT = (Path(__file__).resolve().parents[2]
                 / "app" / "edge_tts_export.py")


# Stub edge_tts module the real app/edge_tts_export.py imports: records the
# wrapper invocation argv and the Communicate call, then either raises
# (FAKE_EDGE_TTS_FAIL) or yields one audio chunk whose data the wrapper
# writes to --media-file, exactly like a successful synthesis.
FAKE_EDGE_TTS_SOURCE = """\
import json, os, sys
# Full invocation: [edge_tts_export.py, --voice, ..., --media-file, ...].
with open(os.environ["FAKE_EDGE_TTS_ARGS"], "w", encoding="utf-8") as handle:
    json.dump(sys.argv, handle)

class Communicate:
    def __init__(self, text, voice, rate="", **kwargs):
        with open(os.environ["FAKE_EDGE_TTS_CALL"], "w", encoding="utf-8") as handle:
            json.dump({"text": text, "voice": voice, "rate": rate}, handle)

    async def stream(self):
        if os.environ.get("FAKE_EDGE_TTS_FAIL"):
            raise RuntimeError("la síntesis falló")
        yield {"type": "audio", "data": b"ID3fake-mp3"}
"""


class FakeEdgeTtsMixin:
    """Runs export_mp3 against a real python that fakes the edge_tts module."""

    def setUp(self):
        super().setUp()
        self.work_dir = tempfile.mkdtemp(prefix="txt-exports-test-")
        module_path = os.path.join(self.work_dir, "edge_tts.py")
        with open(module_path, "w", encoding="utf-8") as handle:
            handle.write(FAKE_EDGE_TTS_SOURCE)
        self.args_log = os.path.join(self.work_dir, "argv.json")
        self.call_log = os.path.join(self.work_dir, "communicate.json")
        self.env = dict(os.environ)
        self.env["PYTHONPATH"] = self.work_dir
        self.env["FAKE_EDGE_TTS_ARGS"] = self.args_log
        self.env["FAKE_EDGE_TTS_CALL"] = self.call_log
        self.env.pop("FAKE_EDGE_TTS_FAIL", None)

    def run_export(self, output_path, **kwargs):
        return export_mp3(
            "Texto para leer.", output_path,
            "es-ES-ElviraNeural", 120,
            python_command=sys.executable, runner=self._runner, **kwargs,
        )

    def _runner(self, argv, stdout=None, stderr=None):
        result = subprocess.run(
            argv, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        return result


class TestBuildPrintHtml(unittest.TestCase):
    def test_has_a4_page_margins_and_counter(self):
        html = build_print_html(SAMPLE_MARKDOWN)
        self.assertIn("@page", html)
        self.assertIn("size: A4", html)
        self.assertIn("22mm 20mm 24mm 20mm", html)
        self.assertIn('content: "Página " counter(page) " de " counter(pages)', html)

    def test_is_always_light_theme(self):
        html = build_print_html(SAMPLE_MARKDOWN)
        self.assertIn("#FFFFFF", html)

    def test_embeds_rendered_markdown_body(self):
        html = build_print_html(SAMPLE_MARKDOWN)
        self.assertIn("<h1", html)
        self.assertIn("Título del documento", html)
        self.assertIn("<strong>", html)

    def test_deterministic(self):
        self.assertEqual(
            build_print_html(SAMPLE_MARKDOWN),
            build_print_html(SAMPLE_MARKDOWN),
        )

    def test_empty_markdown_renders_empty_body(self):
        html = build_print_html("")
        self.assertNotIn("<h1", html)


class TestMarkdownToText(unittest.TestCase):
    def test_strips_markdown_markup(self):
        text = markdown_to_text(SAMPLE_MARKDOWN)
        self.assertIn("Título del documento", text)
        self.assertIn("Párrafo con negrita.", text)
        self.assertNotIn("**", text)
        self.assertNotIn("<", text)

    def test_empty_input(self):
        self.assertEqual(markdown_to_text(""), "")


@unittest.skipUnless(HAVE_PYMUPDF, "pymupdf no está instalado")
class TestExportPdf(unittest.TestCase):
    def setUp(self):
        self.work_dir = tempfile.mkdtemp(prefix="txt-exports-test-")
        self.output = os.path.join(self.work_dir, "preview.pdf")

    def test_small_markdown_produces_pdf(self):
        from txt_core.exports import export_pdf
        export_pdf(SAMPLE_MARKDOWN, self.output)
        self.assertTrue(os.path.isfile(self.output))
        with open(self.output, "rb") as handle:
            self.assertTrue(handle.read(5).startswith(b"%PDF"))
        doc = pymupdf.open(self.output)
        try:
            self.assertGreaterEqual(doc.page_count, 1)
            page_text = doc[0].get_text()
            self.assertIn("Título del documento", page_text)
            self.assertIn("Párrafo con negrita.", page_text)
            # Legacy @bottom-right counter, drawn by us because PyMuPDF
            # does not evaluate CSS counters.
            self.assertIn("Página 1 de 1", page_text)
        finally:
            doc.close()


class TestExportMp3(FakeEdgeTtsMixin, unittest.TestCase):
    def test_success_launches_export_wrapper_with_pinned_argv(self):
        output = os.path.join(self.work_dir, "lectura.mp3")
        self.run_export(output)
        self.assertTrue(os.path.isfile(output))
        with open(output, "rb") as handle:
            self.assertEqual(handle.read(), b"ID3fake-mp3")
        with open(self.args_log, encoding="utf-8") as handle:
            argv = json.load(handle)
        # Pinned wrapper invocation: the repository script (absolute path),
        # never `python -m edge_tts`; the legacy flags keep their meaning.
        self.assertEqual(argv, [
            str(EXPORT_SCRIPT),
            "--voice", "es-ES-ElviraNeural",
            "--rate", "20",
            "--text-file", argv[6],
            "--media-file", output,
        ])
        self.assertTrue(argv[6].endswith(".txt"))
        self.assertNotIn("-m", argv)
        self.assertNotIn("--write-media", argv)
        # The wrapper passed the preview text and the legacy rate
        # (percent - 100, signed "+NN%") to edge_tts.Communicate.
        with open(self.call_log, encoding="utf-8") as handle:
            call = json.load(handle)
        self.assertEqual(call, {
            "text": "Texto para leer.",
            "voice": "es-ES-ElviraNeural",
            "rate": "+20%",
        })
        # The temporary text file handed to --text-file is deleted afterwards.
        self.assertFalse(os.path.isfile(argv[6]),
                         "the temp text file must be deleted after the export")
        leftovers = [name for name in os.listdir(self.work_dir)
                     if name.startswith("txt-mp3-")]
        self.assertEqual(leftovers, [])

    def test_failure_raises_runtime_error_with_legacy_message(self):
        self.env["FAKE_EDGE_TTS_FAIL"] = "1"
        output = os.path.join(self.work_dir, "lectura.mp3")
        with self.assertRaises(RuntimeError) as caught:
            self.run_export(output)
        self.assertEqual(str(caught.exception),
                         "No se pudo generar el MP3: la síntesis falló")
        self.assertFalse(os.path.isfile(output))

    def test_missing_python_raises_legacy_message(self):
        with self.assertRaises(RuntimeError) as caught:
            export_mp3("texto", "no-importa.mp3", "es-ES-ElviraNeural", 100,
                       python_command="", runner=self._runner)
        self.assertEqual(
            str(caught.exception),
            "No se encontró Python para generar el MP3 con la voz Edge.",
        )


@unittest.skipUnless(HAVE_WEBVIEW, "pywebview no está instalado")
class TestApiPreviewText(unittest.TestCase):
    def test_render_preview_keeps_session_preview_text(self):
        api = Api()
        api.render_preview(SAMPLE_MARKDOWN)
        self.assertEqual(api.get_preview_text(), SAMPLE_MARKDOWN)
        self.assertIn("Título del documento", api.get_preview_plain_text())

    def test_ai_result_replaces_preview_text(self):
        api = Api()
        api.render_preview("viejo")
        result = api._ai_result("summarize", "nuevo resumen")
        self.assertEqual(api.get_preview_text(), "nuevo resumen")
        self.assertEqual(result["editor_action"], "replace")


@unittest.skipUnless(HAVE_WEBVIEW, "pywebview no está instalado")
class TestApiExportGuards(unittest.TestCase):
    def test_pdf_without_preview_text(self):
        api = Api()
        result = api.export_pdf()
        self.assertEqual(result, {"ok": False, "message": "No hay contenido para exportar a PDF."})

    def test_mp3_without_preview_text(self):
        api = Api()
        result = api.export_mp3()
        self.assertEqual(result, {"ok": False, "message": "No hay contenido para exportar a MP3."})

    def test_export_without_window_returns_cancelled(self):
        api = Api()
        api.render_preview(SAMPLE_MARKDOWN)
        self.assertEqual(api.export_pdf(), {"ok": False, "message": ""})
        self.assertEqual(api.export_mp3(), {"ok": False, "message": ""})


if __name__ == "__main__":
    unittest.main()
