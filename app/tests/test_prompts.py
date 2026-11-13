"""Tests for AI action prompts (legacy parity, S1)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt_core.prompts import consult_prompt, correct_prompt, summarize_prompt, translate_prompt


class TestPrompts(unittest.TestCase):
    def test_consult_prompt_keeps_the_legacy_lines_and_adds_the_s11_rules(self):
        # S11: the legacy base stays; the anti-echo and research rules are new.
        self.assertEqual(
            consult_prompt("¿qué es Rust?"),
            "Respondé de manera clara, precisa y útil la siguiente consulta.\n"
            "Devolvé solamente la respuesta, sin introducciones innecesarias.\n"
            "No repitas, parafrasees, cites ni reformules la consulta: arrancá directo con la respuesta.\n"
            "Si tenés búsqueda web disponible, investigá el tema, contrastá fuentes y sintetizá lo encontrado en la respuesta.\n"
            "\n"
            "Consulta:\n"
            "¿qué es Rust?\n",
        )

    def test_consult_prompt_keeps_the_legacy_base_lines(self):
        prompt = consult_prompt("¿qué es Rust?")
        self.assertIn("Respondé de manera clara, precisa y útil la siguiente consulta.\n", prompt)
        self.assertIn("Devolvé solamente la respuesta, sin introducciones innecesarias.\n", prompt)
        self.assertTrue(prompt.endswith("\nConsulta:\n¿qué es Rust?\n"))

    def test_consult_prompt_forbids_repeating_or_rephrasing_the_question(self):
        prompt = consult_prompt("¿qué es Rust?")
        lowered = prompt.lower()
        for forbidden in ("no repitas", "parafrase", "cites", "reformule"):
            self.assertIn(forbidden, lowered)

    def test_consult_prompt_directs_web_enabled_research(self):
        prompt = consult_prompt("¿qué es Rust?")
        lowered = prompt.lower()
        self.assertIn("búsqueda web", lowered)
        self.assertIn("investig", lowered)
        self.assertIn("sintetiz", lowered)

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
