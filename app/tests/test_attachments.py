"""Attachment extraction and attachment-list rules, ported from txt.ps1 (S1).

Legacy reference: regions 5745-5940 (document extractors), 6020-6180
(attachments add/limits). .doc/.ppt are intentionally NOT supported in the new
app: the COM/Office path is Windows-only, so the legacy binary formats are
rejected with a clear conversion message.
"""
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import pymupdf  # noqa: F401
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

from txt_core import attachments
from txt_core.attachments import Attachment, Kind


def make_docx(path, paragraphs):
    """Minimal docx zip: word/document.xml with w:document/w:body/w:p/w:t."""
    body = "".join(
        "<w:p><w:r><w:t>{}</w:t></w:r></w:p>".format(p) for p in paragraphs
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{attachments.W_NS}"><w:body>{body}</w:body></w:document>'
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", xml)


def make_pptx(path, slides):
    """Minimal pptx zip: ppt/slides/slide<N>.xml with a:p/a:t runs."""
    with zipfile.ZipFile(path, "w") as zf:
        for number, lines in slides:
            paragraphs = "".join(
                f"<a:p><a:r><a:t>{line}</a:t></a:r></a:p>" for line in lines
            )
            xml = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<p:sld xmlns:a="{attachments.A_NS}" '
                f'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                f"<p:cSld><p:spTree>{paragraphs}</p:spTree></p:cSld></p:sld>"
            )
            zf.writestr(f"ppt/slides/slide{number}.xml", xml)


class TestAttachmentSummary(unittest.TestCase):
    def test_empty_summary(self):
        self.assertEqual(
            attachments.attachment_summary([], "Groq"),
            "Sin archivos adjuntos para la próxima solicitud",
        )

    def test_summary_matches_update_attachmentsummary(self):
        summary = attachments.attachment_summary(["a.txt", "b.md"], "Groq")
        self.assertEqual(summary, "Se enviarán a Groq (2): a.txt, b.md")

    def test_summary_uses_bridge_label(self):
        summary = attachments.attachment_summary(["doc.pdf"], "Claude")
        self.assertEqual(summary, "Se enviarán a Claude (1): doc.pdf")


class TestTextExtraction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def test_text_file_extracts_content(self):
        path = self.path("notas.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("línea uno\nlínea dos")
        attachment = attachments.extract(path)
        self.assertEqual(attachment.kind, Kind.TEXT)
        self.assertEqual(attachment.name, "notas.txt")
        self.assertEqual(attachment.content, "línea uno\nlínea dos")

    def test_text_file_over_2mb_rejected(self):
        path = self.path("grande.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("x" * (attachments.TEXT_FILE_LIMIT + 1))
        with self.assertRaises(ValueError) as ctx:
            attachments.extract(path)
        self.assertEqual(
            str(ctx.exception),
            "grande.txt supera el límite de 2 MB para documentos de texto.",
        )

    def test_unsupported_extension_message(self):
        with self.assertRaises(ValueError) as ctx:
            attachments.extract(self.path("datos.xlsx"))
        self.assertEqual(
            str(ctx.exception), "Tipo de archivo no compatible: .xlsx"
        )

    def test_legacy_doc_and_ppt_are_not_supported(self):
        for name in ("viejo.doc", "viejo.ppt"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError) as ctx:
                    attachments.extract(self.path(name))
                self.assertEqual(
                    str(ctx.exception),
                    "Los archivos .doc y .ppt antiguos ya no se admiten; "
                    "convertilos a .docx o .pptx.",
                )


class TestImageAttachment(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.list = []

    def path(self, name, data=b"png"):
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def test_image_attached_without_content(self):
        attachment = attachments.add_attachment(self.list, self.path("foto.png"))
        self.assertEqual(attachment.kind, Kind.IMAGE)
        self.assertEqual(attachment.content, "")

    def test_maximum_three_images(self):
        for index in range(3):
            attachments.add_attachment(self.list, self.path(f"foto{index}.png"))
        with self.assertRaises(ValueError) as ctx:
            attachments.add_attachment(self.list, self.path("foto3.png"))
        self.assertEqual(
            str(ctx.exception), "Se admiten como máximo tres imágenes por solicitud."
        )

    def test_image_total_size_limit(self):
        original = attachments.IMAGE_TOTAL_LIMIT
        attachments.IMAGE_TOTAL_LIMIT = 10
        try:
            attachments.add_attachment(self.list, self.path("a.png", b"x" * 6))
            with self.assertRaises(ValueError) as ctx:
                attachments.add_attachment(self.list, self.path("b.png", b"x" * 6))
            self.assertEqual(
                str(ctx.exception),
                "Las imágenes superan el límite seguro de 14 MB para una "
                "solicitud codificada.",
            )
        finally:
            attachments.IMAGE_TOTAL_LIMIT = original

    def test_duplicate_path_is_skipped_silently(self):
        path = self.path("foto.png")
        attachments.add_attachment(self.list, path)
        self.assertIsNone(attachments.add_attachment(self.list, path))
        self.assertEqual(len(self.list), 1)


class TestDocxExtraction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def test_docx_paragraphs_joined_with_newlines(self):
        path = self.path("doc.docx")
        make_docx(path, ["primer párrafo", "segundo párrafo"])
        attachment = attachments.extract(path)
        self.assertEqual(attachment.kind, Kind.DOCX)
        self.assertEqual(attachment.content, "primer párrafo\nsegundo párrafo")

    def test_docx_tab_and_break_preserved(self):
        path = self.path("doc.docx")
        xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{attachments.W_NS}"><w:body>'
            "<w:p><w:r><w:t>a</w:t></w:r><w:tab/><w:r><w:t>b</w:t></w:r>"
            "<w:br/><w:r><w:t>c</w:t></w:r></w:p>"
            "</w:body></w:document>"
        )
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("word/document.xml", xml)
        attachment = attachments.extract(path)
        self.assertEqual(attachment.content, "a\tb\nc")

    def test_invalid_docx_message(self):
        path = self.path("doc.docx")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("otro.xml", "<x/>")
        with self.assertRaises(ValueError) as ctx:
            attachments.extract(path)
        self.assertEqual(
            str(ctx.exception), "El archivo no es un documento de Word válido."
        )

    def test_empty_docx_message(self):
        path = self.path("doc.docx")
        make_docx(path, ["  "])
        with self.assertRaises(ValueError) as ctx:
            attachments.extract(path)
        self.assertEqual(
            str(ctx.exception), "No se encontró texto en doc.docx."
        )

    def test_long_document_truncated(self):
        path = self.path("doc.docx")
        make_docx(path, ["x" * (attachments.DOCUMENT_TEXT_LIMIT + 50)])
        attachment = attachments.extract(path)
        # Legacy: text.Substring(0, limit) + "\n\n[Documento recortado: ...]"
        self.assertEqual(attachment.content[:attachments.DOCUMENT_TEXT_LIMIT], "x" * attachments.DOCUMENT_TEXT_LIMIT)
        self.assertTrue(attachment.content.endswith(
            f"[Documento recortado: supera {attachments.DOCUMENT_TEXT_LIMIT} caracteres.]"
        ))


class TestPptxExtraction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def test_two_slides_with_dividers(self):
        path = self.path("deck.pptx")
        make_pptx(path, [(1, ["Título uno", "detalle"]), (2, ["Título dos"])])
        attachment = attachments.extract(path)
        self.assertEqual(attachment.kind, Kind.PPTX)
        self.assertEqual(
            attachment.content,
            "--- Diapositiva 1 ---\nTítulo uno\ndetalle\n\n"
            "--- Diapositiva 2 ---\nTítulo dos",
        )

    def test_slides_sorted_numerically_not_lexically(self):
        path = self.path("deck.pptx")
        make_pptx(path, [(2, ["en slide2"]), (10, ["en slide10"])])
        attachment = attachments.extract(path)
        self.assertLess(
            attachment.content.index("en slide2"),
            attachment.content.index("en slide10"),
        )

    def test_invalid_pptx_message(self):
        path = self.path("deck.pptx")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("ppt/otro.xml", "<x/>")
        with self.assertRaises(ValueError) as ctx:
            attachments.extract(path)
        self.assertEqual(
            str(ctx.exception),
            "El archivo no es una presentación de PowerPoint válida.",
        )


@unittest.skipUnless(HAS_PYMUPDF, "pymupdf is not installed")
class TestPdfExtraction(unittest.TestCase):
    def setUp(self):
        import pymupdf
        self.pymupdf = pymupdf
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def test_one_page_pdf_extracts_text(self):
        path = self.path("doc.pdf")
        doc = self.pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Hola PDF")
        doc.save(path)
        doc.close()
        attachment = attachments.extract(path)
        self.assertEqual(attachment.kind, Kind.PDF)
        self.assertIn("Hola PDF", attachment.content)
        self.assertIn("--- Página 1 ---", attachment.content)

    def test_scanned_pdf_message(self):
        path = self.path("scan.pdf")
        doc = self.pymupdf.open()
        doc.new_page()  # no text: the page is a blank/scanned page
        doc.save(path)
        doc.close()
        with self.assertRaises(ValueError) as ctx:
            attachments.extract(path)
        self.assertEqual(
            str(ctx.exception),
            "El PDF no tiene texto seleccionable (parece escaneado).",
        )


if __name__ == "__main__":
    unittest.main()
