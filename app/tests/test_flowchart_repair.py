"""Real answers from models that Mermaid rejected, and the repaired form."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt_core import prompts


class TestRepairMermaid(unittest.TestCase):
    def test_emoji_before_the_quoted_text_moves_inside_the_quotes(self):
        self.assertEqual(prompts.repair_mermaid('I1([🖱️ "Mostrar menú"]):::proceso'),
                         'I1(["🖱️ Mostrar menú"]):::proceso')
        self.assertEqual(prompts.repair_mermaid('I0((🔰 "Inicio"))'), 'I0(("🔰 Inicio"))')
        self.assertEqual(prompts.repair_mermaid('DB1[(💾 "Archivo datos")]'),
                         'DB1[("💾 Archivo datos")]')
        self.assertEqual(prompts.repair_mermaid('D1{{❓ "¿Todo OK?"}}'), 'D1{{"❓ ¿Todo OK?"}}')

    def test_round_brace_shape_becomes_a_decision(self):
        self.assertEqual(prompts.repair_mermaid('I2({❓ "¿Qué operación?"})'),
                         'I2{"❓ ¿Qué operación?"}')

    def test_correct_code_is_left_alone(self):
        code = "\n".join([
            'subgraph UI ["Interfaz de Usuario"]',
            '    A1(["🚀 Inicio"]):::inicio --> A3{"❓ Datos válidos?"}:::decision',
            '    A3 -- "Sí" --> F1[("💾 Base de datos")]',
            '    A3 -- " " --> B1["📂 Crear registro"]',
            "end",
            "class A1,H1 inicio;",
        ])
        self.assertEqual(prompts.repair_mermaid(code), code)


class TestLegendAfterBareCode(unittest.TestCase):
    ANSWER = "\n".join([
        "flowchart TD",
        "    classDef inicio fill:#1E293B,stroke:#0F172A,stroke-width:2px,color:#FFFFFF;",
        "",
        '    subgraph Entrada ["Entrada de Datos"]',
        '        A1(["🚀 Inicio"])',
        "    end",
        "",
        '    A1 -- " " --> A2',
        "",
        "    class A1,H1 inicio;",
        "",
        "",
        "",
        "Gris oscuro: Inicio y fin del proceso.",
        "",
        "Índigo: Puntos de decisión (preguntas).",
    ])

    def test_plain_sentences_after_the_code_are_the_legend(self):
        fixed = prompts.ensure_mermaid_block(self.ANSWER)
        code, legend = fixed.split("\n```\n\n", 1)
        self.assertTrue(code.startswith("```mermaid\nflowchart TD\n"))
        self.assertTrue(code.endswith("    class A1,H1 inicio;"))
        self.assertEqual(legend, "Gris oscuro: Inicio y fin del proceso.\n\n"
                                 "Índigo: Puntos de decisión (preguntas).")

    def test_fenced_answer_is_repaired_inside_the_fence_only(self):
        answer = ('```mermaid\nflowchart TD\n    I1([🖱️ "Menú"]) --> I2({❓ "¿Cuál?"})\n```\n\n'
                  '**Leyenda**\n- Azul (proceso): pasos ["así"].')
        fixed = prompts.ensure_mermaid_block(answer)
        self.assertIn('    I1(["🖱️ Menú"]) --> I2{"❓ ¿Cuál?"}\n```', fixed)
        self.assertTrue(fixed.endswith('- Azul (proceso): pasos ["así"].'))


if __name__ == "__main__":
    unittest.main()
