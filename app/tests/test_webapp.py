"""UI server: no-store on every response and version-stamped asset URLs, so
an updated app never runs new JS against a cached index.html."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt_core import webapp


def call(app, path):
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = b"".join(app({"PATH_INFO": path, "REQUEST_METHOD": "GET"}, start_response))
    return captured["status"], captured["headers"], body


class TestWebApp(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        root = Path(self._dir.name)
        (root / "js").mkdir()
        (root / "css").mkdir()
        (root / "js" / "main.js").write_text("console.log('ñ')", encoding="utf-8")
        (root / "css" / "app.css").write_text("body{}", encoding="utf-8")
        (root / "index.html").write_text(
            '<link rel="stylesheet" href="css/app.css" />'
            '<a href="https://example.com/js/x.js">x</a>'
            '<script src="js/main.js"></script>', encoding="utf-8")
        (root.parent / "outside.txt").write_text("secret", encoding="utf-8")
        self.addCleanup((root.parent / "outside.txt").unlink)
        self.root = root
        self.app = webapp.create_wsgi_app(root)

    def test_root_and_index_serve_stamped_html_without_caching(self):
        js_version = int((self.root / "js" / "main.js").stat().st_mtime)
        css_version = int((self.root / "css" / "app.css").stat().st_mtime)
        for path in ("/", "/index.html"):
            status, headers, body = call(self.app, path)
            self.assertEqual(status, "200 OK")
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
            self.assertEqual(
                body.decode("utf-8"),
                f'<link rel="stylesheet" href="css/app.css?v={css_version}" />'
                '<a href="https://example.com/js/x.js">x</a>'
                f'<script src="js/main.js?v={js_version}"></script>')

    def test_assets_are_served_without_caching(self):
        status, headers, body = call(self.app, "/js/main.js")
        self.assertEqual(status, "200 OK")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("javascript", headers["Content-Type"])
        self.assertEqual(body.decode("utf-8"), "console.log('ñ')")

    def test_missing_and_outside_files_are_not_served(self):
        self.assertEqual(call(self.app, "/nope.js")[0], "404 Not Found")
        self.assertEqual(call(self.app, "/../outside.txt")[0], "404 Not Found")

    def test_real_index_references_get_stamped(self):
        www = Path(__file__).resolve().parents[1] / "www"
        html = webapp.stamped_index(www).decode("utf-8")
        self.assertRegex(html, r'src="js/main\.js\?v=\d+"')
        self.assertRegex(html, r'href="css/app\.css\?v=\d+"')


if __name__ == "__main__":
    unittest.main()
