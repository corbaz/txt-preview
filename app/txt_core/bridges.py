"""Local subscription bridges, ported from txt.ps1:1550-1770.

Bridges are local servers from the web-chat repo. They only listen on
127.0.0.1 and share one contract: Basic auth (user = key), GET /models and
POST /chat. Their models are listed as "<key>:<bridge model id>" so every AI
action can route by the id alone.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class Bridge:
    key: str
    label: str
    port: int


LOCAL_BRIDGES: tuple[Bridge, ...] = (
    Bridge(key="claude", label="Claude", port=4098),
    Bridge(key="codex", label="Codex", port=4094),
    Bridge(key="gemini", label="Gemini", port=4092),
)


def get_bridge(model_id: str) -> Bridge | None:
    """Return the bridge owning this model id, or None for plain Groq models."""
    for bridge in LOCAL_BRIDGES:
        if model_id.startswith(f"{bridge.key}:"):
            return bridge
    return None


def strip_bridge_prefix(model_id: str, bridge: Bridge) -> str:
    """Bridge body model id: the selector id minus the '<key>:' prefix."""
    return model_id[len(bridge.key) + 1:]


def bridge_env_var_name(bridge: Bridge) -> str:
    return f"{bridge.key.upper()}_BRIDGE_PASSWORD"


def _prompting_base_dir() -> str:
    """Base dir of the bridge apps' data folders, per platform.

    Windows mirrors the legacy %LOCALAPPDATA%\\prompting path; on macOS the
    convention is ~/Library/Application Support.
    """
    if sys.platform == "win32":
        return os.path.join(os.environ.get("LOCALAPPDATA", ""), "prompting")
    home = os.path.expanduser("~")
    return os.path.join(home, "Library", "Application Support", "prompting")


def bridge_password_file(bridge: Bridge) -> str:
    return os.path.join(_prompting_base_dir(), f"{bridge.key}-bridge", "password.txt")


def get_bridge_password(bridge: Bridge, in_memory: dict[str, str] | None = None) -> str:
    """Password resolution order: process env, user env, in-memory, then file."""
    name = bridge_env_var_name(bridge)
    candidates = [
        os.environ.get(name, ""),
        os.environ.get(name, ""),  # user env merged with process env by os.environ
        (in_memory or {}).get(bridge.key, ""),
    ]
    for candidate in candidates:
        if candidate and candidate.strip():
            return candidate.strip()
    password_file = bridge_password_file(bridge)
    if os.path.isfile(password_file):
        try:
            with open(password_file, encoding="utf-8-sig") as handle:
                content = handle.read().strip()
            if content:
                return content
        except OSError:
            pass
    return ""


def bridge_basic_auth_header(bridge: Bridge, password: str) -> str:
    credentials = f"{bridge.key}:{password}"
    token = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def bridge_http(bridge: Bridge, method: str, path: str, body: str | None,
                timeout_seconds: int, password: str) -> tuple[int, str]:
    """HTTP against 127.0.0.1:<port>; returns (status, utf-8 text)."""
    url = f"http://127.0.0.1:{bridge.port}{path}"
    request = urllib.request.Request(url, method=method)
    request.add_header("Authorization", bridge_basic_auth_header(bridge, password))
    data = body.encode("utf-8") if body else None
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, data=data, timeout=timeout_seconds) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:  # non-2xx still carries a body
        return error.code, error.read().decode("utf-8", errors="replace")


def bridge_chat(bridge: Bridge, body: dict, password: str, timeout_seconds: int = 600) -> dict:
    """POST /chat; raises with the legacy error strings."""
    try:
        status, text = bridge_http(
            bridge, "POST", "/chat", json.dumps(body, ensure_ascii=True),
            timeout_seconds, password,
        )
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RuntimeError(
            f"{bridge.label}: el bridge no responde en 127.0.0.1:{bridge.port}."
        ) from error
    try:
        data = json.loads(text) if text else None
    except json.JSONDecodeError:
        data = None
    if status != 200:
        detail = data.get("error") if isinstance(data, dict) and data.get("error") else f"HTTP {status}"
        raise RuntimeError(f"{bridge.label}: {detail}")
    if data is None:
        raise RuntimeError(f"{bridge.label}: el bridge devolvió una respuesta que no es JSON.")
    return data
