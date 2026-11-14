"""TXT Preview — cross-platform entry point.

Runs the same application on Windows (WebView2) and macOS (WKWebView)
through pywebview. Legacy Windows-only app: ../txt.ps1.
"""
from __future__ import annotations

# S17: trust the native system certificate store (macOS Keychain / Windows
# store) before any network module loads. macOS Python 3.14 strict X509
# validation rejects a malformed system CA ("Basic Constraints of CA cert not
# marked critical") during Groq /models startup; truststore fixes it using the
# OS trust store without ever disabling verification. Required dependency —
# missing truststore fails loudly here; Doctor/install provides it.
import truststore
truststore.inject_into_ssl()

from bisect import bisect_right
import json
import os
import socket
import re
import subprocess
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

from txt_core import bridges, browser, clipboard, groq, language, models, prompts, settings, updater, webapp
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
    export_file_path,
    export_pdf as export_pdf_file,
    markdown_to_text,
)
from txt_core.markdown import render_markdown
from txt_core.speech import voices
from txt_core.speech.engine import HIGHLIGHT_LEAD_SECONDS, SpeechEngine
from txt_core.speech.marks import speech_words_key

REPO = ROOT.parent
WWW = ROOT / "www"

VERSION_FILE = REPO / "VERSION"

# Edge voice catalog lands in a later step; this is the default reading voice.
DEFAULT_SPEECH_VOICE = "es-CR-JuanNeural"  # txt.ps1 default: Hombre · Español
DEFAULT_SPEECH_VOICE_DISPLAY = "Edge · es-CR-JuanNeural (Male)"
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
# S11: capability gates speak before the request — never a silent tool omission.
MSG_MODEL_NOT_CHAT = "El modelo elegido no admite chat de texto. Elegí otro modelo para las acciones de IA."
MSG_MODEL_NO_WEB = "El modelo elegido no admite búsqueda web. Desmarcá «Usar web» o elegí otro modelo."
MSG_CONSULT_REQUIRES_WEB_MODEL = (
    "Consultar requiere búsqueda web. Selecciona un modelo GPT-OSS: "
    "openai/gpt-oss-120b u openai/gpt-oss-20b."
)
MSG_ADDED_ATTACHMENTS = (
    "Los adjuntos visibles sobre el editor se enviarán en la próxima acción de IA."
)
MSG_CLEARED_ATTACHMENTS = "Se quitaron los archivos adjuntos del contexto."
# Legacy Micrófono button (txt.ps1 6669-6678): Win+H toggles Windows speech
# dictation; Esc stops it.
MSG_DICTATION_ON = "Dictado activado. Presioná Esc para detenerlo."
MSG_DICTATION_FAILED = "No se pudo activar el dictado: {detail}"
MSG_DICTATION_MAC = ("El dictado es una función del sistema en macOS: activá el "
                     "dictado en Configuración del Sistema → Teclado y presioná "
                     "la tecla de dictado (micrófono).")
MSG_DICTATION_UNSUPPORTED = "El dictado nativo no está disponible en esta plataforma."
MSG_WINDOW_UNAVAILABLE = "La ventana no está disponible."
MSG_PREVIEW_EMPTY = "*No hay contenido para mostrar.*"
MSG_EDGE_TTS_OUTDATED = ("Las voces Edge necesitan una versión nueva de edge-tts. "
                         "Tocá «Actualizar voces» en Configuración.")
MSG_WINDOW_CLOSE_FAILED = "No se pudo cerrar la ventana: {detail}"
INPUT_MESSAGES = {
    "consult": "Ingresá una consulta en el Editor o adjuntá al menos un archivo.",
    "summarize": "Ingresá contenido en el Editor o adjuntá al menos un archivo.",
    "correct": "Ingresá texto en el Editor o adjuntá al menos un archivo.",
    "translate_en_es": "Ingresá texto en el Editor o adjuntá al menos un archivo.",
    "translate_es_en": "Ingresá texto en el Editor o adjuntá al menos un archivo.",
}


def _press_win_h() -> None:
    """Legacy Micrófono: hold Win, tap H, release Win (txt.ps1 6670-6674)."""
    import ctypes

    VK_LWIN = 0x5B  # txt.ps1 Keyboard.VK_LWIN
    VK_H = 0x48     # txt.ps1 Keyboard.VK_H
    KEYEVENTF_KEYDOWN = 0x0000
    KEYEVENTF_KEYUP = 0x0002
    user32 = ctypes.windll.user32
    user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYDOWN, 0)
    user32.keybd_event(VK_H, 0, KEYEVENTF_KEYDOWN, 0)
    time.sleep(0.1)  # legacy Start-Sleep -Milliseconds 100
    user32.keybd_event(VK_H, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)


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
        # S14/T21: pywebview dispatches JS API calls on different threads, so
        # every speech lifecycle entrypoint (and the poll tick) runs inside
        # this re-entrant lock: a stale poll inside a stop→start window used
        # to respawn old Ready audio and leave an orphan second voice.
        self._speech_lock = threading.RLock()
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
        # txt.ps1 never reads theme, speed or voice back: every launch starts
        # on Tema: Oscuro, 1,00x and the default Hombre · Español voice.
        self._theme = DEFAULT_THEME
        self._speech_voice = DEFAULT_SPEECH_VOICE
        self.set_speech_speed(100)
        # The saved model is ignored on purpose, as in txt.ps1: every launch
        # starts on openai/gpt-oss-120b.
        self._selected_model = models.DEFAULT_MODEL_ID
        self._bridge_passwords.update(settings.get_bridge_passwords(
            [bridge.key for bridge in bridges.LOCAL_BRIDGES],
            self._settings_dir, decrypt=self._api_decrypt))
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

    # ---- Voice catalog (T4/S6) ---------------------------------------------
    def _voice_defaults_map(self, catalog: list[dict[str, str]]) -> dict:
        """S15/T22: default voice for every language+gender combination,
        resolved by the legacy priority in voices.default_voice_for (single
        source of truth — the selector never duplicates the table in JS).
        None when a combination has no voice in the catalog."""
        return {
            f"{language}|{gender}": voices.default_voice_for(language, gender,
                                                             catalog)
            for language in ("es", "en")
            for gender in ("Male", "Female")
        }

    def list_voices(self, force_refresh: bool = False, runner=None) -> dict:
        """Legacy Get-EdgeVoiceCatalog: cache first; edge_tts --list-voices on
        a miss or force refresh. A failed refresh falls back to the last
        saved catalog; with no cache the legacy failure message wins.
        S15/T22: the result also carries `defaults`, the legacy default voice
        for each language+gender combination resolved against that catalog."""
        cached = [] if force_refresh else voices.load_voice_cache(self._settings_dir)
        if cached:
            return {"ok": True, "voices": cached,
                    "defaults": self._voice_defaults_map(cached)}
        try:
            fetched = voices.fetch_voice_catalog(
                self.engine.python_command, runner=runner)
        except RuntimeError as error:
            stale = voices.load_voice_cache(self._settings_dir)
            if stale:
                return {"ok": True, "voices": stale,
                        "defaults": self._voice_defaults_map(stale),
                        "warning": "No se pudo actualizar la lista de voces Edge; "
                                   "se usa el último catálogo guardado."}
            return {"ok": False, "voices": [], "error": str(error)}
        voices.save_voice_cache(fetched, self._settings_dir)
        return {"ok": True, "voices": fetched,
                "defaults": self._voice_defaults_map(fetched)}

    def set_speech_voice(self, name: str) -> dict:
        """Persist the selected Edge voice (legacy voiceCombo selection)."""
        voice = (name or "").strip() or DEFAULT_SPEECH_VOICE
        self._speech_voice = voice
        settings.set_speech_voice(voice, self._settings_dir)
        return {"ok": True, "voice": voice}

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
        plus a live probe of every local bridge, cached for the session.
        Without a Groq key the static catalog is listed and the bridges are
        still probed: a subscription bridge alone is a valid setup."""
        if self._models_cache is not None:
            return self._models_cache
        api_key = self._resolve_api_key()
        fetch_error: str | None = None
        groq_models = list(models.DEFAULT_GROQ_MODELS)  # static catalog
        if api_key.strip():
            try:
                groq_models = models.fetch_models(api_key)
            except RuntimeError as error:
                fetch_error = str(error)
        result = self._build_catalog(groq_models)
        if fetch_error:
            result["error"] = fetch_error
        self._models_cache = result
        return result

    def _build_catalog(self, groq_models: list) -> dict:
        """Legacy Show-GroqModels rows: Groq models sorted by id, then the
        models of every running bridge."""
        self._groq_models = list(groq_models)
        catalog: list[dict] = [
            {"id": item.id, "name": item.id, "provider": "Groq",
             "owned_by": item.owned_by,
             "context": (f"{int(item.context_window):,}".replace(",", ".")
                         if item.context_window is not None else "-"),
             "vision": models.model_capabilities(item.id).vision,
             # S11: the full capability dict travels with every catalog entry.
             "capabilities": models.model_capabilities(item.id).as_dict()}
            for item in sorted(groq_models, key=lambda model: model.id)
        ]
        bridge_status: dict[str, str] = {}
        self._bridge_model_vision = {}
        for bridge in bridges.LOCAL_BRIDGES:
            bridge_models, status = self._probe_bridge(bridge)
            bridge_status[bridge.key] = status
            for entry in bridge_models:
                self._bridge_model_vision[entry["id"]] = entry["vision"]
            catalog.extend(bridge_models)
        return {"ok": True, "models": catalog, "bridge_status": bridge_status}

    def _known_groq_models(self) -> list:
        return getattr(self, "_groq_models", None) or list(models.DEFAULT_GROQ_MODELS)

    @staticmethod
    def _bridge_summary(bridge_status: dict) -> str:
        """Legacy Get-BridgeStatusSummary."""
        return " · ".join(f"{bridge.label} {bridge_status.get(bridge.key, '')}"
                          for bridge in bridges.LOCAL_BRIDGES)

    def _apply_bridge_passwords(self, passwords: dict | None) -> None:
        """Legacy Sync-BridgePasswordsFromBoxes."""
        for bridge in bridges.LOCAL_BRIDGES:
            self._bridge_passwords[bridge.key] = str(
                (passwords or {}).get(bridge.key) or "").strip()

    def _persist_secrets(self, api_key: str) -> None:
        settings.set_api_key(api_key, self._settings_dir, encrypt=self._api_encrypt)
        settings.set_bridge_passwords(self._bridge_passwords, self._settings_dir,
                                      encrypt=self._api_encrypt)

    def get_settings_secrets(self) -> dict:
        """Values of the Configuración password boxes (shown masked, as the
        legacy app fills txtApiKey and the bridge boxes)."""
        return {"api_key": self._resolve_api_key(),
                "bridge_passwords": {bridge.key: self._bridge_passwords.get(bridge.key, "")
                                     for bridge in bridges.LOCAL_BRIDGES}}

    def save_settings_form(self, api_key: str, bridge_passwords: dict | None = None) -> dict:
        """Legacy Invoke-SaveSettings: persist the key and bridge passwords,
        then check the bridges again with them."""
        api_key = (api_key or "").strip()
        self._apply_bridge_passwords(bridge_passwords)
        if not api_key and not any(self._bridge_passwords.values()):
            return {"ok": False, "level": "error", "message":
                    "No se pudo guardar: Ingresá una API key de Groq o la contraseña de un bridge."}
        try:
            self._persist_secrets(api_key)
        except Exception as error:
            return {"ok": False, "level": "error",
                    "message": f"No se pudo guardar: {error}"}
        result = self._build_catalog(self._known_groq_models())
        self._models_cache = result
        system = "macOS" if sys.platform == "darwin" else "Windows"
        return {**result, "level": "info", "message":
                f"Configuración guardada de forma segura para este usuario de {system}. "
                f"Bridges: {self._bridge_summary(result['bridge_status'])}"}

    def refresh_models(self, api_key: str, bridge_passwords: dict | None = None) -> dict:
        """Legacy "Actualizar modelos": Groq /models with the key in the box
        (saved on success), then the bridges — probed even without a key."""
        api_key = (api_key or "").strip()
        self._apply_bridge_passwords(bridge_passwords)
        groq_models = self._known_groq_models()
        try:
            groq_models = models.fetch_models(api_key)
            self._persist_secrets(api_key)
            message = f"{len(groq_models)} modelos activos cargados desde Groq."
            level = "info"
        except Exception as error:
            message = f"No se pudieron actualizar los modelos de Groq: {error}"
            level = "warning"
        result = self._build_catalog(groq_models)
        self._models_cache = result
        return {**result, "level": level, "message":
                f"{message} Bridges: {self._bridge_summary(result['bridge_status'])}"}

    def recheck_bridges(self, bridge_passwords: dict | None = None) -> dict:
        """Leaving a bridge password box after changing it checks the bridges
        again right away (legacy passwordBox.Add_Leave)."""
        self._apply_bridge_passwords(bridge_passwords)
        result = self._build_catalog(self._known_groq_models())
        self._models_cache = result
        return result

    def edge_tts_version_label(self, runner=None) -> str:
        """Legacy Update-EdgeTtsVersionLabel."""
        python = self.engine.python_command
        if not python:
            return "Voces Edge: sin Python"
        run = runner or subprocess.run
        try:
            completed = run(
                [python, "-c", "import importlib.metadata as m; print(m.version('edge-tts'))"],
                capture_output=True, text=True, timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            version = completed.stdout.strip() if completed.returncode == 0 else ""
        except Exception:
            version = ""
        return (f"Voces Edge: edge-tts v{version}" if version
                else "Voces Edge: edge-tts no instalado")

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
            capabilities = models.model_capabilities(
                f"{bridge.key}:{model['id']}", bridge.label, vision)
            entries.append({
                "id": f"{bridge.key}:{model['id']}",
                "name": str(model.get("name") or model.get("id")),
                "provider": bridge.label,
                "owned_by": f"{bridge.label} (suscripción)",
                "context": "-",
                "bridge": bridge.key,
                "vision": vision,
                "capabilities": capabilities.as_dict(),
            })
        count = len(model_list)
        status = ("Conectado (1 modelo)" if count == 1
                  else f"Conectado ({count} modelos)")
        return entries, status

    def render_preview(self, text: str) -> str:
        """Sanitized markdown HTML for Vista previa. `text` is the preview
        content chosen by the UI (legacy Get-PreviewContent): the AI answer
        while one is shown, otherwise the editor text."""
        self._preview_text = text
        if not (text or "").strip():
            return render_markdown(MSG_PREVIEW_EMPTY)  # legacy Show-MarkdownPreview
        return render_markdown(text)

    def set_preview_content(self, text: str) -> dict:
        """Copy, PDF, MP3 and Play act on what Vista previa shows even when
        the tab was never opened: the UI hands the content over first."""
        self._preview_text = text or ""
        return {"ok": True}

    # ---- AI actions (T5/S1) -------------------------------------------------
    def get_selected_model(self) -> str:
        return self._selected_model

    def set_selected_model(self, model_id: str) -> dict:
        # S11: validate before persisting — a non-chat or unknown Groq model
        # never changes the session nor the saved settings. Bridge ids are
        # always chat models (their /models list feeds the selector live).
        if bridges.get_bridge(model_id) is None \
                and not models.model_capabilities(model_id).chat:
            return {"ok": False, "error": MSG_MODEL_NOT_CHAT, "model": model_id}
        self._selected_model = model_id
        settings.set_selected_model(model_id, self._settings_dir)
        # txt.ps1 Update-ModelCapabilityControls: image attachments are
        # removed when the new model cannot see images.
        if not self._selected_capabilities().vision:
            with self._attachments_lock:
                self._attachments = [attachment for attachment in self._attachments
                                     if attachment.kind != Kind.IMAGE]
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
        # S11: capability gates before any request — a non-chat model never
        # reaches the API, and a web request on a non-web model fails clearly
        # instead of silently dropping the browser_search tool.
        capabilities = self._selected_capabilities()
        if not capabilities.chat:
            return {"ok": False, "error": MSG_MODEL_NOT_CHAT}
        # Legacy Stop-SpeechForAiRequest: an AI request stops the reading and
        # drops the Repetir audio, which belongs to the previous text.
        self._stop_speech_for_ai_request()
        try:
            # txt.ps1: web search is used only when the checkbox is ticked and
            # the model supports it; any chat model can run every action.
            response = self._send_ai_request(self._build_prompt(action, text), bool(web_search))
            result_text = groq.extract_response_text(response)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except RuntimeError as error:
            # T25/S18: the exact controlled message from Groq (HTTP status,
            # TLS, model/tool rejection) or from a bridge reaches the UI;
            # it is never collapsed into the generic connection error.
            return {"ok": False, "error": str(error)}
        except Exception:
            return {"ok": False, "error": ERR_API_CONNECTION}
        return self._ai_result(action, result_text)

    def _stop_speech_for_ai_request(self) -> None:
        try:
            with self._speech_lock:
                self.engine.stop_voice_playback()
                self.engine._clear_replay_cache()
                self._last_message = ""
        except Exception:
            pass  # a broken engine must not block the AI request

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

    # ---- Portapapeles (T25/S18) ---------------------------------------------
    def read_clipboard(self, runner=None, platform: str | None = None) -> dict:
        """Pegar button: native OS clipboard through the bridge (WKWebView on
        macOS does not expose navigator.clipboard). Returns the {ok,...}
        bridge contract and never raises into pywebview."""
        try:
            text = clipboard.read_clipboard(platform=platform, runner=runner)
        except RuntimeError as error:
            return {"ok": False, "error": str(error)}
        return {"ok": True, "text": text}

    def write_clipboard(self, text: str, runner=None,
                        platform: str | None = None) -> dict:
        """Copiar MD/TXT and Corregir: copy through the native clipboard.
        Returns the {ok,...} bridge contract and never raises."""
        try:
            clipboard.write_clipboard(text or "", platform=platform,
                                      runner=runner)
        except RuntimeError as error:
            return {"ok": False, "error": str(error)}
        return {"ok": True}

    # ---- Micrófono dictation (T15/S8) ---------------------------------------
    def start_dictation(self) -> dict:
        """Micrófono button. Windows reproduces the legacy Win+H keybd_event
        sequence; macOS shows a clear user-facing instruction (never silently
        pretending success); other platforms report the limitation."""
        if sys.platform.startswith("win"):
            try:
                _press_win_h()
            except Exception as error:
                return {"ok": False,
                        "message": MSG_DICTATION_FAILED.format(detail=error)}
            return {"ok": True, "message": MSG_DICTATION_ON}
        if sys.platform == "darwin":
            try:
                subprocess.run(
                    ["osascript", "-e",
                     'display dialog "' + MSG_DICTATION_MAC
                     + '" with title "TXT Preview"'],
                    check=False, timeout=10, capture_output=True)
            except Exception as error:
                return {"ok": False,
                        "message": MSG_DICTATION_FAILED.format(detail=error)}
            return {"ok": True, "message": MSG_DICTATION_MAC}
        return {"ok": False, "message": MSG_DICTATION_UNSUPPORTED}

    # ---- Cerrar (T15/S8) -----------------------------------------------------
    def close_app(self) -> dict:
        """Cerrar button: stop any reading first so the audio never outlives
        the app (S12), then destroy the window (legacy $form.Close()). The
        stop→destroy sequence holds the speech lock (S14): the window is
        never destroyed while another thread is mid-stop."""
        window = getattr(self, "_window", None)
        if window is None:
            return {"ok": False, "message": MSG_WINDOW_UNAVAILABLE}
        with self._speech_lock:
            try:
                self.stop_speech()
            except Exception:  # a broken engine must not trap the app open
                pass
            try:
                window.destroy()
            except Exception as error:
                return {"ok": False,
                        "message": MSG_WINDOW_CLOSE_FAILED.format(detail=error)}
            return {"ok": True}

    # ---- Navegador (txt.ps1 Open-BrowserUrl / Initialize-BrowserView) -------
    def _embedded_browser(self) -> browser.EmbeddedBrowser:
        if getattr(self, "_browser", None) is None:
            self._browser = browser.EmbeddedBrowser(
                getattr(self, "_window", None),
                self._settings_dir or settings.settings_dir())
        return self._browser

    def browser_open(self, address: str) -> dict:
        """Navigate the Navegador tab; `unavailable` asks the UI to offer the
        default browser instead (legacy fallback dialog)."""
        url = browser.to_browser_url(address)
        if not url:
            return {"ok": False, "url": "", "message": browser.MSG_EMPTY_ADDRESS}
        try:
            self._embedded_browser().navigate(url)
        except Exception as error:
            return {"ok": False, "url": url, "unavailable": True,
                    "message": browser.MSG_UNAVAILABLE.format(detail=error)}
        return {"ok": True, "url": url, "message": browser.MSG_OPENING.format(url=url)}

    def browser_back(self) -> dict:
        self._embedded_browser().back()
        return {"ok": True}

    def browser_forward(self) -> dict:
        self._embedded_browser().forward()
        return {"ok": True}

    def browser_place(self, rect: dict, visible: bool) -> dict:
        """Put the native view over the Navegador page area, or hide it."""
        self._embedded_browser().place(rect, bool(visible))
        return {"ok": True}

    def browser_state(self) -> dict:
        return self._embedded_browser().state.snapshot()

    def browser_open_external(self, address: str) -> dict:
        """Legacy "Abrir en navegador": the system default browser."""
        url = browser.to_browser_url(address)
        if not url:
            return {"ok": False, "message": browser.MSG_NO_ADDRESS_TO_OPEN}
        import webbrowser
        webbrowser.open(url)
        return {"ok": True, "url": url, "message": browser.MSG_OPENING.format(url=url)}

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
            webview.FileDialog.OPEN, allow_multiple=True, file_types=file_types,
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
        target = self._ask_export_path("Elegí la carpeta donde guardar el PDF", "pdf")
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
        target = self._ask_export_path("Elegí la carpeta donde guardar el MP3", "mp3")
        if not target:
            return {"ok": False, "message": ""}
        try:
            export_mp3_file(speech_text, target, self._speech_voice,
                            self.engine.applied_speed)
        except RuntimeError as error:
            return {"ok": False, "message": str(error)}
        except Exception as error:  # keep the shell alive; report to the UI
            return {"ok": False, "message": f"No se pudo generar el MP3: {error}"}
        return {"ok": True, "path": target, "message": f"MP3 guardado en {target}"}

    def _ask_export_path(self, title: str, extension: str) -> str | None:
        """Legacy Select-ExportPath: ask only for the destination folder (an
        Explorer-style tree) and generate the file name; None when cancelled."""
        folder = self._ask_folder(title, self._last_export_folder())
        if not folder:
            return None
        self._export_folder = folder
        return export_file_path(folder, extension)

    def _last_export_folder(self) -> str:
        """The folder of the previous export, Documents the first time."""
        return getattr(self, "_export_folder", None) or os.path.join(
            os.path.expanduser("~"), "Documents")

    def _ask_folder(self, title: str, initial: str) -> str | None:
        window = getattr(self, "_window", None)
        if window is None:
            return None
        if sys.platform == "win32":
            try:
                return _windows_folder_tree(window, title, initial)
            except Exception:
                pass  # fall back to the pywebview folder dialog
        chosen = window.create_file_dialog(webview.FileDialog.FOLDER, directory=initial)
        if not chosen:
            return None
        return chosen if isinstance(chosen, str) else chosen[0]

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
    def _take_message(self) -> str:
        message, self._last_message = self._last_message, ""
        return message

    def _on_engine_message(self, level: str, message: str) -> None:
        self._last_message = self._edge_voice_message(message)

    def _edge_voice_message(self, message: str) -> str:
        """Legacy Show-EdgeVoiceError: Microsoft rejects the handshake of an
        outdated edge-tts with HTTP 403; that offers "Actualizar voces"."""
        if "WSServerHandshakeError" in message and re.search(r"\b403\b", message):
            self._voice_update_offered = True
            return MSG_EDGE_TTS_OUTDATED
        return message

    def update_edge_tts(self, runner=None) -> dict:
        """Legacy Update-EdgeTts: pip-upgrade edge-tts for the current user."""
        python = self.engine.python_command
        if not python:
            return {"ok": False, "label": self.edge_tts_version_label(),
                    "message": "Las voces Edge necesitan Python."}
        run = runner or subprocess.run
        try:
            completed = run(
                [python, "-m", "pip", "install", "--user", "--quiet", "--upgrade", "edge-tts"],
                capture_output=True, text=True, timeout=600,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            code, error_text = completed.returncode, (completed.stderr or "").strip()
        except Exception as error:
            code, error_text = -1, str(error)
        label = self.edge_tts_version_label(runner=runner)
        if code != 0:
            detail = (error_text.splitlines()[-1] if error_text
                      else f"pip terminó con código {code}.")
            return {"ok": False, "label": label,
                    "message": f"No se pudieron actualizar las voces Edge: {detail}"}
        self._voice_update_offered = False
        version = label.replace("Voces Edge: ", "", 1)
        return {"ok": True, "label": label,
                "message": f"Voces Edge actualizadas: {version}."}

    def start_speech(self, text: str, raw_words: str | None = None) -> dict:
        """Start an Edge reading of the editor text; raw_words are the preview
        spans. S13 rule 2: a text whose language differs from the selected
        voice language switches to that language's default voice (same
        gender) before the session starts; matching languages keep the
        chosen voice, and insufficient signal never switches. The whole
        stop→align→start transition runs under the speech lock (S14): a
        concurrent tick poll inside this window used to respawn old Ready
        audio behind the stop's back."""
        with self._speech_lock:
            try:
                self.engine.stop_voice_playback()
                switch = self._auto_switch_voice_for_text(text)
                self._speech_words = raw_words or ""
                self.engine.initialize_alignment(self._speech_words)
                self.engine.start_edge_session(
                    text, self._speech_voice_display(), self._speech_voice,
                    rate_percent=self._speech_speed,
                )
                record = self._voice_catalog_record(self._speech_voice)
                return {
                    "ok": True,
                    "message": switch["message"] if switch else self._last_message,
                    "voice": self._speech_voice,
                    "voice_display": self._speech_voice_display(),
                    "voice_language": self._voice_language_of(self._speech_voice,
                                                              record),
                    "voice_gender": record.get("gender") if record else None,
                    "voice_switched": switch is not None,
                }
            except Exception as error:  # keep the shell alive; report to the UI
                return {"ok": False, "message": str(error)}

    def _voice_catalog_record(self, name: str) -> dict | None:
        """Catalog entry of a voice, or None when it is not cached."""
        for voice in voices.load_voice_cache(self._settings_dir):
            if voice["name"] == name:
                return voice
        return None

    def _voice_language_of(self, name: str, record: dict | None) -> str | None:
        """es/en from the catalog culture, else the voice name prefix."""
        if record:
            return (record.get("culture") or "")[:2].lower() or None
        prefix = (name or "")[:3].lower()
        return prefix[:2] if prefix in ("es-", "en-") else None

    def _auto_switch_voice_for_text(self, text: str) -> dict | None:
        """S13 rule 2: resolve the automatic voice switch on Play. A detected
        language different from the voice language selects that language's
        default voice (same gender, legacy priority) and persists it like
        set_speech_voice does; None keeps the chosen voice (languages match
        or insufficient signal)."""
        detected = language.detect_language(text)
        if detected is None:
            return None
        catalog = voices.load_voice_cache(self._settings_dir)
        record = next((voice for voice in catalog
                       if voice["name"] == self._speech_voice), None)
        if self._voice_language_of(self._speech_voice, record) == detected:
            return None
        gender = record.get("gender") if record else None
        voice = voices.default_voice_for(detected, gender, catalog)
        if not voice or voice == self._speech_voice:
            return None
        self._speech_voice = voice
        settings.set_speech_voice(voice, self._settings_dir)
        return {
            "message": (f"Texto en {'inglés' if detected == 'en' else 'español'}"
                        f": se usó la voz {voice}."),
            "language": detected,
        }

    def stop_speech(self) -> dict:
        with self._speech_lock:
            self.engine.stop_voice_playback()
            self._last_message = ""  # nothing is playing any more
            return {"ok": True, "message": "Lectura detenida."}

    def pause_speech(self) -> dict:
        with self._speech_lock:
            self.engine.pause()
            return {"ok": True, "message": self._last_message}

    def resume_speech(self) -> dict:
        with self._speech_lock:
            self.engine.resume()
            return {"ok": True, "message": self._last_message}

    def set_speech_speed(self, percent: int) -> dict:
        speed = max(SPEECH_SPEED_MIN, min(SPEECH_SPEED_MAX, int(percent)))
        with self._speech_lock:
            self._speech_speed = speed
            if self.engine.provider == "Replay" and self.engine.mode in ("Playing", "Paused"):
                # Replay re-renders the same audio at the new tempo from the
                # current position (legacy Set-SpeechSpeed replay branch). S13
                # rule 1: the tempo is the slider speed current now, never the
                # speed the audio was generated with, so applied_speed moves
                # before the restart (start_replay_playback reads it).
                was_paused = self.engine.mode == "Paused"
                position = self._replay_position()
                self.engine.applied_speed = speed
                self.engine.start_replay_playback(position)
                if was_paused:
                    self.engine.pause()
            else:
                # Legacy Restart-ActiveSpeechPlayback: an Edge reading restarts
                # from the current position with the remaining text (engine).
                self.engine.set_speed(speed)
            return {"ok": True, "message": self._last_message}

    def replay_start(self, offset_seconds: float = 0.0) -> dict:
        with self._speech_lock:
            try:
                self.engine.start_replay_playback(float(offset_seconds))
                return {"ok": True, "message": self._last_message}
            except Exception as error:
                return {"ok": False, "message": str(error)}

    def speech_click(self, word_index: int, text: str | None = None) -> dict:
        """Queue a preview-word click; text is the block-aware tail (legacy
        getSpeechTextFrom). Queued under the speech lock and consumed by the
        next speech_tick atomically; a newer click overwrites an older one
        (latest wins, S14)."""
        try:
            index = int(word_index)
        except (TypeError, ValueError):
            index = -1
        with self._speech_lock:
            self._pending_click = (index, text) if index >= 0 else None
        return {"ok": True}

    def speech_tick(self, raw_words: str | None = None) -> dict:
        # The poll AND the pending-click processing share one lock hold (S14):
        # a click queued mid-tick is not dropped, and the tick can never see
        # half of another entrypoint's stop→start transition.
        with self._speech_lock:
            try:
                self.engine.poll()
            except Exception as error:
                self._last_message = self._edge_voice_message(str(error))
            click = self._pending_click
            self._pending_click = None
            if click is not None:
                self._move_speech_to_word(click[0], click[1])
            # Legacy Update-ReplayHighlight validates once per Repetir session
            # that the cached marks belong to the currently rendered preview.
            # start_replay_playback resets these flags before every replay/seek.
            if (self.engine.provider == "Replay"
                    and not self.engine.replay_highlight_checked
                    and raw_words is not None):
                self.engine.replay_highlight_checked = True
                self.engine.replay_highlight_valid = bool(raw_words) \
                    and speech_words_key(raw_words) == self.engine.replay.words_key
            return self._speech_state()

    # ---- Speech internals --------------------------------------------------
    def _speech_voice_display(self) -> str:
        """Friendly display name: legacy default label, catalog display
        (Edge · name (gender)) when known, else the voice id."""
        if self._speech_voice == DEFAULT_SPEECH_VOICE:
            return DEFAULT_SPEECH_VOICE_DISPLAY
        for voice in voices.load_voice_cache(self._settings_dir):
            if voice["name"] == self._speech_voice:
                return voice["display_name"]
        return self._speech_voice

    def _speech_state(self) -> dict:
        engine = self.engine
        if engine.provider == "Replay":
            highlight = None
            if (engine.mode in ("Playing", "Paused")
                    and engine.replay_highlight_checked
                    and engine.replay_highlight_valid
                    and engine.replay.mark_seconds
                    and engine.replay.mark_words):
                position = min(engine.replay.duration,
                               self._replay_position() + HIGHLIGHT_LEAD_SECONDS)
                mark_index = bisect_right(engine.replay.mark_seconds, position) - 1
                if 0 <= mark_index < len(engine.replay.mark_words):
                    highlight = engine.replay.mark_words[mark_index]
        else:
            cursor = engine.align_cursor
            highlight = cursor if cursor > engine.align_floor else None
        return {
            "mode": engine.mode,
            "provider": engine.provider,
            "highlight_word_index": highlight,
            "replay_position": round(self._replay_position(), 3),
            "replay_duration": round(engine.replay.duration, 3),
            "message": self._take_message(),
            "voice_update_offered": bool(getattr(self, "_voice_update_offered", False)),
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
                rate_percent=self._speech_speed, start_cursor=index - 1,
                cache_eligible=False,  # a jump is a partial reading (legacy)
            )
            if was_paused:
                engine.pause()
        except Exception as error:
            self._last_message = f"No se pudo saltar a la palabra elegida: {error}"


def _windows_folder_tree(window, title: str, initial: str) -> str | None:
    """WinForms FolderBrowserDialog in its classic tree form, shown on the UI
    thread of the pywebview form (same dialog as txt.ps1)."""
    from System import Func, Type
    from System.Windows.Forms import DialogResult, FolderBrowserDialog
    from webview.platforms.winforms import BrowserView
    form = BrowserView.instances[window.uid]
    chosen: list[str] = []

    def show():
        dialog = FolderBrowserDialog()
        dialog.Description = title
        dialog.ShowNewFolderButton = True
        # Newer .NET upgrades the dialog to a file-style window; keep the tree.
        for name, value in (("UseDescriptionForTitle", True), ("AutoUpgradeEnabled", False)):
            if hasattr(dialog, name):
                setattr(dialog, name, value)
        dialog.SelectedPath = initial
        try:
            if dialog.ShowDialog(form) == DialogResult.OK:
                chosen.append(str(dialog.SelectedPath))
        finally:
            dialog.Dispose()

    if form.InvokeRequired:
        form.Invoke(Func[Type](show))
    else:
        show()
    return chosen[0] if chosen else None


def create_app() -> None:
    api = Api()
    window = webview.create_window(
        "Corrector de Prompt",
        webapp.create_wsgi_app(WWW),  # no-store + stamped assets: never a stale UI
        js_api=api,  # speech engine lives on the bridge (T4)
        width=1100,
        height=760,
        min_size=(1300, 600),
        maximized=True,  # S8: the original app always starts maximized
    )
    api._window = window

    def _stop_speech_on_closing() -> None:
        # S12: closing through the OS button stops the audio too.
        try:
            api.stop_speech()
        except Exception:
            pass

    window.events.closing += _stop_speech_on_closing
    api.initialize_settings()  # legacy migration + theme/speed/voice/model
    # Legacy startupUpdateTimer: one non-blocking check ~3s after startup.
    threading.Thread(target=api._startup_update_check, daemon=True).start()
    webview.start(private_mode=False)


if __name__ == "__main__":
    create_app()
