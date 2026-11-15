"""Vista previa: a web address written as plain text is a clickable link."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt_core.markdown import render_markdown

URL = "https://example.net/wp-content/uploads/2022/04/tabla-8-con-respuestas.png"


class TestBareUrlLinks(unittest.TestCase):
    def test_bare_url_in_a_list_item_becomes_a_link(self):
        html = render_markdown(f"- Tabla del 8 – {URL}")
        self.assertIn(f'<a href="{URL}">{URL}</a>', html)

    def test_trailing_punctuation_stays_outside_the_link(self):
        html = render_markdown("Mirá https://example.com/a, y https://example.com/b.")
        self.assertIn('<a href="https://example.com/a">https://example.com/a</a>,', html)
        self.assertIn('<a href="https://example.com/b">https://example.com/b</a>.', html)

    def test_url_with_query_keeps_its_ampersand(self):
        html = render_markdown("https://example.com/buscar?a=1&b=2")
        self.assertIn('<a href="https://example.com/buscar?a=1&amp;b=2">'
                      "https://example.com/buscar?a=1&amp;b=2</a>", html)

    def test_markdown_links_are_not_linked_twice(self):
        html = render_markdown("[https://example.com](https://example.com)")
        self.assertEqual(html.count("<a "), 1)

    def test_urls_inside_code_stay_plain(self):
        html = render_markdown("usa `https://example.com/x`\n\n```\nhttps://example.com/y\n```")
        self.assertNotIn("<a ", html)

    def test_parenthesised_url_keeps_the_bracket_outside(self):
        html = render_markdown("(ver https://example.com/a)")
        self.assertIn('<a href="https://example.com/a">https://example.com/a</a>)', html)


if __name__ == "__main__":
    unittest.main()
