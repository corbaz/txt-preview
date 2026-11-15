"""«Diagrama de flujo»: a colored Mermaid flowchart drawn in Vista previa."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from txt_core import groq, prompts, teams
from txt_core.markdown import render_markdown

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "www" / "index.html").read_text(encoding="utf-8")
MAIN_JS = (ROOT / "www" / "js" / "main.js").read_text(encoding="utf-8")
DIAGRAM = "```mermaid\nflowchart TD\n    A([\"Inicio\"]):::inicio --> B{\"¿Válido?\"}:::decision\n```"


class TestFlowchartPrompt(unittest.TestCase):
    def test_prompt_asks_for_a_colored_mermaid_flowchart_only(self):
        prompt = prompts.flowchart_prompt("CRUD de usuarios")
        self.assertIn("```mermaid", prompt)
        self.assertIn("flowchart TD", prompt)
        self.assertIn("classDef decision fill:#6366F1,stroke:#4338CA,stroke-width:2px,color:#FFFFFF;",
                      prompt)
        self.assertIn("una leyenda breve", prompt)
        self.assertIn("subgraph", prompt)
        self.assertIn("emoji", prompt)
        self.assertTrue(prompt.endswith("Tema:\nCRUD de usuarios\n"))

    def test_bare_mermaid_answers_get_the_fence(self):
        self.assertEqual(prompts.ensure_mermaid_block("flowchart TD\n  A --> B"),
                         "```mermaid\nflowchart TD\n  A --> B\n```")
        self.assertEqual(prompts.ensure_mermaid_block("```\ngraph LR\n  A --> B\n```"),
                         "```mermaid\ngraph LR\n  A --> B\n```")

    def test_padded_node_labels_are_repaired(self):
        padded = ('```mermaid'+chr(10)+'flowchart TD'+chr(10)+'  A1([ "Inicio" ]):::inicio --> B{ "¿Ok?" }'+chr(10)
                  +'  B -- "Sí" --> C[( "Base" )]'+chr(10)+'  B -- "No" --> D[ "Fin" ]'+chr(10)+'```')
        fixed = prompts.ensure_mermaid_block(padded)
        self.assertIn('A1(["Inicio"]):::inicio --> B{"¿Ok?"}', fixed)
        self.assertIn('B -- "Sí" --> C[("Base")]', fixed)
        self.assertIn('B -- "No" --> D["Fin"]', fixed)

    def test_bare_diagram_followed_by_a_legend_keeps_the_legend_as_text(self):
        nl = chr(10)
        answer = nl.join(["Mermaid", "", "graph TD", "    A[Cliente] --> B{Tipo}", "",
                          "    %% Estilos", "    style A fill:#e1f5fe", "", "",
                          "Leyenda de Diseños:", "", "*   Azul (Read): lectura."])
        fixed = prompts.ensure_mermaid_block(answer)
        self.assertTrue(fixed.startswith("```mermaid" + nl + "graph TD" + nl))
        self.assertIn("    style A fill:#e1f5fe" + nl + "```" + nl + nl + "Leyenda de Diseños:", fixed)
        self.assertTrue(fixed.endswith("*   Azul (Read): lectura."))

    def test_fenced_and_unrelated_answers_are_kept(self):
        self.assertEqual(prompts.ensure_mermaid_block(DIAGRAM), DIAGRAM)
        self.assertEqual(prompts.ensure_mermaid_block("No puedo ayudar."), "No puedo ayudar.")


class TestFlowchartAction(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.api = main.Api(settings_dir=self._dir.name)
        self.api.engine = mock.Mock()
        patcher = mock.patch.dict("os.environ", {"GROQ_API_KEY": "gsk_test"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_flowchart_keeps_the_topic_and_returns_a_mermaid_block(self):
        with mock.patch.object(groq, "post_chat",
                               return_value={"text": "flowchart TD\n  A --> B"}) as post:
            result = self.api.ask_ai("flowchart", False, "CRUD de usuarios")
        self.assertIn("Tema:\nCRUD de usuarios", post.call_args[0][1]["messages"][0]["content"])
        self.assertEqual(result["text"], "```mermaid\nflowchart TD\n  A --> B\n```")
        self.assertEqual(result["editor_action"], "keep")
        self.assertEqual(result["message"],
                         "Diagrama de flujo listo en Vista previa. El tema sigue en el Editor.")

    def test_empty_topic_is_refused(self):
        self.assertEqual(
            self.api.ask_ai("flowchart", False, " ")["error"],
            "Ingresá en el Editor el tema del diagrama o adjuntá al menos un archivo.")

    def test_speech_text_leaves_the_diagram_code_out(self):
        self.api.set_preview_content("Antes\n\n" + DIAGRAM + "\n\nDespués")
        self.assertEqual(self.api.get_preview_speech_text(), "Antes\n\nDespués")


class TestDiagramRendering(unittest.TestCase):
    def test_mermaid_block_keeps_its_language_class_and_nothing_else(self):
        html = render_markdown(DIAGRAM)
        self.assertIn('<pre><code class="language-mermaid">flowchart TD', html)
        unsafe = render_markdown('<p class="x" onclick="a()">hola</p>')
        self.assertNotIn("class=", unsafe)
        self.assertNotIn("onclick", unsafe)

    def test_teams_copy_replaces_each_diagram_with_its_picture(self):
        picture = "data:image/png;base64,AAAA"
        html = teams.teams_html("Intro\n\n" + DIAGRAM, [picture])
        self.assertIn(f'<img style="max-width:100%" src="{picture}" alt="Diagrama de flujo"/>', html)
        self.assertNotIn("language-mermaid", html)

    def test_teams_copy_keeps_the_code_when_there_is_no_picture(self):
        for diagrams in (None, [""], ["javascript:alert(1)"]):
            html = teams.teams_html(DIAGRAM, diagrams)
            self.assertIn("flowchart TD", html)
            self.assertNotIn("<img", html)

    def test_ui_has_the_button_after_resumir_and_draws_the_blocks(self):
        row = INDEX.split('data-ai-action="summarize"', 1)[1]
        self.assertLess(row.index('data-ai-action="flowchart"'), row.index('data-ai-action="correct"'))
        self.assertIn(">Diagrama de flujo<", INDEX)
        self.assertLess(INDEX.index("js/vendor/mermaid.min.js"), INDEX.index("js/main.js"))
        self.assertTrue((ROOT / "www" / "js" / "vendor" / "mermaid.min.js").is_file())
        self.assertIn("await renderDiagrams(sequence);", MAIN_JS)
        self.assertIn('securityLevel: "strict"', MAIN_JS)
        self.assertIn("api.copy_for_teams(diagrams)", MAIN_JS)


if __name__ == "__main__":
    unittest.main()
