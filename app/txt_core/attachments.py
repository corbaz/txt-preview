"""Attachment extraction for the AI actions, ported from txt.ps1 regions
5745-5940 (document extractors) and 6020-6180 (attachments add/limits).

Pure, cross-platform, stdlib-first: text files and OpenXML documents
(.docx/.pptx are ZIP packages of XML, no Office installation or COM needed);
PDFs go through PyMuPDF, the optional dependency from requirements.txt.

Decision recorded against the legacy app: binary .doc/.ppt files are NOT
supported here. The legacy app read them through an installed Microsoft Office
via COM, which is Windows-only, so the cross-platform app rejects them with a
clear conversion message instead.
"""
from __future__ import annotations

import os
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass

TEXT_FILE_LIMIT = 2 * 1024 * 1024          # legacy 2MB for plain text documents
DOCUMENT_FILE_LIMIT = 50 * 1024 * 1024     # legacy 50MB before reading a document
DOCUMENT_TEXT_LIMIT = 300000               # legacy documentTextLimit (~100k tokens)
MAX_IMAGES = 3                             # legacy: three images per request
IMAGE_TOTAL_LIMIT = 14 * 1024 * 1024       # legacy 14MB for all images combined

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
TEXT_EXTENSIONS = (
    ".txt", ".md", ".json", ".csv", ".xml", ".html", ".htm",
    ".ps1", ".py", ".js", ".ts", ".yaml", ".yml",
)
DOCUMENT_EXTENSIONS = (".pdf", ".docx", ".pptx")
LEGACY_OFFICE_EXTENSIONS = (".doc", ".ppt")  # not supported in the new app

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"

ERR_LEGACY_OFFICE = (
    "Los archivos .doc y .ppt antiguos ya no se admiten; convertilos a .docx o .pptx."
)
ERR_PYMUPDF_MISSING = (
    "Falta la librería PyMuPDF para leer archivos PDF; "
    "instalala con: python -m pip install --user pymupdf"
)


class Kind:
    TEXT = "Text"
    IMAGE = "Image"
    PDF = "Pdf"
    DOCX = "Docx"
    PPTX = "Pptx"


@dataclass
class Attachment:
    kind: str
    name: str
    path: str
    content: str = ""


def attachment_summary(names, provider_label: str) -> str:
    """Legacy Update-AttachmentSummary wording for the UI label."""
    if not names:
        return "Sin archivos adjuntos para la próxima solicitud"
    joined = ", ".join(names)
    return f"Se enviarán a {provider_label} ({len(names)}): {joined}"


def add_attachment(attachments: list[Attachment], path: str) -> Attachment | None:
    """Legacy add loop rules; returns None when the path is already attached."""
    normalized = os.path.abspath(path)
    for existing in attachments:
        if os.path.abspath(existing.path) == normalized:
            return None  # the legacy loop silently skips duplicates
    attachment = extract(path)
    if attachment.kind == Kind.IMAGE:
        images = [item for item in attachments if item.kind == Kind.IMAGE]
        if len(images) >= MAX_IMAGES:
            raise ValueError("Se admiten como máximo tres imágenes por solicitud.")
        total = sum(os.path.getsize(item.path) for item in images)
        total += os.path.getsize(path)
        if total > IMAGE_TOTAL_LIMIT:
            raise ValueError(
                "Las imágenes superan el límite seguro de 14 MB "
                "para una solicitud codificada."
            )
    attachments.append(attachment)
    return attachment


def extract(path: str) -> Attachment:
    """Build an Attachment from a file path, raising ValueError with the
    legacy Spanish messages on any rejection."""
    extension = os.path.splitext(path)[1].lower()
    name = os.path.basename(path)
    if extension in LEGACY_OFFICE_EXTENSIONS:
        raise ValueError(ERR_LEGACY_OFFICE)
    if extension in IMAGE_EXTENSIONS:
        return Attachment(Kind.IMAGE, name, path)
    if extension in TEXT_EXTENSIONS:
        return _text_attachment(path, name)
    if extension in DOCUMENT_EXTENSIONS:
        return _document_attachment(path, name, extension)
    raise ValueError(f"Tipo de archivo no compatible: {extension}")


def _text_attachment(path: str, name: str) -> Attachment:
    if os.path.getsize(path) > TEXT_FILE_LIMIT:
        raise ValueError(f"{name} supera el límite de 2 MB para documentos de texto.")
    with open(path, encoding="utf-8", errors="replace") as handle:
        content = handle.read()
    return Attachment(Kind.TEXT, name, path, content)


def _document_attachment(path: str, name: str, extension: str) -> Attachment:
    if os.path.getsize(path) > DOCUMENT_FILE_LIMIT:
        raise ValueError(f"{name} supera el límite de 50 MB para documentos.")
    if extension == ".pdf":
        content = _extract_pdf(path)
    elif extension == ".docx":
        content = _join_paragraphs(_extract_docx(path))
    else:
        content = _extract_pptx(path)
    if not content.strip():
        raise ValueError(f"No se encontró texto en {name}.")
    if len(content) > DOCUMENT_TEXT_LIMIT:
        content = (
            content[:DOCUMENT_TEXT_LIMIT]
            + f"\n\n[Documento recortado: supera {DOCUMENT_TEXT_LIMIT} caracteres.]"
        )
    kind = {".pdf": Kind.PDF, ".docx": Kind.DOCX, ".pptx": Kind.PPTX}[extension]
    return Attachment(kind, name, path, content)


def _extract_pdf(path: str) -> str:
    try:
        import pymupdf
    except ImportError as error:
        raise ValueError(ERR_PYMUPDF_MISSING) from error
    document = pymupdf.open(path)
    try:
        pages = [
            f"--- Página {page.number + 1} ---\n{page.get_text('text')}"
            for page in document
        ]
    finally:
        document.close()
    text = "\n\n".join(pages)
    if not re.sub(r"--- Página \d+ ---", "", text).strip():
        raise ValueError("El PDF no tiene texto seleccionable (parece escaneado).")
    return text


def _openxml_paragraphs(root: ET.Element, namespace: str) -> list[str]:
    """Legacy Get-OpenXmlParagraphs: one string per w:p/a:p, in document order,
    keeping tabs and line breaks."""
    paragraphs = []
    for paragraph in root.iter(f"{{{namespace}}}p"):
        parts = []
        for node in paragraph.iter():
            local = node.tag.rsplit("}", 1)[-1]
            if local == "t":
                parts.append(node.text or "")
            elif local == "tab":
                parts.append("\t")
            elif local == "br":
                parts.append("\n")
        paragraphs.append("".join(parts))
    return paragraphs


def _zip_xml(zip_file: zipfile.ZipFile, entry_name: str) -> ET.Element:
    with zip_file.open(entry_name) as handle:
        return ET.parse(handle).getroot()


def _extract_docx(path: str) -> list[str]:
    """Word text: word/document.xml paragraphs joined with newlines."""
    with zipfile.ZipFile(path) as package:
        try:
            root = _zip_xml(package, "word/document.xml")
        except (KeyError, ET.ParseError) as error:
            raise ValueError("El archivo no es un documento de Word válido.") from error
        return _openxml_paragraphs(root, W_NS)


def _extract_pptx(path: str) -> str:
    """PowerPoint text: slides in numeric order with legacy dividers."""
    with zipfile.ZipFile(path) as package:
        slides = sorted(
            (name for name in package.namelist()
             if re.fullmatch(r"ppt/slides/slide(\d+)\.xml", name)),
            key=lambda name: int(re.search(r"(\d+)\.xml$", name).group(1)),
        )
        if not slides:
            raise ValueError("El archivo no es una presentación de PowerPoint válida.")
        sections = []
        for slide_number, slide_name in enumerate(slides, start=1):
            root = _zip_xml(package, slide_name)
            lines = [
                line for line in _openxml_paragraphs(root, A_NS)
                if line.strip()
            ]
            sections.append(f"--- Diapositiva {slide_number} ---\n" + "\n".join(lines))
    return "\n\n".join(sections)


def _join_paragraphs(paragraphs: list[str]) -> str:
    return "\n".join(paragraphs)
