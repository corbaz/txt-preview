"""Model catalog and capability mapping, ported from txt.ps1 (availableGroqModels,
Get-GroqModelCapabilities, Get-GroqModelsFromApi)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from .groq import GROQ_MODELS_URL, ERR_HTTP_STATUS, connection_reason

# S17: TLS/connection failures on /models startup become a controlled message
# so update_models can fall back to the static catalog without a traceback.
ERR_MODELS_CONNECTION = (
    "No se pudo conectar con Groq para cargar los modelos (fallo de conexión/TLS): {reason}"
)

DEFAULT_MODEL_ID = "openai/gpt-oss-120b"


@dataclass(frozen=True)
class ModelInfo:
    id: str
    owned_by: str
    context_window: int
    active: bool = True


@dataclass(frozen=True)
class Capabilities:
    chat: bool
    reasoning: bool
    web: bool
    vision: bool
    text_files: bool
    summary: str

    def as_dict(self) -> dict[str, object]:
        return {
            "chat": self.chat,
            "reasoning": self.reasoning,
            "web": self.web,
            "vision": self.vision,
            "text_files": self.text_files,
            "summary": self.summary,
        }


# Fallback catalog when the API list is unavailable; same order as the legacy selector.
DEFAULT_GROQ_MODELS: tuple[ModelInfo, ...] = (
    ModelInfo("allam-2-7b", "SDAIA", 4096),
    ModelInfo("canopylabs/orpheus-arabic-saudi", "Canopy Labs", 4000),
    ModelInfo("canopylabs/orpheus-v1-english", "Canopy Labs", 4000),
    ModelInfo("meta-llama/llama-prompt-guard-2-22m", "Meta", 512),
    ModelInfo("meta-llama/llama-prompt-guard-2-86m", "Meta", 512),
    ModelInfo("openai/gpt-oss-120b", "OpenAI", 131072),
    ModelInfo("openai/gpt-oss-20b", "OpenAI", 131072),
    ModelInfo("openai/gpt-oss-safeguard-20b", "OpenAI", 131072),
    ModelInfo("qwen/qwen3.8-27b", "Alibaba Cloud", 131072),
    ModelInfo("whisper-large-v3", "OpenAI", 448),
    ModelInfo("whisper-large-v3-turbo", "OpenAI", 448),
)

BRIDGE_DOCS_SUMMARY = "Documentos (texto, PDF, Word, PowerPoint)"


def bridge_capabilities(label: str, vision: bool) -> Capabilities:
    features = [f"Suscripción {label} (bridge local)", "Texto"]
    if vision:
        features.append("Visión · Imágenes (máx. 3)")
    features.append(BRIDGE_DOCS_SUMMARY)
    return Capabilities(True, True, False, vision, True, " · ".join(features))


def model_capabilities(model_id: str, bridge_label: str | None = None,
                       bridge_vision: bool | None = None) -> Capabilities:
    """Legacy Get-GroqModelCapabilities rules; bridge entries need their vision flag.

    S11: the map is conservative and keyed by exact official model IDs — an
    unknown ID stays all-false/unclassified instead of being guessed.
    """
    if bridge_label is not None:
        return bridge_capabilities(bridge_label, bool(bridge_vision))
    if model_id == "qwen/qwen3.8-27b":
        return Capabilities(
            True, True, False, True, True,
            "Texto · Razonamiento · Visión · Imágenes (máx. 3) · Documentos (texto, PDF, Word, PowerPoint)",
        )
    if model_id in ("openai/gpt-oss-120b", "openai/gpt-oss-20b"):
        return Capabilities(
            True, True, True, False, True,
            "Texto · Razonamiento · Búsqueda web · Documentos (texto, PDF, Word, PowerPoint)",
        )
    if model_id in ("llama-3.1-8b-instant", "llama-3.3-70b-versatile"):
        return Capabilities(
            True, False, False, False, True,
            "Texto · Documentos (texto, PDF, Word, PowerPoint)",
        )
    if model_id == "minimaxai/minimax-m2.7":
        return Capabilities(
            True, True, False, False, True,
            "Texto · Razonamiento · Documentos (texto, PDF, Word, PowerPoint)",
        )
    if model_id == "meta-models/muse-spark-open":
        return Capabilities(
            True, True, False, True, True,
            "Texto · Razonamiento · Visión · Imágenes (máx. 3) · Documentos (texto, PDF, Word, PowerPoint)",
        )
    if model_id == "allam-2-7b":
        return Capabilities(True, False, False, False, True, "Texto · Árabe · Documentos (texto, PDF, Word, PowerPoint)")
    if model_id == "openai/gpt-oss-safeguard-20b":
        return Capabilities(False, False, True, False, False, "Seguridad · Moderación · Búsqueda web")
    if model_id.startswith("whisper-"):
        return Capabilities(False, False, False, False, False, "Transcripción y traducción de audio")
    if model_id.startswith("canopylabs/orpheus-"):
        return Capabilities(False, False, False, False, False, "Texto a voz")
    if model_id.startswith("meta-llama/llama-prompt-guard-"):
        return Capabilities(False, False, False, False, False, "Clasificación de seguridad de prompts")
    return Capabilities(False, False, False, False, False, "Capacidades no catalogadas")


def fetch_models(api_key: str) -> list[ModelInfo]:
    """GET /openai/v1/models; raises with the legacy error string on HTTP errors."""
    if not api_key or not api_key.strip():
        raise RuntimeError("Ingresá una API key de Groq.")
    request = urllib.request.Request(GROQ_MODELS_URL, method="GET")
    from .groq import USER_AGENT
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(ERR_HTTP_STATUS.format(status=error.code)) from error
    except urllib.error.URLError as error:
        # S17: connection/TLS failure — controlled message, verification intact.
        raise RuntimeError(
            ERR_MODELS_CONNECTION.format(reason=connection_reason(error))) from error
    return [
        ModelInfo(
            id=item["id"],
            owned_by=item.get("owned_by", ""),
            context_window=item.get("context_window", 0),
            active=item.get("active", True),
        )
        for item in payload.get("data", [])
        if item.get("active", True) is not False
    ]
