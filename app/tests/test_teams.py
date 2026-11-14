"""«Copiar Teams»: rich clipboard copy of the preview content."""
import base64
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from txt_core import clipboard, teams

TABLE = "# Título\n\n| A | B |\n|---|---|\n| 1 | [link](https://example.com) |\n"


class TestTeamsHtml(unittest.TestCase):
    def test_table_heading_and_link_get_inline_styles(self):
        html = teams.teams_html(TABLE)
        self.assertIn('<h1 style="font-size:22px;color:#7579EB;', html)
        self.assertIn('<table style="border-collapse:collapse;margin:8px 0">', html)
        self.assertIn('<th style="border:1px solid #8A8A8A;padding:6px 10px;'
                      'background-color:#5B5FC7;color:#FFFFFF;text-align:left">A</th>', html)
        self.assertIn('<td style="border:1px solid #8A8A8A;padding:6px 10px">1</td>', html)
        self.assertIn('<a style="text-decoration:underline" href="https://example.com">link</a>',
                      html)

    def test_code_block_is_styled_once_and_inline_code_separately(self):
        html = teams.teams_html("usa `x`\n\n```\nprint(1)\n```\n")
        self.assertEqual(html.count("padding:1px 4px"), 1)   # only the inline code
        self.assertEqual(html.count("padding:8px 10px"), 1)  # only the block
        self.assertIn("<pre style=", html)

    def test_local_image_is_embedded_and_web_image_keeps_its_address(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "foto.png"
            image.write_bytes(b"PNGDATA")
            html = teams.teams_html(
                f"![local]({image.as_posix()})\n\n![web](https://example.com/a.png)")
        encoded = base64.b64encode(b"PNGDATA").decode("ascii")
        self.assertIn(f'src="data:image/png;base64,{encoded}"', html)
        self.assertIn('src="https://example.com/a.png"', html)
        self.assertIn('<img style="max-width:100%"', html)

    def test_cf_html_offsets_point_at_the_fragment_in_utf8_bytes(self):
        fragment = "<p>año ✓</p>"
        payload = teams.cf_html(fragment).encode("utf-8")
        fields = dict(line.split(":", 1) for line in
                      payload.decode("utf-8").split("\r\n")[:5])
        self.assertEqual(fields["Version"], "0.9")
        start, end = int(fields["StartFragment"]), int(fields["EndFragment"])
        self.assertEqual(payload[start:end].decode("utf-8"), fragment)
        self.assertEqual(payload[int(fields["StartHTML"]):int(fields["EndHTML"])].decode("utf-8"),
                         "<html><body><!--StartFragment-->" + fragment
                         + "<!--EndFragment--></body></html>")


class TestWriteClipboardHtml(unittest.TestCase):
    def test_windows_passes_both_payloads_in_temp_files_and_removes_them(self):
        seen = {}

        def runner(argv, **kwargs):
            env = kwargs["env"]
            seen["argv"] = argv
            seen["html"] = Path(env[clipboard.HTML_FILE_ENV_VAR]).read_text(encoding="utf-8")
            seen["text"] = Path(env[clipboard.TEXT_FILE_ENV_VAR]).read_text(encoding="utf-8")
            seen["paths"] = [env[clipboard.HTML_FILE_ENV_VAR], env[clipboard.TEXT_FILE_ENV_VAR]]
            return mock.Mock(returncode=0, stdout="", stderr="")

        clipboard.write_clipboard_html("<p>hola</p>", "hola", platform="win32", runner=runner)
        self.assertEqual(seen["argv"][-1], clipboard.POWERSHELL_WRITE_HTML_COMMAND)
        self.assertIn("-STA", seen["argv"])
        self.assertTrue(seen["html"].startswith("Version:0.9"))
        self.assertIn("<!--StartFragment--><p>hola</p><!--EndFragment-->", seen["html"])
        self.assertEqual(seen["text"], "hola")
        self.assertFalse(any(Path(path).exists() for path in seen["paths"]))

    def test_mac_writes_html_and_plain_text(self):
        written = []
        clipboard.write_clipboard_html("<p>hola</p>", "hola", platform="darwin",
                                       mac_writer=lambda html, text: written.append((html, text)))
        self.assertEqual(written, [("<p>hola</p>", "hola")])

    def test_failure_is_a_controlled_message(self):
        failed = mock.Mock(returncode=1, stdout="", stderr="acceso denegado")
        with mock.patch.object(clipboard.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError,
                                        r"No se pudo copiar al portapapeles \(acceso denegado\)"):
                clipboard.write_clipboard_html("<p>x</p>", "x", platform="win32",
                                               runner=lambda argv, **k: failed)


class TestCopyForTeamsApi(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.api = main.Api(settings_dir=self._dir.name)

    def test_copies_the_preview_content_as_rich_and_plain_text(self):
        self.api.set_preview_content("## Hola\n\ntexto **fuerte**")
        with mock.patch.object(main.clipboard, "write_clipboard_html") as write:
            result = self.api.copy_for_teams()
        html, text = write.call_args[0]
        self.assertIn('<h2 style="font-size:19px;', html)
        self.assertIn("<strong>fuerte</strong>", html)
        self.assertEqual(text, "Hola\n\ntexto fuerte")
        self.assertEqual(result, {
            "ok": True,
            "message": "Copiado con formato para Teams. Pegalo en el chat con Ctrl+V."})

    def test_nothing_to_copy(self):
        with mock.patch.object(main.clipboard, "write_clipboard_html") as write:
            result = self.api.copy_for_teams()
        write.assert_not_called()
        self.assertEqual(result, {"ok": False, "error": "No hay contenido para copiar."})


if __name__ == "__main__":
    unittest.main()
