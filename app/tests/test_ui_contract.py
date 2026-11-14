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

    def handler_window(self, control_id):
        marker = f'$("{control_id}")'
        windows = []
        start = self.js_source.find(marker)
        while start >= 0:
            windows.append(self.js_source[max(0, start - 200):start + 700])
            start = self.js_source.find(marker, start + 1)
        return "\n".join(windows)


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

    def test_context_bar_is_shown_only_on_the_editor_tab(self):
        """txt.ps1 hosts the Contexto IA panel inside the Editor tab."""
        body = js_function(MAIN_JS.read_text(encoding="utf-8"), "setTab")
        self.assertIn('$("context-bar").hidden = name !== "editor";', body)

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
            "es-CR-JuanNeural",
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
        self.assertIn('"Corrector de Prompt"', args[0])  # txt.ps1 $form.Text


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
        "paste-editor": "read_clipboard",
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
        body = js_function(self.js_source, "copyMain")
        self.assertIn("previewContent()", body)


class TestClipboardBridgeWiring(UiContractTestCase):
    """T25/S18: macOS WKWebView does not expose navigator.clipboard, so
    Pegar/Copiar must go through the bridge's native clipboard methods."""

    def test_no_navigator_clipboard_left_in_the_ui(self):
        self.assertNotIn("navigator.clipboard", self.js_source)

    def test_paste_uses_the_bridge_via_safe_call(self):
        window = self.handler_window("paste-editor")
        self.assertIn("read_clipboard", window)
        self.assertIn("safeCall", window)
        self.assertNotIn("navigator", window)

    def test_paste_preserves_legacy_empty_and_error_messages(self):
        window = self.handler_window("paste-editor")
        self.assertIn("El portapapeles no contiene texto.", window)
        self.assertIn("No se pudo leer el portapapeles.", window)
        self.assertIn("Texto pegado desde el portapapeles.", window)

    def test_copy_uses_the_bridge_write_clipboard(self):
        copy_main = js_function(self.js_source, "copyMain")
        self.assertIn("write_clipboard", copy_main)
        self.assertNotIn("navigator", copy_main)

    def test_copy_preserves_legacy_messages_and_preview_first_rule(self):
        self.assertIn("Markdown copiado al portapapeles.", self.js_source)
        self.assertIn("Texto sin formato copiado al portapapeles.", self.js_source)
        self.assertIn("No se pudo copiar al portapapeles.", self.js_source)

    def test_corregir_clipboard_result_copies_through_the_bridge(self):
        run_ai = js_function(self.js_source, "runAi")
        self.assertIn("write_clipboard", run_ai)
        self.assertNotIn("navigator", run_ai)

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


class TestPreviewTypography(UiContractTestCase):
    """S10/T17 (A): Vista previa keeps the editor's line/paragraph rhythm —
    single breaks stay as <br>, blank lines visibly separate paragraphs."""

    def setUp(self):
        super().setUp()
        self.css_source = APP_CSS.read_text(encoding="utf-8")

    def test_markdown_body_line_height_matches_or_exceeds_the_editor(self):
        body = css_block(self.css_source, ".markdown-body")
        self.assertIsNotNone(body, ".markdown-body rule missing")
        match = re.search(r"line-height:\s*([0-9.]+)", body)
        self.assertIsNotNone(match, "line-height missing in .markdown-body")
        self.assertGreaterEqual(float(match.group(1)), 1.55)

    def test_paragraphs_are_visibly_separated(self):
        p = css_block(self.css_source, ".markdown-body p")
        self.assertIsNotNone(p, ".markdown-body p rule missing")
        self.assertIn("margin: 0 0 1em", p)

    def test_br_keeps_the_default_line_break_height(self):
        br = css_block(self.css_source, ".markdown-body br")
        self.assertIsNotNone(br, "explicit .markdown-body br rule missing")

    def test_headings_and_lists_are_spaced(self):
        for selector in (".markdown-body h1, .markdown-body h2, .markdown-body h3",
                         ".markdown-body ul, .markdown-body ol"):
            block = css_block(self.css_source, selector)
            self.assertIsNotNone(block, f"{selector} rule missing")
            self.assertIn("margin:", block)

    def test_no_double_spacing_inside_list_items_and_code_blocks(self):
        li_p = css_block(self.css_source, ".markdown-body li p")
        self.assertIsNotNone(li_p, ".markdown-body li p rule missing")
        self.assertIn("margin: 0", li_p)
        pre = css_block(self.css_source, ".markdown-body pre")
        self.assertIn("padding:", pre)

    def test_speech_word_walker_resets_the_global_token_before_each_test(self):
        body = js_function(self.js_source, "wrapSpeechWords")
        # TOKEN is /\S+/g: without resetting lastIndex, acceptNode results
        # depend on the walker's previous calls (nondeterministic acceptance).
        self.assertLess(body.index("TOKEN.lastIndex = 0;"),
                        body.index("TOKEN.test(node.nodeValue)"))

    def test_whitespace_text_nodes_are_preserved_exactly(self):
        body = js_function(self.js_source, "wrapSpeechWords")
        # One text node for the gap before each match and one for the
        # trailing remainder: whitespace is never dropped.
        self.assertEqual(body.count("document.createTextNode("), 2)


class TestWorkOverlay(UiContractTestCase):
    """S10/T17 (B): pending AI work shows one large centered overlay over the
    canvas, never a spinner inside a button."""

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

    def test_overlay_lives_inside_pages_with_status_semantics(self):
        pages = self.tree.find(node_id="pages")
        overlay = pages.find(node_id="work-overlay")
        self.assertIsNotNone(overlay)
        self.assertIn(overlay, pages.children)
        self.assertIn("hidden", overlay.attrs)
        self.assertEqual(overlay.attrs.get("role"), "status")
        self.assertEqual(overlay.attrs.get("aria-live"), "polite")

    def test_overlay_holds_a_large_spinner_and_a_message_label(self):
        overlay = self.tree.find(node_id="work-overlay")
        self.assertIsNotNone(overlay.find(cls="work-spinner"))
        self.assertIsNotNone(overlay.find(node_id="work-message"))

    def test_no_spinner_remains_inside_any_button(self):
        self.assertIsNone(css_block(self.css_source, ".btn.ai-busy::before"))
        self.assertNotIn("ai-busy", self.css_source)
        self.assertNotIn("ai-busy", self.js_source)
        self.assertNotIn("ai-busy", INDEX.read_text(encoding="utf-8"))
        self.assertNotIn("setAiBusy", self.js_source)

    def test_overlay_css_covers_the_canvas_and_centers_the_spinner(self):
        pages = css_block(self.css_source, "#pages")
        self.assertIn("position: relative", pages)
        overlay = css_block(self.css_source, "#work-overlay")
        self.assertIsNotNone(overlay, "#work-overlay rule missing")
        self.assertIn("position: absolute", overlay)
        self.assertIn("inset: 0", overlay)
        self.assertIn("align-items: center", overlay)
        self.assertIn("justify-content: center", overlay)
        self.assertIn("rgba(", overlay)  # dark translucent backdrop
        self.assertIn("z-index:", overlay)  # over editor/preview

    def test_spinner_is_large_and_the_label_sits_below(self):
        spinner = css_block(self.css_source, ".work-spinner")
        self.assertIsNotNone(spinner, ".work-spinner rule missing")
        self.assertIn("width: 60px", spinner)   # 56-64px, large work look
        self.assertIn("height: 60px", spinner)
        self.assertIn("border-radius: 50%", spinner)
        self.assertIn("animation:", spinner)
        message = css_block(self.css_source, ".work-message")
        self.assertIsNotNone(message, ".work-message rule missing")
        self.assertIn("margin-top:", message)

    def test_spinner_rotation_is_always_infinite(self):
        spinner = css_block(self.css_source, ".work-spinner")
        self.assertIn("animation:", spinner)
        self.assertIn("infinite", spinner)  # S11: it visibly turns like a gif

    def test_reduced_motion_slows_the_rotation_but_never_stops_it(self):
        index = self.css_source.index("prefers-reduced-motion: reduce")
        segment = self.css_source[index:index + 300]
        self.assertIn(".work-spinner", segment)
        # S11: Windows/WebView2 reported the spinner "quieto" — reduced-motion
        # may slow the rotation, never disable it.
        self.assertNotIn("animation: none", segment)
        self.assertIn("infinite", segment)
        spinner = css_block(self.css_source, ".work-spinner")
        self.assertIn("border:", spinner)  # the ring stays visible

    def test_overlay_hidden_state_hides_it(self):
        hidden = css_block(self.css_source, "#work-overlay[hidden]")
        self.assertIsNotNone(hidden, "#work-overlay[hidden] rule missing")
        self.assertIn("display: none", hidden)

    def test_show_and_hide_functions_exist(self):
        self.assertIn("function showWorkOverlay(", self.js_source)
        self.assertIn("function hideWorkOverlay(", self.js_source)
        show = js_function(self.js_source, "showWorkOverlay")
        self.assertIn("work-message", show)
        self.assertIn("work-overlay", show)
        hide = js_function(self.js_source, "hideWorkOverlay")
        self.assertIn("work-overlay", hide)

    def test_run_ai_shows_the_overlay_before_ask_ai_and_hides_it_in_finally(self):
        body = js_function(self.js_source, "runAi")
        self.assertLess(body.index("showWorkOverlay("), body.index("ask_ai("))
        self.assertGreater(body.index("hideWorkOverlay("), body.index("finally"))

    def test_button_may_stay_disabled_but_carries_no_busy_state(self):
        body = js_function(self.js_source, "runAi")
        self.assertIn("button.disabled = true", body)
        self.assertNotIn("aria-busy", body)


class TestModelCapabilityIcons(UiContractTestCase):
    """S11/T18: the five context-bar icons reflect the selected model's
    capabilities live, the web checkbox is model-gated, and a rejected
    selection reverts with a visible error."""

    def setUp(self):
        super().setUp()
        self.css_source = APP_CSS.read_text(encoding="utf-8")

    def test_capability_icons_carry_data_capability_in_fixed_order(self):
        caps = self.tree.find(node_id="context-bar").find_all(cls="cap")
        self.assertEqual([cap.attrs.get("data-capability") for cap in caps],
                         ["chat", "reasoning", "web", "vision", "text_files"])

    def test_capability_css_has_active_and_inactive_states(self):
        self.assertIsNotNone(css_block(self.css_source, ".cap"), ".cap rule missing")
        off = css_block(self.css_source, ".cap.off")
        self.assertIsNotNone(off, ".cap.off rule missing")
        self.assertIn("color:", off)

    def test_catalog_entries_retain_capabilities(self):
        body = js_function(self.js_source, "applyModelCatalog")
        self.assertIn("capabilities", body)
        self.assertIn("catalogCapabilities", self.js_source)

    def test_selection_updates_icon_states_tooltips_and_web_checkbox(self):
        body = js_function(self.js_source, "applySelectedModelCapabilities")
        self.assertIn("data-capability", body)
        self.assertIn('classList.toggle("off"', body)
        self.assertIn("title", body)
        self.assertIn('$("web-search")', body)
        self.assertIn("checked", body)
        self.assertIn("disabled", body)

    def test_same_web_model_preserves_the_checkbox_choice(self):
        body = js_function(self.js_source, "applySelectedModelCapabilities")
        self.assertIn("lastCapabilityModel", body)

    def test_selection_gates_attachments_and_surfaces_the_summary(self):
        body = js_function(self.js_source, "applySelectedModelCapabilities")
        self.assertIn('$("attach-files")', body)
        window = self.handler_window("model-select")
        self.assertIn("refreshAttachmentSummary()", window)

    def test_rejected_selection_reverts_and_shows_the_error(self):
        window = self.handler_window("model-select")
        self.assertIn("set_selected_model", window)
        self.assertIn("!result.ok", window)
        self.assertIn("selectedModelId", window)  # revert target
        self.assertIn("setStatus(result.error)", window)


class TestArtboardS11Parity(UiContractTestCase):
    """S11/T18: the chosen artboard proves the same two fixes — always
    rotating spinner and live capability icons."""

    def setUp(self):
        super().setUp()
        artboard = ROOT.parent / "design" / "txt-original-parity" \
            / "01-original-layout.html"
        self.artboard = artboard.read_text(encoding="utf-8")

    def test_artboard_reduced_motion_keeps_the_rotation(self):
        index = self.artboard.index("prefers-reduced-motion: reduce")
        segment = self.artboard[index:index + 300]
        self.assertIn(".work-spinner", segment)
        self.assertNotIn("animation: none", segment)
        self.assertIn("infinite", segment)

    def test_artboard_capability_icons_carry_data_capability(self):
        self.assertEqual(self.artboard.count('data-capability="'), 5)

    def test_artboard_has_an_off_state_and_model_switch_proof(self):
        self.assertIn(".cap.off", self.artboard)
        self.assertIn("model-combo", self.artboard)
        self.assertIn("applySelectedModelCapabilities", self.artboard)


class TestSliderFillAlignment(UiContractTestCase):
    """S10/T17 (C): the slider fill always agrees with its thumb — painted at
    startup (after the persisted speed is applied) and on every programmatic
    value change. JS paint is authoritative; the CSS fallback only matches
    the named mismatch (speed=100 over 50–200 → 33.33%)."""

    def setUp(self):
        super().setUp()
        self.css_source = APP_CSS.read_text(encoding="utf-8")

    def _ready_handler(self):
        start = self.js_source.index('"pywebviewready"')
        end = self.js_source.index("});", start)
        return self.js_source[start:end]

    def test_track_fallback_matches_speed_100_over_50_200(self):
        track = css_block(
            self.css_source,
            'input[type="range"]::-webkit-slider-runnable-track')
        self.assertIsNotNone(track, "webkit track rule missing")
        self.assertIn("var(--fill, 33.33%)", track)
        self.assertNotIn("var(--fill, 25%)", track)

    def test_startup_applies_the_persisted_speed_before_the_first_paint(self):
        handler = self._ready_handler()
        self.assertIn("config.speed", handler)
        self.assertIn("speedSlider.value", handler)
        self.assertIn("speedLabel(", handler)
        self.assertLess(handler.index("speedSlider.value"),
                        handler.index("paintSlider(speedSlider)"))

    def test_startup_paints_both_sliders(self):
        handler = self._ready_handler()
        self.assertIn("paintSlider(speedSlider)", handler)
        self.assertIn('paintSlider($("seek"))', handler)

    def test_apply_speech_state_paints_the_seek_slider_after_value_and_max(self):
        body = js_function(self.js_source, "applySpeechState")
        self.assertLess(body.index("seek.max ="), body.index("paintSlider(seek)"))
        self.assertLess(body.index("seek.value ="), body.index("paintSlider(seek)"))


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


class TestPlayVoiceAutoSwitch(UiContractTestCase):
    """S13 rule 2 (T20): Play detects the text language and the UI reflects
    the automatic voice switch (selector + Hombre/Mujer + Español/Inglés)."""

    def py_function_source(self, class_name, function_name):
        tree = ast.parse(self.py_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for child in node.body:
                    if isinstance(child, ast.FunctionDef) \
                            and child.name == function_name:
                        return ast.unparse(child)
        raise AssertionError(f"{class_name}.{function_name} not found")

    def test_start_speech_detects_the_language_and_resolves_the_default_voice(self):
        body = self.py_function_source("Api", "start_speech")
        self.assertIn("_auto_switch_voice_for_text(text)", body)
        self.assertIn("voice_switched", body)
        self.assertIn("voice_language", body)
        self.assertIn("voice", body)
        switch = self.py_function_source("Api", "_auto_switch_voice_for_text")
        self.assertIn("language.detect_language(text)", switch)
        self.assertIn("voices.default_voice_for(", switch)
        self.assertIn("settings.set_speech_voice(", switch)

    def test_play_handler_awaits_start_speech_and_applies_the_switch(self):
        window = self.handler_window("speech-play")
        self.assertIn("await api.start_speech(speechText", window)
        self.assertIn("applyVoiceSwitch(", window)

    def test_play_handler_prepares_the_preview_before_reading_the_words(self):
        # S14 rule 2: the default tab is Editor, so pressing Play before ever
        # opening Vista previa used to read alignment words from an unwrapped
        # preview (empty getSpeechWords → no highlight and no click targets).
        window = self.handler_window("speech-play")
        render = window.index("await renderPreviewNow()")
        start = window.index("api.start_speech")
        self.assertLess(render, start)
        # The wrapped words are read as start_speech's argument, i.e. strictly
        # after the awaited render (render → wrap → getSpeechWords → start).
        self.assertIn(
            "api.start_speech(speechText, getSpeechWords())", window)
        # txt.ps1 parity: Play reads what Vista previa shows (the AI answer
        # or the editor) as plain text, and shows that tab.
        self.assertIn("previewContent()", window)
        self.assertIn("get_preview_plain_text()", window)
        self.assertIn('setTab("preview")', window)
        self.assertIn("No hay contenido en Vista previa para leer.", window)

    def test_apply_voice_switch_updates_the_selector_and_the_toggles(self):
        # S15/T22: the toggles move through the shared setVoiceToggles helper
        # and the selector is re-rendered filtered by the new combination.
        body = js_function(self.js_source, "applyVoiceSwitch")
        self.assertIn("voice_switched", body)
        self.assertIn('const select = $("voice-select")', body)
        self.assertIn("select.value = result.voice", body)
        self.assertIn("setVoiceToggles(", body)
        self.assertIn("renderFilteredVoiceCatalog(", body)
        self.assertIn("voice_language", body)

    def test_apply_voice_switch_gates_on_ok_and_reuses_the_status_helper(self):
        body = js_function(self.js_source, "applyVoiceSwitch")
        self.assertIn("result.ok", body)
        self.assertIn("setStatus(result.message)", body)


class TestVoiceSelectorFiltersByActiveToggles(UiContractTestCase):
    """S15/T22: the voice selector shows ONLY the voices of the active
    language+gender combination (never both languages); every toggle click
    re-renders it, selects and persists that combination's legacy default,
    and a matching Play language never mutates the filter."""

    def py_function_source(self, class_name, function_name):
        tree = ast.parse(self.py_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for child in node.body:
                    if isinstance(child, ast.FunctionDef) \
                            and child.name == function_name:
                        return ast.unparse(child)
        raise AssertionError(f"{class_name}.{function_name} not found")

    def test_list_voices_returns_the_legacy_defaults_map(self):
        body = self.py_function_source("Api", "list_voices")
        self.assertIn("'defaults'", body)
        self.assertIn("self._voice_defaults_map(", body)
        # One source of truth: the legacy priority table stays in voices.py.
        helper = self.py_function_source("Api", "_voice_defaults_map")
        self.assertIn("voices.default_voice_for(", helper)
        self.assertIn("'es', 'en'", helper)
        self.assertIn("'Male', 'Female'", helper)

    def test_apply_voice_catalog_never_renders_groups_or_all_voices(self):
        body = js_function(self.js_source, "applyVoiceCatalog")
        self.assertIn("renderFilteredVoiceCatalog(", body)
        self.assertNotIn("optgroup", body)
        self.assertNotIn("VOICE_GROUP_LABELS", self.js_source)
        # The voice selector never renders both languages (optgroups are
        # legitimate only in the model selector).
        render = js_function(self.js_source, "renderFilteredVoiceCatalog")
        self.assertNotIn("optgroup", render)
        self.assertNotIn("VOICE_GROUP_LABELS", render)

    def test_rendered_options_match_gender_and_culture_only(self):
        body = js_function(self.js_source, "renderFilteredVoiceCatalog")
        self.assertIn("voice.gender === gender", body)
        self.assertIn(".slice(0, 2) === culture", body)
        # One source of truth: the legacy default comes from the backend
        # defaults map, with the first matching voice as fallback.
        self.assertIn("voiceDefaults[", body)
        self.assertIn("filtered[0].name", body)
        self.assertIn("select.disabled = true", body)
        self.assertNotIn("optgroup", body)

    def test_initial_load_derives_the_toggles_from_the_persisted_voice(self):
        body = js_function(self.js_source, "applyVoiceCatalog")
        self.assertIn("voiceRecordOf(", body)
        derive = body.index("setVoiceToggles(record.gender")
        render = body.index("renderFilteredVoiceCatalog(")
        self.assertLess(derive, render)

    def test_render_keeps_the_persisted_voice_when_it_is_compatible(self):
        body = js_function(self.js_source, "renderFilteredVoiceCatalog")
        self.assertIn("keepPreferred", body)
        self.assertIn("!chooseDefault", body)

    def test_toggle_click_rerenders_and_persists_exactly_once(self):
        body = js_function(self.js_source, "selectVoiceByFilter")
        self.assertIn("renderFilteredVoiceCatalog(null, true)", body)
        self.assertEqual(body.count("set_speech_voice"), 1)
        toggle = js_function(self.js_source, "activateVoiceToggle")
        self.assertIn("aria-pressed", toggle)
        self.assertIn("selectVoiceByFilter(silent)", toggle)

    def test_apply_voice_switch_sets_toggles_before_rendering_and_never_persists(self):
        body = js_function(self.js_source, "applyVoiceSwitch")
        self.assertIn("setVoiceToggles(", body)
        self.assertIn("renderFilteredVoiceCatalog(", body)
        # The backend already persisted the switched voice: no second write.
        self.assertNotIn("set_speech_voice", body)
        self.assertLess(body.index("setVoiceToggles("),
                        body.index("renderFilteredVoiceCatalog("))


class TestReplayHighlightAndNativeAttachments(UiContractTestCase):
    def test_speech_tick_sends_the_current_preview_words_for_replay_validation(self):
        body = js_function(self.js_source, "speechTick")
        self.assertIn("speech_tick(getSpeechWords())", body)

    def test_missing_replay_highlight_clears_a_stale_word(self):
        body = js_function(self.js_source, "applySpeechState")
        self.assertIn('state.provider === "Replay"', body)
        self.assertIn("clearSpeechProgress()", body)

    def test_attach_button_uses_one_native_dialog_directly(self):
        window = self.handler_window("attach-files")
        self.assertIn("open_attachment_dialog()", window)
        self.assertNotIn('$("attach-input").click()', window)

    def test_modern_pywebview_file_dialog_enums_replace_deprecated_constants(self):
        self.assertIn("webview.FileDialog.OPEN", self.py_source)
        self.assertIn("webview.FileDialog.FOLDER", self.py_source)
        self.assertNotIn("webview.OPEN_DIALOG", self.py_source)
        self.assertNotIn("webview.SAVE_DIALOG", self.py_source)


class TestBridgeReadinessAndControlledErrors(UiContractTestCase):
    """S18/T25: no silent dead buttons — bridge readiness is centralized with
    a visible Spanish status, the pywebviewready startup sequence survives any
    rejected call, every fire-and-forget bridge promise has controlled
    rejection handling, Play surfaces {ok:false,message}, and Consultar
    always requests web research regardless of the optional checkbox."""

    def ready_handler(self):
        start = self.js_source.index('"pywebviewready"')
        end = self.js_source.index("});", start)
        return self.js_source[start:end]

    def full_handler(self, control_id):
        """Whole addEventListener handler of one control (beyond the shared
        700-char window), from the binding to its closing `});`."""
        start = self.js_source.index(f'$("{control_id}").addEventListener')
        end = self.js_source.index("});", start)
        return self.js_source[start:end]

    # -- centralized bridge readiness ----------------------------------------

    def test_bridge_readiness_is_centralized_with_a_visible_spanish_status(self):
        self.assertIn("function bridgeApi(", self.js_source)
        require = js_function(self.js_source, "requireBridge")
        self.assertIn("setStatus(", require)  # visible, never a silent return
        # The Spanish status lives in the shared constant requireBridge shows.
        self.assertIn("BRIDGE_NOT_READY", require)
        self.assertIn("puente de la aplicación", self.js_source)
        # The shared helper documents the null contract for callers.
        self.assertIn("requireBridge() returns null", self.js_source)

    def test_no_handler_keeps_the_silent_dead_button_guard(self):
        self.assertNotIn(
            "if (!window.pywebview || !window.pywebview.api) return;",
            self.js_source)
        self.assertNotIn(
            "window.pywebview && window.pywebview.api;\n    if (!api) return;",
            self.js_source)

    # -- central async call/error wrapper ------------------------------------

    def test_central_safe_call_wrapper_catches_rejections(self):
        body = js_function(self.js_source, "safeCall")
        self.assertIn("requireBridge()", body)
        self.assertIn("catch", body)
        self.assertIn("setStatus(", body)  # rejections become visible errors

    def test_fire_and_forget_public_actions_route_through_safe_call(self):
        for control_id, call in (
            ("theme-toggle", "set_theme"),
            ("speech-pause", "pause_speech"),
            ("speech-replay", "replay_start"),
            ("speech-stop", "stop_speech"),
            ("speed", "set_speech_speed"),
            ("close-app", "close_app"),
            ("clear-chat", "clear_attachments"),
            ("attach-files", "open_attachment_dialog"),
        ):
            window = self.handler_window(control_id)
            self.assertIn("safeCall(", window, control_id)
            self.assertIn(call, window, control_id)

    def test_busy_exports_surface_a_controlled_error(self):
        body = js_function(self.js_source, "withBusy")
        self.assertLess(body.index("catch (_) {"), body.index("finally {"))

    def test_ai_actions_surface_a_controlled_error(self):
        body = js_function(self.js_source, "runAi")
        self.assertLess(body.index("catch (_) {"), body.index("finally {"))

    def test_voice_selection_surfaces_a_controlled_error(self):
        for name in ("selectVoiceByFilter", "refreshVoices", "saveSettingsForm",
                     "loadStartupModels"):
            body = js_function(self.js_source, name)
            # Either its own catch or the central safeCall wrapper.
            self.assertTrue("catch" in body or "safeCall(" in body, name)

    # -- startup sequence is independently survivable -------------------------

    def test_startup_settings_failure_does_not_kill_startup(self):
        handler = self.ready_handler()
        settings_try = handler.index("try {")
        get_settings = handler.index("get_settings")
        self.assertLess(settings_try, get_settings)
        self.assertIn("catch", handler[get_settings:get_settings + 400])

    def test_startup_version_failure_does_not_kill_the_rest(self):
        handler = self.ready_handler()
        version_zone = handler[handler.index("app_version") - 200:]
        self.assertIn("catch", version_zone[:400])
        # Independent initialization still runs after a rejected version call.
        self.assertIn("setStatus(\"Listo.\")", handler)
        self.assertIn("loadStartupModels(", handler)
        self.assertIn("setInterval(speechTick, 120)", handler)

    def test_startup_model_load_keeps_its_catch(self):
        body = js_function(self.js_source, "loadStartupModels")
        self.assertLess(body.index("update_models()"), body.index("catch"))

    # -- Play surfaces {ok:false,message} -------------------------------------

    def test_play_surfaces_start_speech_failure_messages(self):
        handler = self.full_handler("speech-play")
        self.assertIn("applyVoiceSwitch(", handler)
        self.assertIn("!result.ok", handler)
        self.assertIn("setStatus(result.message", handler)

    def test_play_catches_rejected_start_speech_calls(self):
        handler = self.full_handler("speech-play")
        self.assertIn("catch", handler)
        self.assertIn("setStatus(", handler)

    # -- Consultar always researches the web ----------------------------------

    def test_web_search_follows_only_the_checkbox(self):
        """txt.ps1 parity: Consultar does not force the web search."""
        body = js_function(self.js_source, "runAi")
        self.assertIn('const useWeb = $("web-search").checked;', body)
        self.assertNotIn('action === "consult" ||', body)

    def test_busy_text_names_provider_and_model_like_the_legacy_app(self):
        body = js_function(self.js_source, "runAi")
        self.assertIn("} · ${display}...`", body)
        self.assertNotIn("Investigando en la web", body)

    def test_consult_keeps_the_question_and_shows_the_answer_bar(self):
        body = js_function(self.js_source, "runAi")
        self.assertIn("showAiResult(result.text)", body)
        self.assertIn("setEditorText(result.text)", body)
        index = INDEX.read_text(encoding="utf-8")
        for expected in ('id="preview-result-bar"',
                         "Respuesta de la IA. Tu consulta sigue en el Editor.",
                         ">Llevar al editor<", ">Ver el editor<"):
            self.assertIn(expected, index)
        self.assertIn("Respuesta llevada al editor. Ctrl+Z recupera tu consulta.",
                      self.js_source)
        self.assertIn("Vista previa muestra otra vez el contenido del Editor.",
                      self.js_source)

    def test_preview_renders_the_preview_content_not_just_the_editor(self):
        body = js_function(self.js_source, "renderPreviewNow")
        self.assertIn("api.render_preview(previewContent())", body)

    def test_update_buttons_use_a_declared_bridge(self):
        for button in ("check-update", "apply-update"):
            window = self.handler_window(button)
            self.assertNotRegex(window, r"await api\.(check_for_updates|apply_update)")

    def test_other_ai_actions_keep_the_web_checkbox(self):
        body = js_function(self.js_source, "runAi")
        self.assertIn('$("web-search").checked', body)


if __name__ == "__main__":
    unittest.main()
