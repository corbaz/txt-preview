"""Tests for AI citation-marker stripping (legacy parity, S1)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt_core.citations import strip_citation_markers


class TestStripCitationMarkers(unittest.TestCase):
    def test_empty_string_returns_empty(self):
        self.assertEqual(strip_citation_markers(""), "")

    def test_plain_text_unchanged(self):
        text = "Respuesta sin citas de búsqueda web."
        self.assertEqual(strip_citation_markers(text), text)

    def test_readme_example_line_range(self):
        # README: "Las marcas de cita ... (como 【2†L58-L62】) se quitan antes de mostrarla."
        self.assertEqual(
            strip_citation_markers("según la fuente 【2†L58-L62】."),
            "según la fuente.",
        )

    def test_readme_example_source_only(self):
        self.assertEqual(
            strip_citation_markers("dato verificado 【0†source】"),
            "dato verificado",
        )

    def test_marker_before_punctuation_with_space(self):
        self.assertEqual(
            strip_citation_markers("texto 【2†L58-L62】 , más"),
            "texto, más",
        )

    def test_marker_before_punctuation_without_space(self):
        self.assertEqual(
            strip_citation_markers("texto【3†L1-L2】;fin"),
            "texto;fin",
        )

    def test_marker_between_words_keeps_single_space(self):
        self.assertEqual(
            strip_citation_markers("primero 【1†L5】 segundo"),
            "primero segundo",
        )

    def test_brackets_without_dagger_are_kept(self):
        text = "notas 【sin daga】 quedan"
        self.assertEqual(strip_citation_markers(text), text)

    def test_multiple_markers(self):
        self.assertEqual(
            strip_citation_markers("a 【2†L1】 b 【3†L2-L3】 c"),
            "a b c",
        )

    def test_multiline_brackets_not_matched(self):
        # The legacy regex never crosses a line break inside the marker.
        text = "inicio 【2†\nsalto】fin"
        self.assertEqual(strip_citation_markers(text), text)


if __name__ == "__main__":
    unittest.main()
