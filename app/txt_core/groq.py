"""Groq HTTP layer and request-body shapes, ported from txt.ps1 (New-GroqRequestJson,
Get-GroqHeaders, Invoke-GroqRequest, Get-GroqModelsFromApi).

Stdlib only: urllib.request. No third-party dependencies so the module runs
unchanged on Windows and macOS.
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any, Mapping, Sequence

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"

# Cloudflare (error 1010) rejects Python's default urllib User-Agent signature;
# the legacy .NET HttpClient was never affected. Identify the app instead.
USER_AGENT = "txt-preview/26.11 (cross-platform desktop app)"

ERR_MISSING_API_KEY = "Falta configurar la API key de Groq."
ERR_MISSING_BRIDGE_PASSWORD = "Falta la contraseña del bridge de {label} ({env_var})."
ERR_HTTP_STATUS = "Groq devolvió el estado HTTP {status}."
# S17: TLS/connection failures (macOS Python 3.14 "Basic Constraints of CA cert
# not marked critical") surface as a controlled Spanish message — never a raw
# urllib traceback. Verification is never disabled; truststore provides native
# system trust instead.
ERR_CONNECTION = "Error de conexión con Groq (fallo de red/TLS): {reason}"

IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def connection_reason(error: urllib.error.URLError) -> str:
    """Human-readable reason of a URLError (an SSLError, an OSError or a str)."""
    return str(getattr(error, "reason", None) or error)


def image_media_type(extension: str) -> str:
    return IMAGE_MEDIA_TYPES.get(extension.lower(), "image/jpeg")


def groq_headers(api_key: str) -> dict[str, str]:
    trimmed = (api_key or "").strip()
    if not trimmed:
        raise RuntimeError(ERR_MISSING_API_KEY)
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {trimmed}",
    }


def attachment_text(name: str, content: str) -> str:
    """Legacy format of one text attachment inside the combined prompt."""
    return f"---\nArchivo adjunto: {name}\n---\n{content}"


def combined_prompt_text(prompt: str, text_attachments: Sequence[Mapping[str, str]]) -> str:
    parts = [prompt]
    for attachment in text_attachments:
        parts.append(attachment_text(attachment["name"], attachment["content"]))
    return "\n\n".join(parts)


def _image_data_url(path: str) -> str:
    with open(path, "rb") as handle:
        base64_data = base64.b64encode(handle.read()).decode("ascii")
    media_type = image_media_type(path[path.rfind("."):]) if "." in path else "image/jpeg"
    return f"data:{media_type};base64,{base64_data}"


def build_groq_body(prompt: str, selected_model: str, web_search: bool,
                    capabilities: Mapping[str, Any],
                    text_attachments: Sequence[Mapping[str, str]] = (),
                    image_paths: Sequence[str] = ()) -> dict:
    """OpenAI-shaped chat body for api.groq.com (txt.ps1 New-GroqRequestJson)."""
    combined = combined_prompt_text(prompt, text_attachments)
    if image_paths:
        content: Any = [{"type": "text", "text": combined}]
        for image_path in image_paths:
            content.append({"type": "image_url", "image_url": {"url": _image_data_url(image_path)}})
    else:
        content = combined
    body: dict[str, Any] = {
        "model": selected_model,
        "messages": [{"role": "user", "content": content}],
    }
    if web_search and capabilities.get("web"):
        # Same as txt.ps1: server-side browser_search with tool_choice "auto".
        # "required" made Groq reject answers where gpt-oss chose not to
        # search (HTTP 400 tool_use_failed). Sources are read from
        # message.executed_tools in the response; reasoning_effort "low" as
        # recommended for gpt-oss models.
        body["tools"] = [{"type": "browser_search"}]
        body["tool_choice"] = "auto"
        body["reasoning_effort"] = "low"
    return body


def build_bridge_body(prompt: str, selected_model: str, bridge_key: str,
                      text_attachments: Sequence[Mapping[str, str]] = (),
                      image_paths: Sequence[str] = ()) -> dict:
    """Body for local subscription bridges: {model, message, images?}."""
    body: dict[str, Any] = {
        "model": selected_model[len(bridge_key) + 1:],
        "message": combined_prompt_text(prompt, text_attachments),
    }
    if image_paths:
        images = []
        for image_path in image_paths:
            with open(image_path, "rb") as handle:
                base64_data = base64.b64encode(handle.read()).decode("ascii")
            media_type = image_media_type(image_path[image_path.rfind("."):]) if "." in image_path else "image/jpeg"
            images.append({"mimeType": media_type, "data": base64_data})
        body["images"] = images
    return body


def _http_error_payload(error: urllib.error.HTTPError) -> dict:
    """Groq's JSON error object ({message, code, ...}); empty when unreadable."""
    try:
        raw = error.read()
        data = json.loads(raw.decode("utf-8", errors="replace")) if raw else {}
    except (ValueError, OSError, AttributeError):
        return {}
    detail = data.get("error") if isinstance(data, dict) else None
    return detail if isinstance(detail, dict) else {}


def _http_error_message(status: int, payload: Mapping[str, Any]) -> str:
    message = ERR_HTTP_STATUS.format(status=status)
    detail = str(payload.get("message") or "").strip()
    if detail:
        message = f"{message[:-1]}: {detail}"
    return message


def _open_chat(api_key: str, body: dict, timeout_seconds: int) -> dict:
    request = urllib.request.Request(
        GROQ_CHAT_URL,
        data=json.dumps(body, ensure_ascii=True).encode("utf-8"),
        method="POST",
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("Authorization", f"Bearer {api_key}")
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def post_chat(api_key: str, body: dict, timeout_seconds: int = 600) -> dict:
    """POST the chat body to api.groq.com and return the parsed JSON."""
    try:
        return _open_chat(api_key, body, timeout_seconds)
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            _http_error_message(error.code, _http_error_payload(error))) from error
    except urllib.error.URLError as error:
        # S17: connection/TLS failure — controlled message, verification intact.
        raise RuntimeError(ERR_CONNECTION.format(reason=connection_reason(error))) from error


def extract_response_text(response: Mapping[str, Any]) -> str:
    """Legacy Get-AiResponseText minus the PS encoding repair (Python already decodes UTF-8).

    T25/S18: also accepts the real Groq built-in-tool final response shape
    (message.content plus executed_tools/annotations). The readable answer is
    kept, citation markers are stripped, and the only visible evidence added is
    the payload's own annotation citations — URLs are never fabricated.
    """
    from .citations import builtin_tool_sources, strip_citation_markers  # keeps module tree flat

    choices = response.get("choices")
    if not choices:
        text = response.get("text", "")
        return strip_citation_markers(str(text))
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str):
        content = "" if content is None else str(content)
    text = strip_citation_markers(content)
    sources = builtin_tool_sources(message)
    if sources:
        text = text.rstrip("\n") + "\n\nFuentes:\n" + "\n".join(sources)
    return text
