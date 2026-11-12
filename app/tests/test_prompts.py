"""Tests for AI action prompts (legacy parity, S1)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt_core.prompts import consult_prompt, correct_prompt, summarize_prompt, translate_prompt


class TestPrompts(unittest.TestCase):
    def test_consult_prompt_is_verbatim_legacy(self):
        self.assertEqual(
            consult_prompt("¿qué es Rust?"),
            "Respondé de manera clara, precisa y útil la siguiente consulta.\n"
            "Devolvé solamente la respuesta, sin introducciones innecesarias.\n"
            "\n"
            "Consulta:\n"
            "¿qué es Rust?\n",
        )

    def test_correct_prompt_is_verbatim_legacy(self):
        prompt = correct_prompt("hola mundo")
        self.assertIn("Actúa como un corrector experto en redacción en español.", prompt)
        self.assertIn("Dame solo el texto corregido, sin explicaciones ni comentarios.", prompt)
        self.assertTrue(prompt.endswith("Texto original:\nhola mundo\n"))

    def test_summarize_prompt_is_verbatim_legacy(self):
        prompt = summarize_prompt("contenido")
        self.assertIn("Actuá como analista profesional, clasificador y ejemplificador experto.", prompt)
        self.assertIn("- Entregá el resultado en Markdown claro y bien estructurado.", prompt)
        self.assertTrue(prompt.endswith("Contenido:\ncontenido\n"))

    def test_translate_prompt_swaps_languages(self):
        prompt = translate_prompt("hola", "inglés", "español")
        self.assertIn("Traducí el siguiente texto del inglés al español.", prompt)
        self.assertTrue(prompt.endswith("Texto original:\nhola\n"))

    def test_prompts_keep_trailing_newline(self):
        self.assertTrue(consult_prompt("x").endswith("\n"))
        self.assertTrue(translate_prompt("x", "a", "b").endswith("\n"))


if __name__ == "__main__":
    unittest.main()
