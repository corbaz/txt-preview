"""Static UI contract tests (T15/S8): the pywebview production UI must match
the original txt.ps1 layout — top navigation/context bar, editor canvas
without top toolbars, the complete four-row bottom control deck with the
exact legacy labels in order, and a maximized startup window.

These tests parse the public interface only: index.html text/attributes,
main.py source (AST) and js/main.js handler wiring. No GUI is launched.
"""
import ast
from html.parser import HTMLParser
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "www" / "index.html"
MAIN_PY = ROOT / "main.py"
MAIN_JS = ROOT / "www" / "js" / "main.js"
APP_CSS = ROOT / "www" / "css" / "app.css"

STATUS_DEFAULT = "Sin archivos adjuntos para la próxima solicitud"


class Node:
    def __init__(self, tag, attrs):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []
        self.text_parts = []

    @property
    def id(self):
        return self.attrs.get("id")

    def text(self):
        parts = list(self.text_parts)
        for child in self.children:
            parts.append(child.text())
        return "".join(parts).strip()

    def find_all(self, tag=None, node_id=None, cls=None):
        found = []
        for child in self.children:
            if (tag is None or child.tag == tag) \
                    and (node_id is None or child.id == node_id) \
                    and (cls is None or cls in child.attrs.get("class", "").split()):
                found.append(child)
            found.extend(child.find_all(tag, node_id, cls))
        return found

    def find(self, tag=None, node_id=None, cls=None):
        matches = self.find_all(tag, node_id, cls)
        return matches[0] if matches else None


class _TreeBuilder(HTMLParser):
    VOID = {"meta", "link", "br", "hr", "img", "input", "path", "circle"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, attrs))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if data.strip() or data == " ":
            self.stack[-1].text_parts.append(data)


def parse_html():
    builder = _TreeBuilder()
    builder.feed(INDEX.read_text(encoding="utf-8"))
    return builder.root


def control_labels(node):
    """Visible labels of the controls inside a deck row, in source order:
    button/label text, the selected option text of a select, nothing for
    sliders/inputs."""
    labels = []
    for control in node.find_all():
        if control.tag == "button":
            labels.append(control.text())
        elif control.tag == "label":
            labels.append(control.text())
        elif control.tag == "select":
            option = control.find("option")
            labels.append(option.text() if option else "")
        elif control.tag == "span" and (control.id
                or "deck-label" in control.attrs.get("class", "")):
            labels.append(control.text())
    return labels


import re


def css_block(source, selector):
    """Body of the first top-level `selector { ... }` rule."""
    pattern = re.escape(selector) + r"\s*\{([^{}]*)\}"
    match = re.search(pattern, source)
    return match.group(1) if match else None


def js_function(source, name):
    """Full text of `function name(...) { ... }` (brace matched)."""
    marker = f"function {name}("
    start = source.index(marker)
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(f"unclosed function {name}")


class UiContractTestCase(unittest.TestCase):
    def setUp(self):
        self.tree = parse_html()
        self.py_source = MAIN_PY.read_text(encoding="utf-8")
        self.js_source = MAIN_JS.read_text(encoding="utf-8")


class TestTopNavigation(UiContractTestCase):
    def test_left_tabs_in_original_order(self):
        segmented = self.tree.find(node_id="segmented")
        tabs = [button.text() for button in segmented.find_all("button")]
        self.assertEqual(tabs, ["Editor", "Vista previa", "Navegador"])

    def test_status_lives_in_top_bar(self):
        header = self.tree.find(node_id="app-header")
        self.assertIsNotNone(header.find(node_id="status-message"))

    def test_settings_tab_and_model_selector_in_top_bar(self):
        header = self.tree.find(node_id="app-header")
        settings_tab = header.find("button", node_id="settings-tab")
        self.assertIsNotNone(settings_tab)
        self.assertEqual(settings_tab.text(), "Configuración")
        self.assertIsNotNone(header.find("label", cls="model-label"))
        self.assertIsNotNone(header.find("select", node_id="model-select"))

    def test_model_select_no_longer_lives_in_settings_page(self):
        settings_page = self.tree.find(node_id="pages")
        self.assertIsNone(settings_page.find(node_id="model-select"))

    def test_theme_toggle_and_version_are_not_in_the_header(self):
        header = self.tree.find(node_id="app-header")
        self.assertIsNone(header.find(node_id="theme-toggle"))
        self.assertIsNone(header.find(node_id="version-badge"))


class TestContextRow(UiContractTestCase):
    def setUp(self):
        super().setUp()
        self.bar = self.tree.find(node_id="context-bar")

    def test_context_bar_exists_with_title(self):
        self.assertIsNotNone(self.bar)
        self.assertEqual(self.bar.find(cls="context-title").text(), "Contexto IA")

    def test_capability_indicators_have_title_tooltips(self):
        titles = [cap.attrs.get("title") for cap in self.bar.find_all(cls="cap")]
        self.assertEqual(titles, [
            "Chat de texto",
            "Razonamiento",
            "Navegación y búsqueda web",
            "Visión: entiende imágenes",
            "Adjuntar documentos: texto, PDF, Word y PowerPoint",
        ])

    def test_web_search_checkbox_checked_with_original_label(self):
        label = self.bar.find(node_id="web-search-label")
        self.assertIsNotNone(label)
        self.assertIn("Usar web en la próxima consulta", label.text())
        checkbox = label.find("input", node_id="web-search")
        self.assertEqual(checkbox.attrs.get("type"), "checkbox")
        self.assertIn("checked", checkbox.attrs)

    def test_attach_controls_and_summary(self):
        self.assertIsNotNone(self.bar.find(node_id="attach-files"))
        self.assertIsNotNone(self.bar.find(node_id="attach-input"))
        self.assertIsNotNone(self.bar.find(node_id="clear-attachments"))
        summary = self.bar.find(node_id="attachment-summary")
        self.assertIsNotNone(summary)
        self.assertEqual(summary.text(), STATUS_DEFAULT)


class TestMainCanvas(UiContractTestCase):
    def test_no_toolbars_on_top_of_the_editor_or_preview(self):
        for toolbar in ("ai-bar", "preview-bar", "speech-bar", "editor-tools-bar"):
            self.assertIsNone(self.tree.find(node_id=toolbar),
                              f"toolbar #{toolbar} must move to the bottom deck")

    def test_pages_keep_the_four_views(self):
        pages = {page.attrs.get("data-page") for page in self.tree.find_all(cls="page")}
        self.assertEqual(pages, {"editor", "preview", "settings", "browser"})


class TestBottomDeck(UiContractTestCase):
    def setUp(self):
        super().setUp()
        self.deck = self.tree.find(node_id="deck")

    def test_deck_is_after_the_main_canvas(self):
        body = self.tree.find("body")
        tags = [child.tag for child in body.children if child.tag != "script"]
        self.assertEqual(tags, ["header", "div", "main", "footer"])

    def test_row1_ai_actions_in_original_order(self):
        row = self.deck.find(node_id="deck-row-1")
        self.assertEqual(control_labels(row), [
            "Consultar IA",
            "Resumir con IA",
            "Corregir Gramática y Ortografía",
            "Traducir Inglés a Español",
            "Traducir Español a Inglés",
        ])

    def test_row1_ai_actions_keep_their_data_actions(self):
        row = self.deck.find(node_id="deck-row-1")
        actions = [button.attrs.get("data-ai-action") for button in row.find_all("button")]
        self.assertEqual(actions, ["consult", "summarize", "correct",
                                   "translate_en_es", "translate_es_en"])

    def test_row2_utilities_in_original_order(self):
        row = self.deck.find(node_id="deck-row-2")
        self.assertEqual(control_labels(row), [
            "Pegar desde el portapapeles al editor",
            "Copiar MD",
            "Copiar TXT",
            "Micrófono",
            "PDF",
            "MP3",
            "Limpiar chat",
        ])

    def test_row3_voice_and_playback_in_original_order(self):
        row = self.deck.find(node_id="deck-row-3")
        self.assertEqual(control_labels(row), [
            "Hombre",
            "Mujer",
            "Español",
            "Inglés",
            "Voz",
            "es-ES-ElviraNeural",
            "Play",
            "Pausar",
            "Detener",
            "Tema: Oscuro",
            "Cerrar",
        ])

    def test_row3_toggles_are_radio_like(self):
        row = self.deck.find(node_id="deck-row-3")
        toggles = row.find_all("button", cls="toggle")
        self.assertEqual([t.text() for t in toggles],
                         ["Hombre", "Mujer", "Español", "Inglés"])
        self.assertEqual([t.attrs.get("aria-pressed") for t in toggles],
                         ["true", "false", "true", "false"])

    def test_row4_speed_and_replay_in_original_order(self):
        row = self.deck.find(node_id="deck-row-4")
        self.assertEqual(control_labels(row), [
            "Velocidad de lectura",
            "1,00x",
            "Repetir",
            "0:00 / 0:00",
            "",
        ])

    def test_speed_slider_legacy_range(self):
        speed = self.deck.find("input", node_id="speed")
        self.assertIsNotNone(speed)
        self.assertEqual(speed.attrs.get("type"), "range")
        self.assertEqual(speed.attrs.get("min"), "50")
        self.assertEqual(speed.attrs.get("max"), "200")
        self.assertEqual(speed.attrs.get("value"), "100")

    def test_replay_slider_exists(self):
        seek = self.deck.find("input", node_id="seek")
        self.assertIsNotNone(seek)
        self.assertEqual(seek.attrs.get("type"), "range")
        self.assertEqual(seek.attrs.get("value"), "0")

    def test_version_label_sits_in_the_bottom_deck(self):
        version = self.deck.find(node_id="version-badge")
        self.assertIsNotNone(version)
        self.assertEqual(version.id, "version-badge")


class TestStartupMaximized(UiContractTestCase):
    def _create_window_call(self):
        tree = ast.parse(self.py_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) \
                    and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "create_window":
                return node
        return None

    def test_create_window_starts_maximized(self):
        call = self._create_window_call()
        self.assertIsNotNone(call)
        maximized = [kw for kw in call.keywords if kw.arg == "maximized"]
        self.assertTrue(maximized)
        self.assertIsInstance(maximized[0].value, ast.Constant)
        self.assertIs(maximized[0].value.value, True)

    def test_create_window_keeps_title_and_min_size(self):
        call = self._create_window_call()
        args = [ast.unparse(arg).replace("'", '"') for arg in call.args]
        keywords = {kw.arg for kw in call.keywords}
        self.assertIn("min_size", keywords)
        self.assertIn('"TXT Preview"', args[0])


class TestApiSurface(UiContractTestCase):
    def test_start_dictation_exists(self):
        tree = ast.parse(self.py_source)
        names = {node.name for node in ast.walk(tree)
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertIn("start_dictation", names)

    def test_close_app_exists(self):
        tree = ast.parse(self.py_source)
        names = {node.name for node in ast.walk(tree)
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertIn("close_app", names)


class TestJavaScriptWiring(UiContractTestCase):
    BINDINGS = {
        "mic-button": "start_dictation",
        "close-app": "close_app",
        "speed": "set_speech_speed",
        "seek": "replay_start",
        "gender-male": "set_speech_voice",
        "gender-female": "set_speech_voice",
        "lang-es": "set_speech_voice",
        "lang-en": "set_speech_voice",
        "paste-editor": "clipboard.readText",
        "copy-md": "get_preview_text",
        "copy-txt": "get_preview_plain_text",
        "export-pdf": "export_pdf",
        "export-mp3": "export_mp3",
        "clear-chat": "clear_attachments",
        "attach-files": "add_attachments",
        "clear-attachments": "clear_attachments",
        "model-select": "set_selected_model",
        "voice-select": "set_speech_voice",
        "speech-play": "start_speech",
        "speech-pause": "pause_speech",
        "speech-stop": "stop_speech",
        "speech-replay": "replay_start",
        "theme-toggle": "set_theme",
    }

    def handler_window(self, control_id):
        marker = f'$("{control_id}")'
        windows = []
        start = self.js_source.find(marker)
        while start >= 0:
            windows.append(self.js_source[max(0, start - 200):start + 700])
            start = self.js_source.find(marker, start + 1)
        return "\n".join(windows)

    def test_every_deck_control_is_bound_and_calls_its_api(self):
        missing = []
        for control_id, method in self.BINDINGS.items():
            window = self.handler_window(control_id)
            if "addEventListener" not in window or method not in window:
                missing.append((control_id, method))
        self.assertEqual(missing, [])

    def test_settings_tab_is_wired_like_the_other_tabs(self):
        self.assertIn('querySelectorAll(".seg")', self.js_source)
        self.assertIn("dataset.tab", self.js_source)
        self.assertIn("function setTab", self.js_source)

    def test_speed_slider_updates_label_on_input_and_api_on_commit(self):
        speed_zone = self.handler_window("speed")
        self.assertIn('"input"', speed_zone)
        self.assertIn('"change"', speed_zone)
        self.assertIn('replace(".", ",")', speed_zone)

    def test_seek_slider_updates_from_speech_tick_state(self):
        self.assertIn("replay_duration", self.js_source)
        self.assertIn("replay_position", self.js_source)
        # Legacy label format m:ss ("0:00 / 0:00").
        self.assertIn("fmtSeconds", self.js_source)
        self.assertIn('" / "', self.js_source)

    def test_copy_buttons_follow_the_preview_first_legacy_rule(self):
        self.assertIn("previewHasAiResponse", self.js_source)

    def test_gender_language_toggles_filter_the_voice_catalog(self):
        for token in ("voiceCatalog", "gender", "culture", "aria-pressed"):
            self.assertIn(token, self.js_source)


class TestBottomRowDistribution(UiContractTestCase):
    """S9: rows centered/distributed like the original; version pinned
    bottom-right of the deck without shifting row 4."""

    def setUp(self):
        super().setUp()
        self.css_source = APP_CSS.read_text(encoding="utf-8")

    def test_deck_rows_are_centered_like_the_original(self):
        row = css_block(self.css_source, ".deck-row")
        self.assertIsNotNone(row, ".deck-row rule missing")
        self.assertIn("justify-content: center", row)

    def test_deck_inner_spans_a_centered_desktop_area(self):
        inner = css_block(self.css_source, ".deck-inner")
        self.assertIsNotNone(inner, ".deck-inner rule missing")
        self.assertIn("width: 100%", inner)
        self.assertIn("max-width: 1252px", inner)
        self.assertIn("margin: 0 auto", inner)

    def test_version_is_pinned_bottom_right_without_shifting_row4(self):
        deck = css_block(self.css_source, "#deck")
        self.assertIsNotNone(deck, "#deck rule missing")
        self.assertIn("position: relative", deck)
        version = css_block(self.css_source, ".version")
        self.assertIsNotNone(version, ".version rule missing")
        self.assertIn("position: absolute", version)
        self.assertIn("right: 18px", version)
        self.assertIn("bottom: 14px", version)
        self.assertNotIn("margin-left: auto", version)


class TestAiActionSpinner(UiContractTestCase):
    """S9: every [data-ai-action] button shows an in-button spinner until the
    AI answer arrives (setAiBusy true before ask_ai, false in finally)."""

    def setUp(self):
        super().setUp()
        self.css_source = APP_CSS.read_text(encoding="utf-8")

    def test_every_ai_action_button_is_wired_through_run_ai(self):
        self.assertIn('querySelectorAll("[data-ai-action]")', self.js_source)
        for action in ("consult", "summarize", "correct",
                       "translate_en_es", "translate_es_en"):
            row = self.tree.find(node_id="deck-row-1")
            actions = [button.attrs.get("data-ai-action")
                       for button in row.find_all("button")]
            self.assertIn(action, actions)

    def test_set_ai_busy_toggles_class_and_aria_busy(self):
        body = js_function(self.js_source, "setAiBusy")
        self.assertIn("ai-busy", body)
        self.assertIn('setAttribute("aria-busy", "true")', body)
        self.assertIn('removeAttribute("aria-busy")', body)

    def test_run_ai_shows_spinner_until_the_response_arrives(self):
        body = js_function(self.js_source, "runAi")
        self.assertLess(body.index("setAiBusy(button, true)"),
                        body.index("ask_ai("))
        self.assertGreater(body.index("setAiBusy(button, false)"),
                           body.index("finally"))

    def test_spinner_css_is_visible_and_keeps_the_button_width(self):
        spinner = css_block(self.css_source, ".btn.ai-busy::before")
        self.assertIsNotNone(spinner, ".btn.ai-busy::before rule missing")
        self.assertIn("width: 12px", spinner)
        self.assertIn("border-radius: 50%", spinner)
        self.assertIn("animation: ai-spin", spinner)
        # Absolutely positioned inside the padding: the original button width
        # (text label) stays stable while it spins.
        self.assertIn("position: absolute", spinner)
        self.assertIn("@keyframes ai-spin", self.css_source)

    def test_spinner_respects_prefers_reduced_motion(self):
        index = self.css_source.index("prefers-reduced-motion: reduce")
        segment = self.css_source[index:index + 300]
        self.assertIn("animation: none", segment)


class TestMainModelSelectorStartup(UiContractTestCase):
    """S9: the main-page model selector loads its catalog on startup — no
    visit to Configuración and no manual 'Actualizar modelos' click."""

    def test_pywebviewready_loads_models_and_restores_the_saved_model(self):
        start = self.js_source.index('"pywebviewready"')
        end = self.js_source.index("});", start)
        handler = self.js_source[start:end]
        self.assertIn("get_settings", handler)
        self.assertIn("selected_model", handler)
        self.assertIn("loadStartupModels(", handler)

    def test_startup_asks_the_api_for_the_catalog(self):
        body = js_function(self.js_source, "loadStartupModels")
        self.assertIn("update_models()", body)
        self.assertIn("applyModelCatalog(result, selectedModel)", body)

    def test_startup_shows_loading_status_and_restores_ready(self):
        body = js_function(self.js_source, "loadStartupModels")
        self.assertIn('"Cargando modelos..."', body)
        self.assertIn('"Listo."', body)

    def test_catalog_failure_keeps_the_default_and_needs_more_than_one_model(self):
        body = js_function(self.js_source, "loadStartupModels")
        self.assertIn("select.options.length > 1", body)

    def test_apply_model_catalog_accepts_a_preferred_model(self):
        self.assertIn("function applyModelCatalog(result, preferredModel)",
                      self.js_source)

    def test_apply_model_catalog_enables_the_selector_with_options(self):
        body = js_function(self.js_source, "applyModelCatalog")
        self.assertIn("select.disabled = select.options.length === 0;", body)
        # The persisted/saved model stays selected after the catalog load.
        self.assertIn("preferredModel", body)


if __name__ == "__main__":
    unittest.main()
