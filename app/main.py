"""TXT Preview — cross-platform entry point.

Runs the same application on Windows (WebView2) and macOS (WKWebView)
through pywebview. Legacy Windows-only app: ../txt.ps1.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import webview

ROOT = Path(__file__).resolve().parent
APP = ROOT
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from txt_core import bridges, groq, models, prompts
from txt_core.attachments import (
    IMAGE_EXTENSIONS,
    TEXT_EXTENSIONS,
    DOCUMENT_EXTENSIONS,
    Kind,
    add_attachment,
    attachment_summary,
)
from txt_core.exports import (
    MSG_MP3_EMPTY,
    MSG_PDF_EMPTY,
    export_mp3 as export_mp3_file,
    export_pdf as export_pdf_file,
    markdown_to_text,
)
from txt_core.markdown import render_markdown
from txt_core.speech.engine import SpeechEngine

REPO = ROOT.parent
WWW = ROOT / "www"

VERSION_FILE = REPO / "VERSION"

# Edge voice catalog lands in a later step; this is the default reading voice.
DEFAULT_SPEECH_VOICE = "es-ES-ElviraNeural"
DEFAULT_SPEECH_VOICE_DISPLAY = "Elvira (es-ES)"
SPEECH_SPEED_MIN = 50
SPEECH_SPEED_MAX = 200

# Legacy Show-Message / Set-StatusText strings for the AI actions (txt.ps1 ~6340-6580).
ERR_API_CONNECTION = "Error al conectar con la API."
MSG_ADDED_ATTACHMENTS = (
    "Los adjuntos visibles sobre el editor se enviarán en la próxima acción de IA."
)
MSG_CLEARED_ATTACHMENTS = "Se quitaron los archivos adjuntos del contexto."
INPUT_MESSAGES = {
    "consult": "Ingresá una consulta en el Editor o adjuntá al menos un archivo.",
    "summarize": "Ingresá contenido en el Editor o adjuntá al menos un archivo.",
    "correct": "Ingresá texto en el Editor o adjuntá al menos un archivo.",
    "translate_en_es": "Ingresá texto en el Editor o adjuntá al menos un archivo.",
    "translate_es_en": "Ingresá texto en el Editor o adjuntá al menos un archivo.",
}


def document_extension_group(extension: str) -> str | None:
    """Which capability an extension needs, mirroring the legacy add loop."""
    extension = extension.lower()
    if extension in IMAGE_EXTENSIONS:
        return "image"
    if extension in TEXT_EXTENSIONS:
        return "text"
    if extension in DOCUMENT_EXTENSIONS:
        return "document"
    return None


def read_version() -> str:
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    return "dev"


class Api:
    """Bridge exposed to the frontend as window.pywebview.api."""

    def __init__(self) -> None:
        self.engine = SpeechEngine(emit=self._on_engine_message)
        self._pending_click: int | None = None
        self._speech_words = ""
        self._speech_speed = 100
        self._last_message = ""
        # ---- AI actions (T5) --------------------------------------------
        self._attachments: list = []
        self._attachments_lock = threading.Lock()
        self._selected_model = models.DEFAULT_MODEL_ID
        # Session bridge passwords; get_bridge_password falls back to the
        # process env and (later steps) the stored settings.
        self._bridge_passwords: dict[str, str] = {}
        self._speech_language = "es"
        # ---- Exports (T6) ---------------------------------------------------
        # The markdown text last rendered in Vista previa: exports and the
        # clipboard buttons work on this, not on the editor (legacy
        # Get-PreviewContent).
        self._preview_text = ""

    # ---- Existing bridge ---------------------------------------------------
    def app_version(self) -> str:
        return read_version()

    def platform(self) -> str:
        return sys.platform

    def render_preview(self, text: str) -> str:
        """Sanitized markdown HTML for Vista previa."""
        self._preview_text = text
        return render_markdown(text)

    # ---- AI actions (T5/S1) -------------------------------------------------
    def get_selected_model(self) -> str:
        return self._selected_model

    def set_selected_model(self, model_id: str) -> dict:
        self._selected_model = model_id
        return {"ok": True, "model": model_id}

    def add_attachments(self, paths) -> dict:
        """Legacy Add-Attachment loop: dedupe, capability gates, extract text now."""
        added: list[str] = []
        errors: list[str] = []
        capabilities = self._selected_capabilities()
        with self._attachments_lock:
            for path in paths:
                try:
                    group = document_extension_group(os.path.splitext(path)[1])
                    if group == "image" and not capabilities.vision:
                        raise ValueError("El modelo elegido no admite imágenes.")
                    if group == "text" and not capabilities.text_files:
                        raise ValueError(
                            "El modelo elegido no admite documentos de texto en esta aplicación."
                        )
                    if group == "document" and not capabilities.text_files:
                        raise ValueError(
                            "El modelo elegido no admite documentos en esta aplicación."
                        )
                    attachment = add_attachment(self._attachments, path)
                    if attachment is not None:
                        added.append(attachment.name)
                except (ValueError, OSError) as error:
                    errors.append(f"No se pudo adjuntar: {error}")
        return {
            "added": added,
            "errors": errors,
            "summary": self.get_attachment_summary(),
        }

    def clear_attachments(self) -> dict:
        with self._attachments_lock:
            self._attachments.clear()
        return {
            "ok": True,
            "message": MSG_CLEARED_ATTACHMENTS,
            "summary": self.get_attachment_summary(),
        }

    def get_attachment_summary(self) -> str:
        with self._attachments_lock:
            names = [attachment.name for attachment in self._attachments]
        return attachment_summary(names, self._provider_label())

    def _provider_label(self) -> str:
        bridge = bridges.get_bridge(self._selected_model)
        return bridge.label if bridge else "Groq"

    def _selected_capabilities(self) -> models.Capabilities:
        bridge = bridges.get_bridge(self._selected_model)
        if bridge:
            # Bridge vision detection (legacy probe of GET /models) lands with T10.
            return models.model_capabilities(self._selected_model, bridge.label, False)
        return models.model_capabilities(self._selected_model)

    def ask_ai(self, action: str, web_search: bool = False, text: str = "") -> dict:
        """Run one of Consultar/Resumir/Corregir/Traducir; returns {ok, text?, error?}.

        editor_action tells the UI what to do with the result: keep (consult)
        or replace (summarize/correct/translate), as in the legacy handlers.
        """
        input_message = INPUT_MESSAGES.get(action)
        if not input_message:
            return {"ok": False, "error": f"Acción de IA desconocida: {action}"}
        with self._attachments_lock:
            has_attachments = bool(self._attachments)
        if not (text or "").strip() and not has_attachments:
            return {"ok": False, "error": input_message}
        try:
            response = self._send_ai_request(self._build_prompt(action, text), bool(web_search))
            result_text = groq.extract_response_text(response)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except Exception:
            return {"ok": False, "error": ERR_API_CONNECTION}
        return self._ai_result(action, result_text)

    def _build_prompt(self, action: str, text: str) -> str:
        if action == "consult":
            return prompts.consult_prompt(text)
        if action == "summarize":
            return prompts.summarize_prompt(text)
        if action == "correct":
            return prompts.correct_prompt(text)
        if action == "translate_es_en":
            return prompts.translate_prompt(text, "español", "inglés")
        return prompts.translate_prompt(text, "inglés", "español")

    def _send_ai_request(self, prompt: str, web_search: bool) -> dict:
        """Route to a local bridge or api.groq.com, raising ValueError for
        configuration problems and RuntimeError for request failures."""
        with self._attachments_lock:
            text_attachments = [
                {"name": attachment.name, "content": attachment.content}
                for attachment in self._attachments
                if attachment.kind != Kind.IMAGE
            ]
            image_paths = [
                attachment.path for attachment in self._attachments
                if attachment.kind == Kind.IMAGE
            ]
        bridge = bridges.get_bridge(self._selected_model)
        if bridge:
            password = bridges.get_bridge_password(bridge, self._bridge_passwords)
            if not password:
                raise ValueError(groq.ERR_MISSING_BRIDGE_PASSWORD.format(
                    label=bridge.label, env_var=bridges.bridge_env_var_name(bridge),
                ))
            body = groq.build_bridge_body(
                prompt, self._selected_model, bridge.key, text_attachments, image_paths,
            )
            return bridges.bridge_chat(bridge, body, password)
        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key.strip():
            raise ValueError(groq.ERR_MISSING_API_KEY)
        capabilities = models.model_capabilities(self._selected_model).as_dict()
        body = groq.build_groq_body(
            prompt, self._selected_model, web_search, capabilities,
            text_attachments, image_paths,
        )
        return groq.post_chat(api_key, body)

    def _ai_result(self, action: str, result_text: str) -> dict:
        """Legacy post-actions: what the UI does with the AI result."""
        result: dict = {
            "ok": True,
            "text": result_text,
            "editor_action": "keep",
            "speech_language": self._speech_language,
        }
        # Vista previa will show this answer; exports follow the preview.
        self._preview_text = result_text
        if action == "consult":
            result["message"] = (
                "Respuesta lista en Vista previa. Tu consulta sigue en el Editor."
            )
        elif action == "summarize":
            result["editor_action"] = "replace"
            result["message"] = "Resumen profesional listo en Vista previa."
        elif action == "correct":
            result["editor_action"] = "replace"
            result["clipboard"] = True
            result["message"] = (
                "Se copió al portapapeles. Usá Ctrl+V para pegarlo en cualquier lugar."
            )
        else:  # translate_es_en / translate_en_es
            result["editor_action"] = "replace"
            self._speech_language = "en" if action == "translate_es_en" else "es"
            result["speech_language"] = self._speech_language
            result["message"] = "Traducción lista en Vista previa."
        return result

    def open_attachment_dialog(self) -> dict:
        """Native open dialog returning real paths; used when the page's
        <input type=file> cannot hand over full paths."""
        window = getattr(self, "_window", None)
        if window is None:
            return {"added": [], "errors": [], "summary": self.get_attachment_summary()}
        file_types = (
            "Documentos e imágenes (*.txt;*.md;*.pdf;*.docx;*.pptx;*.png;*.jpg;*.jpeg;*.webp;*.gif)",
            "Todos los archivos (*.*)",
        )
        chosen = window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=True, file_types=file_types,
        ) or []
        if not chosen:
            return {"added": [], "errors": [], "summary": self.get_attachment_summary()}
        return self.add_attachments(list(chosen))

    # ---- Preview exports (T6/S1) -------------------------------------------
    def get_preview_text(self) -> str:
        """Raw markdown of what Vista previa shows (legacy Copy MD)."""
        return self._preview_text

    def get_preview_plain_text(self) -> str:
        """Plain text of what Vista previa shows (legacy Convert-MarkdownToText)."""
        return markdown_to_text(self._preview_text)

    def export_pdf(self) -> dict:
        """Legacy Export-PreviewPdf, PyMuPDF instead of headless Edge."""
        if not self._preview_text.strip():
            return {"ok": False, "message": MSG_PDF_EMPTY}
        target = self._ask_save_path(
            "Guardar Vista previa como PDF", "txt-preview.pdf",
            ("Documento PDF (*.pdf)", "Todos los archivos (*.*)"),
        )
        if not target:
            return {"ok": False, "message": ""}
        try:
            export_pdf_file(self._preview_text, target)
        except RuntimeError as error:
            return {"ok": False, "message": str(error)}
        except Exception as error:  # keep the shell alive; report to the UI
            return {"ok": False, "message": f"No se pudo generar el PDF: {error}"}
        return {"ok": True, "path": target, "message": f"PDF guardado en {target}"}

    def export_mp3(self) -> dict:
        """Legacy Export-SpeechMp3 (Edge-only voices, S6)."""
        speech_text = markdown_to_text(self._preview_text)
        if not speech_text.strip():
            return {"ok": False, "message": MSG_MP3_EMPTY}
        target = self._ask_save_path(
            "Guardar lectura como MP3", "txt-preview.mp3",
            ("Audio MP3 (*.mp3)", "Todos los archivos (*.*)"),
        )
        if not target:
            return {"ok": False, "message": ""}
        try:
            export_mp3_file(speech_text, target, DEFAULT_SPEECH_VOICE,
                            self.engine.applied_speed)
        except RuntimeError as error:
            return {"ok": False, "message": str(error)}
        except Exception as error:  # keep the shell alive; report to the UI
            return {"ok": False, "message": f"No se pudo generar el MP3: {error}"}
        return {"ok": True, "path": target, "message": f"MP3 guardado en {target}"}

    def _ask_save_path(self, _title: str, suggested_name: str, file_types) -> str | None:
        """Native save dialog (legacy Select-ExportPath); None when cancelled."""
        window = getattr(self, "_window", None)
        if window is None:
            return None
        chosen = window.create_file_dialog(
            webview.SAVE_DIALOG, save_filename=suggested_name, file_types=file_types,
        )
        return chosen or None

    # ---- Speech (T4/S6) ----------------------------------------------------
    def _on_engine_message(self, level: str, message: str) -> None:
        self._last_message = message

    def start_speech(self, text: str, raw_words: str | None = None) -> dict:
        """Start an Edge reading of the editor text; raw_words are the preview spans."""
        try:
            self.engine.stop_voice_playback()
            self._speech_words = raw_words or ""
            self.engine.initialize_alignment(self._speech_words)
            self.engine.start_edge_session(
                text, DEFAULT_SPEECH_VOICE_DISPLAY, DEFAULT_SPEECH_VOICE,
                rate_percent=self._speech_speed,
            )
            return {"ok": True, "message": self._last_message}
        except Exception as error:  # keep the shell alive; report to the UI
            return {"ok": False, "message": str(error)}

    def stop_speech(self) -> dict:
        self.engine.stop_voice_playback()
        return {"ok": True, "message": self._last_message}

    def pause_speech(self) -> dict:
        self.engine.pause()
        return {"ok": True, "message": self._last_message}

    def resume_speech(self) -> dict:
        self.engine.resume()
        return {"ok": True, "message": self._last_message}

    def set_speech_speed(self, percent: int) -> dict:
        speed = max(SPEECH_SPEED_MIN, min(SPEECH_SPEED_MAX, int(percent)))
        self._speech_speed = speed
        self.engine.applied_speed = speed
        # Replay re-renders the same audio at the new tempo from the current
        # position (legacy Set-SpeechSpeed); an Edge reading picks the rate up
        # on the next jump/play.
        if self.engine.provider == "Replay" and self.engine.mode in ("Playing", "Paused"):
            was_paused = self.engine.mode == "Paused"
            position = self._replay_position()
            self.engine.start_replay_playback(position)
            if was_paused:
                self.engine.pause()
        return {"ok": True, "message": self._last_message}

    def replay_start(self, offset_seconds: float = 0.0) -> dict:
        try:
            self.engine.start_replay_playback(float(offset_seconds))
            return {"ok": True, "message": self._last_message}
        except Exception as error:
            return {"ok": False, "message": str(error)}

    def speech_click(self, word_index: int, text: str | None = None) -> dict:
        """Queue a preview-word click; text is the block-aware tail (legacy getSpeechTextFrom)."""
        try:
            index = int(word_index)
        except (TypeError, ValueError):
            index = -1
        self._pending_click = (index, text) if index >= 0 else None
        return {"ok": True}

    def speech_tick(self) -> dict:
        try:
            self.engine.poll()
        except Exception as error:
            self._last_message = str(error)
        click = self._pending_click
        self._pending_click = None
        if click is not None:
            self._move_speech_to_word(click[0], click[1])
        return self._speech_state()

    # ---- Speech internals --------------------------------------------------
    def _speech_state(self) -> dict:
        engine = self.engine
        cursor = engine.align_cursor
        highlight = cursor if cursor > engine.align_floor else None
        return {
            "mode": engine.mode,
            "provider": engine.provider,
            "highlight_word_index": highlight,
            "replay_position": round(self._replay_position(), 3),
            "replay_duration": round(engine.replay.duration, 3),
            "message": self._last_message,
        }

    def _replay_position(self) -> float:
        engine = self.engine
        if engine.provider != "Replay":
            return 0.0
        elapsed = engine.elapsed_seconds()
        if elapsed is None:
            return engine.replay_offset
        return min(engine.replay.duration,
                   engine.replay_offset + elapsed * engine.replay_tempo)

    def _move_speech_to_word(self, index: int, text: str | None = None) -> None:
        """Legacy Move-SpeechToWord: restart the reading from the clicked word."""
        engine = self.engine
        if engine.mode == "Idle" or engine.provider == "Replay" or index < 0:
            return
        if not text:
            words = self._speech_words.split("\n") if self._speech_words else []
            text = " ".join(words[index:])
        if not text.strip():
            return
        was_paused = engine.mode == "Paused"
        try:
            engine.stop_voice_playback()
            engine.reset_alignment(index - 1)
            engine.initialize_alignment(self._speech_words)
            engine.start_edge_session(
                text, DEFAULT_SPEECH_VOICE_DISPLAY, DEFAULT_SPEECH_VOICE,
                rate_percent=self._speech_speed,
            )
            if was_paused:
                engine.pause()
        except Exception as error:
            self._last_message = f"No se pudo saltar a la palabra elegida: {error}"


def create_app() -> None:
    api = Api()
    window = webview.create_window(
        "TXT Preview",
        str(WWW / "index.html"),
        js_api=api,  # speech engine lives on the bridge (T4)
        width=1100,
        height=760,
        min_size=(720, 480),
    )
    api._window = window
    webview.start(private_mode=False)


if __name__ == "__main__":
    create_app()
