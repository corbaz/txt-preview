"""Extracts text from generated .docx/.pptx files through the app's own function."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "txt.ps1"

DOCX_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:r><w:t>Informe de ventas</w:t></w:r></w:p>
<w:p><w:r><w:t xml:space="preserve">Primer </w:t></w:r><w:r><w:t>párrafo</w:t></w:r><w:r><w:tab/><w:t>tabulado</w:t></w:r></w:p>
</w:body></w:document>"""

SLIDE_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree>
<p:sp><p:txBody><a:p><a:r><a:t>{title}</a:t></a:r></a:p><a:p><a:r><a:t>{body}</a:t></a:r></a:p></p:txBody></p:sp>
</p:spTree></p:cSld></p:sld>"""


def _write_zip(path: Path, entries: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "needs Windows and PowerShell 7")
class DocumentExtractionTests(unittest.TestCase):
    def _extract(self, path: Path) -> str:
        command = (
            "$env:TXT_PREVIEW_TEST_MODE = '1'; "
            "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
            f". '{SCRIPT}'; ConvertFrom-DocumentFile '{path}'"
        )
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-STA", "-Command", command],
            capture_output=True, timeout=120, encoding="utf-8", errors="replace",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_docx_paragraphs_and_tabs(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "informe.docx"
            _write_zip(path, {"word/document.xml": DOCX_XML})
            text = self._extract(path)
        self.assertIn("Informe de ventas", text)
        self.assertIn("Primer párrafo\ttabulado", text)

    def test_pptx_slides_in_numeric_order(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "charla.pptx"
            # slide10 sorts before slide2 as text; the app must order numerically.
            _write_zip(path, {
                "ppt/slides/slide1.xml": SLIDE_XML.format(title="Portada", body="Bienvenida"),
                "ppt/slides/slide2.xml": SLIDE_XML.format(title="Agenda", body="Temas"),
                "ppt/slides/slide10.xml": SLIDE_XML.format(title="Cierre", body="Gracias"),
            })
            text = self._extract(path)
        self.assertIn("Diapositiva 1", text)
        self.assertLess(text.index("Agenda"), text.index("Cierre"))
        self.assertIn("Bienvenida", text)


if __name__ == "__main__":
    unittest.main()
