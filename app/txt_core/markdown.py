"""Markdown -> sanitized HTML rendering for Vista previa.

Uses the pure-Python `markdown` package so Windows and macOS produce the
same output, then neutralizes any raw HTML the source may carry (AI answers
must never inject markup or script into the preview).

Citation markers are expected to be stripped beforehand (txt_core.citations).
"""
from __future__ import annotations

import re

import markdown as _markdown
from html.parser import HTMLParser

_EXTENSIONS = ("fenced_code", "tables", "sane_lists", "nl2br")

_ALLOWED_TAGS = frozenset({
    "p", "br", "hr",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "strong", "em", "del", "code", "pre",
    "ul", "ol", "li",
    "a", "img",
    "blockquote",
    "table", "thead", "tbody", "tr", "td", "th",
    "span",
})

_ALLOWED_ATTRS = frozenset({"href", "src", "alt", "title"})

_VOID_TAGS = frozenset({"br", "hr", "img"})

# Block out event handlers and javascript URLs in one sweep.
_DANGEROUS_ATTR = re.compile(r"^(on[a-z]+|javascript:)", re.IGNORECASE)


class _Sanitizer(HTMLParser):
    """Rewrites an HTML fragment keeping only allowlisted tags/attributes.

    Disallowed tags are emitted escaped (as visible text), never dropped, so
    the reader still sees the content the model produced.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.open_tags: list[str] = []

    def _emit_attr(self, name: str, value: str | None) -> str:
        if _DANGEROUS_ATTR.match(name) or name not in _ALLOWED_ATTRS:
            return ""
        if value is None:
            return f" {name}"
        escaped = value.replace("&", "&amp;").replace('"', "&quot;")
        return f' {name}="{escaped}"'

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _ALLOWED_TAGS:
            rendered = "".join(self._emit_attr(name, value) for name, value in attrs)
            self.out.append(f"<{tag}{rendered}>")
            if tag not in _VOID_TAGS:
                self.open_tags.append(tag)
        else:
            self.out.append(f"&lt;{tag}&gt;")

    def handle_endtag(self, tag: str) -> None:
        if tag in _ALLOWED_TAGS and tag in self.open_tags:
            # Close through the stack so fragments stay well-formed.
            while self.open_tags:
                open_tag = self.open_tags.pop()
                self.out.append(f"</{open_tag}>")
                if open_tag == tag:
                    break
        elif tag not in _ALLOWED_TAGS:
            self.out.append(f"&lt;/{tag}&gt;")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _ALLOWED_TAGS:
            rendered = "".join(self._emit_attr(name, value) for name, value in attrs)
            self.out.append(f"<{tag}{rendered}/>")
        else:
            self.out.append(f"&lt;{tag}/&gt;")

    def handle_data(self, data: str) -> None:
        self.out.append(data.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    def close(self) -> None:
        super().close()
        while self.open_tags:
            self.out.append(f"</{self.open_tags.pop()}>")


def _sanitize_html(html: str) -> str:
    sanitizer = _Sanitizer()
    sanitizer.feed(html)
    sanitizer.close()
    return "".join(sanitizer.out)


def render_markdown(text: str) -> str:
    """Render markdown text to a sanitized HTML body fragment."""
    if not text:
        return ""
    rendered = _markdown.markdown(text, extensions=_EXTENSIONS)
    return _sanitize_html(rendered)
