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

IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


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
        body["tools"] = [{"type": "browser_search"}]
        body["tool_choice"] = "auto"
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


def post_chat(api_key: str, body: dict, timeout_seconds: int = 600) -> dict:
    """POST the chat body to api.groq.com and return the parsed JSON."""
    request = urllib.request.Request(
        GROQ_CHAT_URL,
        data=json.dumps(body, ensure_ascii=True).encode("utf-8"),
        method="POST",
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(ERR_HTTP_STATUS.format(status=error.code)) from error


def extract_response_text(response: Mapping[str, Any]) -> str:
    """Legacy Get-AiResponseText minus the PS encoding repair (Python already decodes UTF-8)."""
    from .citations import strip_citation_markers  # local import keeps module tree flat

    choices = response.get("choices")
    if not choices:
        text = response.get("text", "")
        return strip_citation_markers(str(text))
    return strip_citation_markers(str(choices[0]["message"]["content"]))
