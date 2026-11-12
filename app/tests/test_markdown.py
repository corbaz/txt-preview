"""Tests for the markdown renderer used by Vista previa (S1, S2)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt_core.markdown import render_markdown


class TestRenderMarkdown(unittest.TestCase):
    def test_headings(self):
        html = render_markdown("# Título\n\n## Sub")
        self.assertIn("<h1>Título</h1>", html)
        self.assertIn("<h2>Sub</h2>", html)

    def test_bold_italic_code(self):
        html = render_markdown("**negrita** *cursiva* `código`")
        self.assertIn("<strong>negrita</strong>", html)
        self.assertIn("<em>cursiva</em>", html)
        self.assertIn("<code>código</code>", html)

    def test_list(self):
        html = render_markdown("- uno\n- dos")
        self.assertIn("<li>uno</li>", html)
        self.assertIn("<li>dos</li>", html)

    def test_link(self):
        html = render_markdown("[Groq](https://groq.com)")
        self.assertIn('href="https://groq.com"', html)

    def test_fenced_code_block(self):
        html = render_markdown("```python\nprint('hola')\n```")
        self.assertIn("<pre>", html)
        self.assertIn("print", html)

    def test_table(self):
        html = render_markdown("| a | b |\n| - | - |\n| 1 | 2 |")
        self.assertIn("<table>", html)
        self.assertIn("<td>1</td>", html)

    def test_raw_html_is_neutralized(self):
        # Raw HTML from AI answers must never execute or inject markup.
        html = render_markdown("texto con <etiqueta> & símbolos")
        self.assertIn("&lt;etiqueta&gt;", html)

    def test_script_tag_is_escaped_not_executed(self):
        html = render_markdown("hola <script>alert(1)</script> chau")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_allowed_tags_pass_through(self):
        html = render_markdown("<blockquote>cita</blockquote>")
        self.assertIn("<blockquote>", html)

    def test_onclick_attribute_is_removed(self):
        html = render_markdown('<a href="https://x.y" onclick="evil()">link</a>')
        self.assertNotIn("onclick", html)
        self.assertIn('href="https://x.y"', html)

    def test_empty_text(self):
        self.assertEqual(render_markdown(""), "")


if __name__ == "__main__":
    unittest.main()
