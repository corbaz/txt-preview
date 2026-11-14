"""WSGI app that serves the UI (app/www) to the pywebview window.

pywebview's built-in static server loses its no-cache headers, so the web
view kept an old index.html after an update (new JS against old HTML broke
the UI). This app sends `Cache-Control: no-store` on everything and stamps
the asset URLs of index.html with their modification time, so files already
cached under the old URLs are never reused.
"""
from __future__ import annotations

import mimetypes
import os
import re
from pathlib import Path

INDEX_NAME = "index.html"
_ASSET_REF = re.compile(r'(?P<attr>\b(?:src|href)=")(?P<path>(?:css|js)/[^"?#]+)(?P<end>")')
_NO_STORE = [("Cache-Control", "no-store"), ("Pragma", "no-cache"), ("Expires", "0")]


def stamped_index(root: Path) -> bytes:
    """index.html with `?v=<mtime>` on its local css/js references."""
    html = (root / INDEX_NAME).read_text(encoding="utf-8")

    def stamp(match: re.Match) -> str:
        asset = root / match.group("path")
        version = int(asset.stat().st_mtime) if asset.is_file() else 0
        return f'{match.group("attr")}{match.group("path")}?v={version}{match.group("end")}'

    return _ASSET_REF.sub(stamp, html).encode("utf-8")


def create_wsgi_app(root: str | os.PathLike):
    root_path = Path(root).resolve()

    def respond(start_response, status: str, body: bytes, content_type: str):
        start_response(status, [("Content-Type", content_type),
                                ("Content-Length", str(len(body))), *_NO_STORE])
        return [body]

    def app(environ, start_response):
        relative = (environ.get("PATH_INFO") or "/").lstrip("/")
        if relative in ("", INDEX_NAME):
            return respond(start_response, "200 OK", stamped_index(root_path),
                           "text/html; charset=utf-8")
        target = (root_path / relative).resolve()
        if root_path not in target.parents or not target.is_file():
            return respond(start_response, "404 Not Found", b"Not found",
                           "text/plain; charset=utf-8")
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type.endswith("javascript"):
            content_type += "; charset=utf-8"
        return respond(start_response, "200 OK", target.read_bytes(), content_type)

    return app
