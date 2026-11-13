"""TXT Preview — cross-platform entry point.

Runs the same application on Windows (WebView2) and macOS (WKWebView)
through pywebview. Legacy Windows-only app: ../txt.ps1.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import urllib.error
from pathlib import Path

import webview

ROOT = Path(__file__).resolve().parent
APP = ROOT
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from txt_core import bridges, groq, models, prompts, settings, updater
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
DEFAULT_THEME = "dark"

# Legacy Update-BridgeModels status strings (txt.ps1:1721-1760).
MSG_NEEDS_API_KEY = settings.MSG_NEEDS_API_KEY
BRIDGE_GROUP_ORDER = ("Groq", "Claude", "Codex", "Gemini")


def _tcp_listening(port: int, timeout_seconds: float = 0.5) -> bool:
    """Legacy Test-BridgeListening: a short TCP probe tells a stopped bridge
    apart without waiting for the refused-connection HTTP timeout."""
    try:
        with socket.socket() as probe:
            probe.settimeout(timeout_seconds)
            probe.connect(("127.0.0.1", int(port)))
        return True
    except OSError:
        return False

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

    def __init__(self, settings_dir: str | None = None,
                 legacy_dir: str | None = None,
                 api_encrypt=None, api_decrypt=None) -> None:
        self.engine = SpeechEngine(emit=self._on_engine_message)
        self._pending_click: int | None = None
        self._speech_words = ""
        self._speech_speed = 100
        # ---- Persisted settings (T10/S2) ----------------------------------
        # Paths and crypto are injectable so tests never touch the real
        # settings folder nor the real DPAPI/keychain APIs.
        self._settings_dir = settings_dir
        self._legacy_dir = legacy_dir
        self._api_encrypt = api_encrypt
        self._api_decrypt = api_decrypt
        self._theme = DEFAULT_THEME
        self._speech_voice = DEFAULT_SPEECH_VOICE
        self._models_cache: dict | None = None
        self._bridge_model_vision: dict[str, bool] = {}
        self._last_message = ""
        # ---- AI actions (T5) --------------------------------------------
        self._attachments: list = []
        self._attachments_lock = threading.Lock()
        self._selected_model = models.DEFAULT_MODEL_ID
        # Session bridge passwords; get_bridge_password falls back to the
        # process env, in-memory values and the bridge password file.
        self._bridge_passwords: dict[str, str] = {}
        self._speech_language = "es"
        # ---- In-app update (T11/S4) -----------------------------------------
        self._update_status: updater.UpdateStatus | None = None
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

    # ---- Persisted settings (T10/S2) ---------------------------------------
    def initialize_settings(self) -> dict:
        """Legacy Import-AppSettings: migrate the legacy DPAPI settings once,
        then apply theme, speed, voice and selected model to the session."""
        migrated = settings.migrate_legacy_settings(
            self._settings_dir, legacy_dir=self._legacy_dir,
            encrypt=self._api_encrypt, decrypt=self._api_decrypt)
        loaded = settings.load_settings(self._settings_dir)
        self._theme = str(loaded.get("theme") or DEFAULT_THEME)
        self._speech_voice = str(loaded.get("speech_voice") or DEFAULT_SPEECH_VOICE)
        self.set_speech_speed(int(loaded.get("speed") or 100))
        self._selected_model = str(loaded.get("selected_model")
                                   or models.DEFAULT_MODEL_ID)
        return {
            "migrated": migrated,
            "theme": self._theme,
            "speech_voice": self._speech_voice,
            "speed": self._speech_speed,
            "selected_model": self._selected_model,
            "api_key_masked": self.get_api_key_masked(),
        }

    def get_settings(self) -> dict:
        return {
            "theme": self._theme,
            "speech_voice": self._speech_voice,
            "speed": self._speech_speed,
            "selected_model": self._selected_model,
            "api_key_masked": self.get_api_key_masked(),
        }

    def set_theme(self, theme: str) -> dict:
        self._theme = theme if theme in ("light", "dark") else DEFAULT_THEME
        settings.set_theme(self._theme, self._settings_dir)
        return {"ok": True, "theme": self._theme}

    def _resolve_api_key(self) -> str:
        """Stored settings key first, GROQ_API_KEY env fallback (legacy order)."""
        try:
            stored = settings.get_api_key(
                self._settings_dir, decrypt=self._api_decrypt).strip()
        except Exception:
            stored = ""
        if stored:
            return stored
        return os.environ.get("GROQ_API_KEY", "")

    def set_api_key(self, key: str) -> dict:
        """Legacy Save-AppSettings for the Groq key: encrypt and persist."""
        settings.set_api_key(key, self._settings_dir, encrypt=self._api_encrypt)
        self._models_cache = None  # the model catalog depends on the key
        return {"ok": True, "masked": self.get_api_key_masked()}

    def get_api_key_masked(self) -> str:
        key = self._resolve_api_key()
        if not key:
            return ""
        return f"{key[:4]}...{key[-4:]}"

    # ---- Model catalog (T10/S2) ---------------------------------------------
    def update_models(self) -> dict:
        """Legacy Initialize-ModelSources / Update-BridgeModels: Groq /models
        plus a live probe of every local bridge, cached for the session."""
        if self._models_cache is not None:
            return self._models_cache
        api_key = self._resolve_api_key()
        if not api_key.strip():
            return {"ok": False, "error": MSG_NEEDS_API_KEY,
                    "models": [], "bridge_status": {}}
        fetch_error: str | None = None
        try:
            groq_models = models.fetch_models(api_key)
        except RuntimeError as error:
            fetch_error = str(error)
            groq_models = list(models.DEFAULT_GROQ_MODELS)  # static catalog
        catalog: list[dict] = [
            {"id": item.id, "name": item.id, "provider": "Groq",
             "vision": models.model_capabilities(item.id).vision}
            for item in groq_models
        ]
        bridge_status: dict[str, str] = {}
        self._bridge_model_vision = {}
        for bridge in bridges.LOCAL_BRIDGES:
            bridge_models, status = self._probe_bridge(bridge)
            bridge_status[bridge.key] = status
            for entry in bridge_models:
                self._bridge_model_vision[entry["id"]] = entry["vision"]
            catalog.extend(bridge_models)
        result: dict = {"ok": True, "models": catalog,
                        "bridge_status": bridge_status}
        if fetch_error:
            result["error"] = fetch_error
        self._models_cache = result
        return result

    def _probe_bridge(self, bridge: bridges.Bridge) -> tuple[list[dict], str]:
        """Legacy Update-BridgeModels per bridge: GET /models with the resolved
        password and the same status strings."""
        password = bridges.get_bridge_password(bridge, self._bridge_passwords)
        if not _tcp_listening(bridge.port):
            return [], "Apagado"
        try:
            status_code, text = bridges.bridge_http(
                bridge, "GET", "/models", None, 10, password)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return [], f"Sin respuesta: {error}"
        if status_code == 401:
            status = ("Falta la contraseña" if not password.strip()
                      else "Contraseña incorrecta")
            return [], status
        if status_code != 200:
            return [], f"Error HTTP {status_code}"
        try:
            model_list = json.loads(text) if text else []
        except json.JSONDecodeError as error:
            return [], f"Sin respuesta: {error}"
        if not isinstance(model_list, list):
            model_list = []
        entries: list[dict] = []
        for model in model_list:
            if not isinstance(model, dict) or not model.get("id"):
                continue
            # Claude Code always reads images, Codex says it per model (legacy switch).
            vision = (bridge.key == "claude"
                      or (bridge.key == "codex" and model.get("vision") is True))
            entries.append({
                "id": f"{bridge.key}:{model['id']}",
                "name": str(model.get("name") or model.get("id")),
                "provider": bridge.label,
                "bridge": bridge.key,
                "vision": vision,
            })
        count = len(model_list)
        status = ("Conectado (1 modelo)" if count == 1
                  else f"Conectado ({count} modelos)")
        return entries, status

    def render_preview(self, text: str) -> str:
        """Sanitized markdown HTML for Vista previa."""
        self._preview_text = text
        return render_markdown(text)

    # ---- AI actions (T5/S1) -------------------------------------------------
    def get_selected_model(self) -> str:
        return self._selected_model

    def set_selected_model(self, model_id: str) -> dict:
        self._selected_model = model_id
        settings.set_selected_model(model_id, self._settings_dir)
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
            # Vision flag comes from the live /models probe (legacy Update-BridgeModels).
            return models.model_capabilities(
                self._selected_model, bridge.label,
                self._bridge_model_vision.get(self._selected_model, False))
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
        api_key = self._resolve_api_key()
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

    # ---- In-app update (T11/S4) ---------------------------------------------
    def check_for_updates(self) -> dict:
        """Legacy Update-AppUpdateControls check: origin/main VERSION vs local."""
        self._update_status = updater.check_update(REPO)
        return self._update_status.as_dict()

    def apply_update(self) -> dict:
        """Legacy Install-AppUpdate: verify, then git pull --ff-only."""
        self._update_status = updater.apply_update(REPO)
        return self._update_status.as_dict()

    def _startup_update_check(self, delay: float = 3.0) -> None:
        """Legacy Invoke-StartupUpdateCheck: runs once off the UI thread,
        stays silent unless an update is available (the UI notice is the
        only signal; offline or non-Git installs stay quiet)."""
        time.sleep(delay)
        try:
            status = self.check_for_updates()
        except Exception:
            return
        if status.get("state") != updater.STATE_AVAILABLE:
            return
        window = getattr(self, "_window", None)
        if window is not None:
            window.evaluate_js(
                "window.txtUI && window.txtUI.applyUpdateStatus("
                + json.dumps(status) + ")")

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
                text, self._speech_voice_display(), self._speech_voice,
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
    def _speech_voice_display(self) -> str:
        """Friendly display name; the id itself for non-default voices."""
        if self._speech_voice == DEFAULT_SPEECH_VOICE:
            return DEFAULT_SPEECH_VOICE_DISPLAY
        return self._speech_voice

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
                text, self._speech_voice_display(), self._speech_voice,
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
    api.initialize_settings()  # legacy migration + theme/speed/voice/model
    # Legacy startupUpdateTimer: one non-blocking check ~3s after startup.
    threading.Thread(target=api._startup_update_check, daemon=True).start()
    webview.start(private_mode=False)


if __name__ == "__main__":
    create_app()
