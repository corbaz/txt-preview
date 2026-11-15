"""«Copiar Teams»: the preview content as rich text for a Microsoft Teams chat.

Teams drops style sheets, classes and most block styling of pasted HTML
(a real paste lost the heading color and the header-cell background), but
its own editor writes text color as `<span style="color:...">`. So the
sanitized preview HTML gets bordered tables plus colored text in spans for
headings and table headers, code blocks, quotes and images.
Local images are embedded as data URLs, because a chat cannot read a file
path; web images keep their address. The colors are fixed and readable on
both the light and the dark Teams theme.
"""
from __future__ import annotations

import base64
import os
import re
import urllib.parse

from .markdown import render_markdown

TEAMS_ACCENT = "#5B5FC7"
TEXT_ACCENT = "#7579EB"  # readable on the light and the dark Teams theme
_HEADING = "font-weight:600;margin:12px 0 6px"
_CELL = "border:1px solid #8A8A8A;padding:6px 10px"
_CODE = "font-family:Consolas,'Courier New',monospace;background-color:#F0F0F0;color:#242424"

INLINE_STYLES = {
    "h1": f"font-size:22px;{_HEADING}",
    "h2": f"font-size:19px;{_HEADING}",
    "h3": f"font-size:16px;{_HEADING}",
    "h4": f"font-size:14px;{_HEADING}",
    "h5": f"font-size:13px;{_HEADING}",
    "h6": f"font-size:12px;{_HEADING}",
    "table": "border-collapse:collapse;margin:8px 0",
    "th": f"{_CELL};text-align:left",
    "td": _CELL,
    "pre": f"{_CODE};padding:8px 10px;margin:8px 0;white-space:pre-wrap",
    "code": f"{_CODE};padding:1px 4px",
    "blockquote": f"border-left:4px solid {TEAMS_ACCENT};margin:8px 0;padding:2px 10px",
    "img": "max-width:100%",
    "a": "text-decoration:underline",
}

# Tags whose text is colored with an inner span, the form Teams itself keeps.
_COLORED_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6", "th")
_COLOR_SPAN = f'<span style="color:{TEXT_ACCENT}">'

_OPEN_TAG = re.compile(r"<(?P<tag>[a-z][a-z0-9]*)(?P<rest>(?:\s[^<>]*)?)>")
_IMG_SRC = re.compile(r'(<img\b[^<>]*?\bsrc=")(?P<src>[^"]*)(")')
_IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp"}


def _add_inline_styles(html: str) -> str:
    in_pre = False

    def styled(match: re.Match) -> str:
        nonlocal in_pre
        tag = match.group("tag")
        style = INLINE_STYLES.get(tag)
        if tag == "pre":
            in_pre = True
        elif tag == "code" and in_pre:
            in_pre = False
            style = None  # the surrounding <pre> already carries the block style
        if not style:
            return match.group(0)
        opened = f'<{tag} style="{style}"{match.group("rest")}>'
        return opened + _COLOR_SPAN if tag in _COLORED_TAGS else opened

    html = _OPEN_TAG.sub(styled, html)
    return re.sub(r"</(%s)>" % "|".join(_COLORED_TAGS), r"</span></\1>", html)


def _embed_local_images(html: str) -> str:
    """A local image path becomes a data URL; unreadable ones stay as they are."""

    def embed(match: re.Match) -> str:
        source = match.group("src")
        if re.match(r"(?i)^(https?:|data:)", source):
            return match.group(0)
        path = urllib.parse.unquote(re.sub(r"(?i)^file:/{2,3}", "", source))
        media_type = _IMAGE_TYPES.get(os.path.splitext(path)[1].lower())
        if not media_type or not os.path.isfile(path):
            return match.group(0)
        try:
            with open(path, "rb") as handle:
                data = base64.b64encode(handle.read()).decode("ascii")
        except OSError:
            return match.group(0)
        return f"{match.group(1)}data:{media_type};base64,{data}{match.group(3)}"

    return _IMG_SRC.sub(embed, html)


_MERMAID_BLOCK = re.compile(
    r'<pre><code class="language-mermaid">.*?</code></pre>', re.DOTALL)


def _embed_diagrams(html: str, diagrams) -> str:
    """Each Mermaid block becomes the picture the preview drew for it (a
    chat cannot draw the code); a block without a picture stays as code."""
    pictures = [picture for picture in (diagrams or [])]

    def picture_for(match: re.Match) -> str:
        if not pictures:
            return match.group(0)
        source = pictures.pop(0)
        if not isinstance(source, str) or not source.startswith("data:image/png;base64,"):
            return match.group(0)
        return f'<p><img src="{source}" alt="Diagrama de flujo"/></p>'

    return _MERMAID_BLOCK.sub(picture_for, html)


def teams_html(markdown_text: str, diagrams=None) -> str:
    """HTML fragment of the preview content with Teams-ready inline styles.
    `diagrams` are the PNG data URLs of the drawn Mermaid blocks, in order."""
    html = _embed_diagrams(render_markdown(markdown_text), diagrams)
    return _add_inline_styles(_embed_local_images(html))


def cf_html(fragment: str) -> str:
    """Windows "HTML Format" clipboard payload: a header with the byte offsets
    (UTF-8) of the document and of the fragment inside it."""
    prefix = "<html><body><!--StartFragment-->"
    suffix = "<!--EndFragment--></body></html>"
    header = ("Version:0.9\r\nStartHTML:{:010d}\r\nEndHTML:{:010d}\r\n"
              "StartFragment:{:010d}\r\nEndFragment:{:010d}\r\n")
    start_html = len(header.format(0, 0, 0, 0).encode("utf-8"))
    start_fragment = start_html + len(prefix.encode("utf-8"))
    end_fragment = start_fragment + len(fragment.encode("utf-8"))
    end_html = end_fragment + len(suffix.encode("utf-8"))
    return (header.format(start_html, end_html, start_fragment, end_fragment)
            + prefix + fragment + suffix)
