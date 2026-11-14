"""Navegador tab (txt.ps1 parity): address conversion, the Api bridge over an
injected backend and the static UI contract. No native web view is created."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from txt_core import browser

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "www" / "index.html").read_text(encoding="utf-8")
MAIN_JS = (ROOT / "www" / "js" / "main.js").read_text(encoding="utf-8")


class FakeBackend:
    def __init__(self):
        self.calls = []

    def navigate(self, url):
        self.calls.append(("navigate", url))

    def back(self):
        self.calls.append(("back",))

    def forward(self):
        self.calls.append(("forward",))

    def place(self, rect, visible):
        self.calls.append(("place", rect, visible))


class TestToBrowserUrl(unittest.TestCase):
    def test_full_urls_are_kept(self):
        self.assertEqual(browser.to_browser_url(" https://example.com/a?b=1 "),
                         "https://example.com/a?b=1")
        self.assertEqual(browser.to_browser_url("http://example.com"), "http://example.com")

    def test_bare_domain_gets_https(self):
        self.assertEqual(browser.to_browser_url("example.com/docs"), "https://example.com/docs")

    def test_plain_words_are_searched_on_google(self):
        self.assertEqual(browser.to_browser_url("clima córdoba"),
                         "https://www.google.com/search?q=clima%20c%C3%B3rdoba")
        self.assertEqual(browser.to_browser_url("python"),
                         "https://www.google.com/search?q=python")

    def test_empty_address(self):
        self.assertEqual(browser.to_browser_url("   "), "")

    def test_bounds_scale_with_host_width(self):
        rect = {"x": 10, "y": 100, "width": 500, "height": 300, "inner_width": 1000}
        self.assertEqual(browser._scaled_bounds(rect, 1500), (15, 150, 750, 450))
        self.assertEqual(browser._scaled_bounds(rect, 1000), (10, 100, 500, 300))


class TestBrowserApi(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.api = main.Api(settings_dir=self._dir.name)
        self.backend = FakeBackend()
        self.api._browser = browser.EmbeddedBrowser(
            None, self._dir.name, backend=self.backend)

    def test_open_navigates_the_embedded_view(self):
        result = self.api.browser_open("example.com")
        self.assertEqual(result, {"ok": True, "url": "https://example.com",
                                  "message": "Abriendo https://example.com"})
        self.assertEqual(self.backend.calls, [("navigate", "https://example.com")])

    def test_open_empty_address_warns(self):
        result = self.api.browser_open("  ")
        self.assertEqual(result, {"ok": False, "url": "",
                                  "message": "Escribí una dirección para navegar."})
        self.assertEqual(self.backend.calls, [])

    def test_open_failure_reports_unavailable_with_the_url(self):
        self.backend.navigate = mock.Mock(side_effect=RuntimeError("sin WebView2"))
        result = self.api.browser_open("example.com")
        self.assertEqual(result["ok"], False)
        self.assertEqual(result["unavailable"], True)
        self.assertEqual(result["url"], "https://example.com")
        self.assertEqual(result["message"],
                         "No se pudo abrir el navegador integrado: sin WebView2")

    def test_back_forward_and_place(self):
        self.api.browser_back()
        self.api.browser_forward()
        self.api.browser_place({"x": 1}, True)
        self.assertEqual(self.backend.calls,
                         [("back",), ("forward",), ("place", {"x": 1}, True)])

    def test_state_reports_url_history_and_clears_the_error(self):
        self.api._browser.state.update(url="https://a.b/", can_back=True, error="falló")
        self.assertEqual(self.api.browser_state(),
                         {"url": "https://a.b/", "can_back": True,
                          "can_forward": False, "error": "falló"})
        self.assertEqual(self.api.browser_state()["error"], "")

    def test_open_external_uses_the_default_browser(self):
        with mock.patch("webbrowser.open") as opened:
            result = self.api.browser_open_external("example.com")
        opened.assert_called_once_with("https://example.com")
        self.assertEqual(result["ok"], True)

    def test_open_external_without_address_warns(self):
        with mock.patch("webbrowser.open") as opened:
            result = self.api.browser_open_external("")
        opened.assert_not_called()
        self.assertEqual(result, {"ok": False, "message": "No hay una dirección para abrir."})


class TestBrowserUiContract(unittest.TestCase):
    def test_bar_has_the_legacy_controls(self):
        for control in ("browser-back", "browser-forward", "browser-address",
                        "browser-go", "browser-external", "browser-host"):
            self.assertIn(f'id="{control}"', INDEX)
        self.assertIn(">Ir<", INDEX)
        self.assertIn(">Abrir en navegador<", INDEX)
        self.assertIn("Escribí una dirección arriba o hacé clic en un link de la Vista previa.",
                      INDEX)
        self.assertNotIn("<iframe", INDEX)

    def test_preview_links_open_in_the_browser_tab(self):
        handler = MAIN_JS.split("// Links clicked in Vista previa", 1)[1][:600]
        self.assertIn("preventDefault()", handler)
        self.assertIn("openBrowserUrl(", handler)


if __name__ == "__main__":
    unittest.main()
