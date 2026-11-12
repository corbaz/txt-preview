"""TXT Preview — cross-platform entry point.

Runs the same application on Windows (WebView2) and macOS (WKWebView)
through pywebview. Legacy Windows-only app: ../txt.ps1.
"""
from __future__ import annotations

import sys
from pathlib import Path

import webview

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
WWW = ROOT / "www"

VERSION_FILE = REPO / "VERSION"


def read_version() -> str:
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    return "dev"


class Api:
    """Bridge exposed to the frontend as window.pywebview.api."""

    def app_version(self) -> str:
        return read_version()

    def platform(self) -> str:
        return sys.platform


def create_app() -> None:
    window = webview.create_window(
        "TXT Preview",
        str(WWW / "index.html"),
        js_api=Api(),
        width=1100,
        height=760,
        min_size=(720, 480),
    )
    webview.start(private_mode=False)


if __name__ == "__main__":
    create_app()
