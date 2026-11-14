"""Exports (T6/S1): PDF and MP3 of what Vista previa shows.

Pure, cross-platform and deterministic. Legacy reference: txt.ps1
Export-PreviewPdf / Export-SpeechMp3 (4645-4790), Get-PrintHtml (5189)
and Convert-MarkdownToText (5945).

- The PDF used to be printed by headless msedge.exe; the new app renders it
  with PyMuPDF (pymupdf.Story, falling back to a plain-text layout), so it
  needs neither Edge nor the network and behaves identically on Windows
  and macOS.
- The MP3 used to run `python -m edge_tts ...` directly, the same CLI the
  legacy app used; on macOS Python 3.14 that subprocess builds its SSL
  context from the certifi bundle and fails (S17: "Basic Constraints of CA
  cert not marked critical"), so the MP3 now runs app/edge_tts_export.py,
  a wrapper that injects the native system trust (truststore) BEFORE
  importing edge_tts. Certificate verification is never disabled
  (S6: Edge-only; System.Speech is dropped).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from html import unescape
from pathlib import Path

from .markdown import render_markdown

# Legacy Show-Message / error strings mirrored from txt.ps1 4645-4790.
MSG_PDF_EMPTY = "No hay contenido para exportar a PDF."
MSG_MP3_EMPTY = "No hay contenido para exportar a MP3."
MSG_NO_PYTHON = "No se encontró Python para generar el MP3 con la voz Edge."

# Legacy @page margins: 22mm 20mm 24mm 20mm (A4).
_MM = 2.834645669
PAGE_WIDTH = 595.2756   # A4 portrait, points
PAGE_HEIGHT = 841.8898
MARGIN_LEFT = 20 * _MM
MARGIN_RIGHT = 20 * _MM
MARGIN_TOP = 22 * _MM
MARGIN_BOTTOM = 24 * _MM

# Legacy Get-PrintHtml palette: always the light theme
# ("siempre en fondo blanco"), taken from $themePalettes.Light.
_PRINT_COLORS = {
    "text": "#161A26",
    "muted": "#5E667A",
    "heading": "#0F1220",
    "border": "#DCE0EA",
    "code": "#F3F4F8",
    "accent": "#5056E0",
    "link": "#4248D6",
}

_PAGE_CSS = """\
@page {
    size: A4;
    margin: 22mm 20mm 24mm 20mm;
    @bottom-right {
        content: "Página " counter(page) " de " counter(pages);
        color: %(muted)s;
        font-family: "Segoe UI", Arial, sans-serif;
        font-size: 8pt;
    }
}
""" % _PRINT_COLORS

# Body rules without the @page block: pymupdf.Story evaluates what it
# supports and ignores the rest, but a stray @page keeps it from laying
# the document out at all.
_BODY_CSS = """\
html, body { background: #FFFFFF; }
body { color: %(text)s; font-family: "Segoe UI", Arial, sans-serif; font-size: 10.5pt; line-height: 1.55; margin: 0; }
h1, h2, h3, h4 { color: %(heading)s; font-weight: 600; line-height: 1.25; }
h1 { border-bottom: 1.5pt solid %(accent)s; font-size: 22pt; margin: 0 0 14pt; padding-bottom: 6pt; }
h2 { border-bottom: 0.6pt solid %(border)s; font-size: 15pt; margin: 20pt 0 8pt; padding-bottom: 3pt; }
h3 { font-size: 12.5pt; margin: 16pt 0 6pt; }
h4 { font-size: 11pt; margin: 14pt 0 4pt; }
p { margin: 0 0 8pt; }
ul, ol { margin: 0 0 8pt; padding-left: 16pt; }
li { margin: 2pt 0; }
strong { color: %(heading)s; font-weight: 600; }
a { color: %(link)s; text-decoration: none; }
code { background: %(code)s; border: 0.5pt solid %(border)s; font-family: monospace; font-size: 8.8pt; }
pre { background: %(code)s; border: 0.6pt solid %(border)s; font-size: 8.8pt; line-height: 1.45; margin: 0 0 10pt; padding: 8pt 10pt; white-space: pre-wrap; }
blockquote { background: %(code)s; border-left: 2.5pt solid %(accent)s; color: %(muted)s; margin: 10pt 0; padding: 6pt 10pt; }
table { border-collapse: collapse; font-size: 9.5pt; margin: 0 0 10pt; width: 100%%; }
th { background: %(code)s; color: %(heading)s; font-weight: 600; }
th, td { border: 0.5pt solid %(border)s; padding: 4pt 7pt; }
img { max-width: 100%%; }
hr { border: 0; border-top: 0.6pt solid %(border)s; margin: 14pt 0; }
""" % _PRINT_COLORS


def build_print_html(markdown_text: str) -> str:
    """Complete HTML document for PDF printing (legacy Get-PrintHtml).

    Always the light theme on a white background, A4 with print margins and
    page numbers through CSS counters where the renderer supports them; the
    sanitized rendered markdown goes in the body. Citation markers are
    expected to be stripped by the caller (txt_core.citations).
    """
    body_html = render_markdown(markdown_text)
    return (
        "<!doctype html>\n<html lang=\"es\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<style>\n" + _PAGE_CSS + _BODY_CSS + "</style>\n</head>\n<body>\n"
        + body_html + "\n</body>\n</html>\n"
    )


def markdown_to_text(markdown_text: str) -> str:
    """Plain text of a markdown document (legacy Convert-MarkdownToText).

    Renders the same sanitized HTML as Vista previa, turns block closings
    into newlines, strips tags and unescapes entities.
    """
    html = render_markdown(markdown_text)
    if not html:
        return ""
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</(p|h[1-6]|li|pre|tr|blockquote)>", "\n", html)
    plain = re.sub(r"<[^>]+>", "", html)
    return unescape(plain).strip()


def export_pdf(markdown_text: str, output_path: str) -> str:
    """Write markdown_text as a paginated PDF at output_path.

    Tries pymupdf.Story first (HTML/CSS layout) and falls back to a
    hand-paginated text layout. Returns output_path; raises RuntimeError
    with a legacy-style Spanish message when nothing works.
    """
    try:
        buffer = _pdf_bytes_with_story(markdown_text)
    except Exception as error:  # noqa: BLE001 - any Story failure falls back
        try:
            buffer = _pdf_bytes_text_fallback(markdown_text)
        except Exception as fallback_error:  # noqa: BLE001
            raise RuntimeError(
                f"No se pudo generar el PDF: {fallback_error or error}"
            ) from fallback_error
    _write_pdf(buffer, output_path)
    return output_path


def _pdf_bytes_with_story(markdown_text: str) -> bytes:
    import io

    import pymupdf

    story = pymupdf.Story(
        html=render_markdown(markdown_text), user_css=_BODY_CSS,
    )
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    mediabox = pymupdf.paper_rect("a4")
    where = mediabox + (MARGIN_LEFT, MARGIN_TOP, -MARGIN_RIGHT, -MARGIN_BOTTOM)
    more = 1
    while more:
        device = writer.begin_page(mediabox)
        more, _filled = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()
    story = None
    writer = None
    return buffer.getvalue()


def _pdf_bytes_text_fallback(markdown_text: str) -> bytes:
    """Text-only layout: wrap markdown_to_text lines into A4 pages."""
    import io

    import pymupdf

    text = markdown_to_text(markdown_text)
    font = pymupdf.Font("helv")
    font_size = 10.5
    line_height = font_size * 1.55
    content_width = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT
    content_height = PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM

    lines: list[str] = []
    for source_line in text.splitlines() or [""]:
        words = source_line.split(" ")
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if candidate and font.text_length(candidate, font_size) > content_width:
                if current:
                    lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)

    doc = pymupdf.open()
    y = MARGIN_TOP
    page = None
    for line in lines:
        if page is None or y + line_height > MARGIN_TOP + content_height:
            if page is not None:
                page.insert_text((MARGIN_LEFT, y), "", fontsize=font_size)
            page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            y = MARGIN_TOP
        page.insert_text((MARGIN_LEFT, y + font_size), line, fontname="helv",
                         fontsize=font_size, color=_pdf_color("text"))
        y += line_height
    buffer = io.BytesIO()
    doc.save(buffer, garbage=3, deflate=True)
    doc.close()
    return buffer.getvalue()


def _pdf_color(name: str) -> tuple[float, float, float]:
    value = _PRINT_COLORS[name].lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _write_pdf(buffer: bytes, output_path: str) -> None:
    import pymupdf

    doc = pymupdf.open(stream=buffer, filetype="pdf")
    try:
        _add_page_numbers(doc)
        doc.save(output_path, garbage=3, deflate=True)
    finally:
        doc.close()


def _add_page_numbers(doc) -> None:
    """Legacy @bottom-right counter: "Página X de Y" in 8pt muted text.

    PyMuPDF does not evaluate CSS counters, so the footer is drawn here on
    every page, bottom-right inside the print margins.
    """
    import pymupdf

    total = doc.page_count
    for index, page in enumerate(doc, start=1):
        footer = f"Página {index} de {total}"
        rect = pymupdf.Rect(
            PAGE_WIDTH - MARGIN_RIGHT - 120,
            PAGE_HEIGHT - MARGIN_BOTTOM + MARGIN_TOP - 14,
            PAGE_WIDTH - MARGIN_RIGHT,
            PAGE_HEIGHT - MARGIN_BOTTOM + MARGIN_TOP,
        )
        page.insert_textbox(rect, footer, fontsize=8, fontname="helv",
                            color=_pdf_color("muted"), align=pymupdf.TEXT_ALIGN_RIGHT)


def find_python_command(*names: str) -> str | None:
    """Engine's _find_command pattern: first available executable."""
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


# S17/T24: MP3 synthesis goes through the repository wrapper (next to the
# app package), never `python -m edge_tts`, so the subprocess uses the
# same native system TLS trust as the app itself.
EDGE_TTS_EXPORT_SCRIPT = (Path(__file__).resolve().parents[2]
                          / "app" / "edge_tts_export.py")


def export_mp3(
    text: str,
    output_path: str,
    voice_name: str,
    rate_percent: int,
    python_command: str | None = None,
    runner=None,
) -> str:
    """Read text aloud into an MP3 via the Edge truststore wrapper (S17/T24).

    Runs `python app/edge_tts_export.py --voice <voice> --rate <rate-100>
    --text-file <tmp> --media-file <output>` with the engine's
    python_command discovery pattern; the wrapper injects the native
    system TLS trust before importing edge_tts. The temp text file is
    always deleted. Returns output_path and raises RuntimeError with
    legacy-style Spanish messages on failure.
    """
    if python_command is None:
        python_command = find_python_command("python", "python3")
    if not python_command:
        raise RuntimeError(MSG_NO_PYTHON)
    text_file = None
    try:
        handle_fd, text_file = tempfile.mkstemp(prefix="txt-mp3-", suffix=".txt")
        with os.fdopen(handle_fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        argv = [
            python_command, str(EDGE_TTS_EXPORT_SCRIPT),
            "--voice", voice_name,
            "--rate", str(rate_percent - 100),
            "--text-file", text_file,
            "--media-file", output_path,
        ]
        run = runner or subprocess.run
        result = run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        error_text = ""
        stderr = getattr(result, "stderr", None)
        if stderr:
            error_text = (stderr if isinstance(stderr, str) else
                          stderr.decode("utf-8", errors="replace")).strip()
        exit_code = getattr(result, "returncode", -1)
        if (exit_code == 0 and os.path.isfile(output_path)
                and os.path.getsize(output_path) > 0):
            return output_path
        detail = (error_text.splitlines()[-1] if error_text
                  else f"El proceso terminó con código {exit_code}.")
        raise RuntimeError(f"No se pudo generar el MP3: {detail}")
    finally:
        if text_file:
            _remove_file(text_file)


def _remove_file(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
