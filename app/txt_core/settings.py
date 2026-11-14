"""Persisted settings and secret storage, ported from txt.ps1 (Import-AppSettings,
Save-AppSettings, legacy %LOCALAPPDATA%\\TXT Preview\\settings.json).

Cross-platform (S2): Windows uses %LOCALAPPDATA%\\TXT Preview with the API key
DPAPI-encrypted (base64 blob in api_key_enc, matching the legacy storage shape:
CryptProtectData over UTF-16-LE, the same bytes ConvertFrom-SecureString kept);
macOS uses ~/Library/Application Support/TXT Preview with the key in the OS
keychain through the `keyring` package; other platforms use ~/.local/share.
When keyring is unavailable the key falls back to a plaintext api_key field
flagged with "plaintext_key": true.

The DPAPI pair is a pure wrapper (dpapi_encrypt/dpapi_decrypt) so tests can
inject fake encrypt/decrypt functions and never touch the real Windows API.
"""
from __future__ import annotations

import base64
import binascii
import ctypes
import json
import os
import sys
from ctypes import wintypes

APP_DIR_NAME = "TXT Preview"
SETTINGS_FILE_NAME = "settings.json"

DEFAULT_MODEL_ID = "openai/gpt-oss-120b"
DEFAULT_THEME = "dark"
DEFAULT_SPEECH_VOICE = "es-ES-ElviraNeural"
DEFAULT_SPEED = 100

KEYRING_SERVICE = "TXT Preview"
KEYRING_ACCOUNT = "groq-api-key"

MSG_NEEDS_API_KEY = "Ingresá una API key de Groq."


def settings_dir() -> str:
    """Platform settings folder: %LOCALAPPDATA%\\TXT Preview / Application
    Support / ~/.local/share, mirroring the legacy PowerShell app on Windows."""
    if sys.platform == "win32":
        return os.path.join(os.environ.get("LOCALAPPDATA", ""), APP_DIR_NAME)
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library",
                            "Application Support", APP_DIR_NAME)
    return os.path.join(os.path.expanduser("~"), ".local", "share", APP_DIR_NAME)


def legacy_settings_dir() -> str:
    """Folder of the legacy PowerShell app's settings.json (same name on Windows)."""
    if sys.platform == "win32":
        return os.path.join(os.environ.get("LOCALAPPDATA", ""), APP_DIR_NAME)
    return settings_dir()


def _settings_file(directory: str | None) -> str:
    return os.path.join(directory or settings_dir(), SETTINGS_FILE_NAME)


def default_settings() -> dict:
    return {
        "selected_model": DEFAULT_MODEL_ID,
        "theme": DEFAULT_THEME,
        "speech_voice": DEFAULT_SPEECH_VOICE,
        "speed": DEFAULT_SPEED,
    }


# ---- JSON persistence (plain fields only; secrets never cross this pair) ----

_PLAIN_FIELDS = ("selected_model", "theme", "speech_voice", "speed")
_SECRET_FIELDS = ("api_key", "api_key_enc", "plaintext_key")
# Key field of txt.ps1 (hex DPAPI blob, ConvertFrom-SecureString shape). Both
# apps share settings.json on Windows, so the Python app keeps it in sync.
LEGACY_KEY_FIELD = "EncryptedApiKey"


def _read_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8-sig") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write_json(path: str, data: dict) -> None:
    """Atomic save: temp file in the same directory, then os.replace."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    import tempfile

    descriptor, temp_path = tempfile.mkstemp(prefix=".settings-", suffix=".tmp",
                                             dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def load_settings(directory: str | None = None) -> dict:
    """Plain settings fields merged over defaults; secrets are not returned."""
    stored = _read_json(_settings_file(directory)) or {}
    loaded = default_settings()
    for field in _PLAIN_FIELDS:
        if field in stored and stored[field] is not None:
            loaded[field] = stored[field]
    return loaded


def save_settings(values: dict, directory: str | None = None) -> None:
    """Persist plain fields; existing secret fields in the file are preserved."""
    path = _settings_file(directory)
    stored = _read_json(path) or {}
    for field in _PLAIN_FIELDS:
        if field in values and values[field] is not None:
            stored[field] = values[field]
    _write_json(path, stored)


# ---- Public getters/setters (theme / voice / speed / model) -----------------

def get_theme(directory: str | None = None) -> str:
    return str(load_settings(directory).get("theme", DEFAULT_THEME))


def set_theme(theme: str, directory: str | None = None) -> None:
    save_settings({"theme": theme}, directory)


def get_speech_voice(directory: str | None = None) -> str:
    return str(load_settings(directory).get("speech_voice", DEFAULT_SPEECH_VOICE))


def set_speech_voice(voice: str, directory: str | None = None) -> None:
    save_settings({"speech_voice": voice}, directory)


def get_speed(directory: str | None = None) -> int:
    return int(load_settings(directory).get("speed", DEFAULT_SPEED))


def set_speed(speed: int, directory: str | None = None) -> None:
    save_settings({"speed": int(speed)}, directory)


def get_selected_model(directory: str | None = None) -> str:
    return str(load_settings(directory).get("selected_model", DEFAULT_MODEL_ID))


def set_selected_model(model_id: str, directory: str | None = None) -> None:
    save_settings({"selected_model": model_id}, directory)


# ---- DPAPI wrapper (Windows) -------------------------------------------------

class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _require_windows() -> None:
    if sys.platform != "win32":
        raise RuntimeError("DPAPI solo está disponible en Windows.")


def _make_blob(data: bytes) -> _DATA_BLOB:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _free_blob(blob: _DATA_BLOB) -> None:
    ctypes.windll.kernel32.LocalFree(blob.pbData)


def dpapi_encrypt(data: bytes) -> bytes:
    """CryptProtectData; called with UTF-16-LE text it matches the legacy blob shape."""
    _require_windows()
    blob_in = _make_blob(data)
    blob_out = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise OSError(f"CryptProtectData falló ({ctypes.GetLastError()}).")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        _free_blob(blob_out)


def dpapi_decrypt(data: bytes) -> bytes:
    """CryptUnprotectData; decrypts blobs written by dpapi_encrypt and by the
    legacy PowerShell app (CryptProtectData output)."""
    _require_windows()
    blob_in = _make_blob(data)
    blob_out = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise OSError(f"CryptUnprotectData falló ({ctypes.GetLastError()}).")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        _free_blob(blob_out)


def _decode_secret_text(raw: bytes) -> str:
    """Secret text is stored as UTF-16-LE (legacy shape); UTF-8 as fallback."""
    try:
        return raw.decode("utf-16-le")
    except UnicodeDecodeError:
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return ""


# ---- API key storage ---------------------------------------------------------

def _keyring_module():
    import keyring  # lazy: optional dependency, only needed off-Windows
    return keyring


def set_api_key(key: str, directory: str | None = None,
                encrypt=None) -> None:
    """Store the key: DPAPI blob on Windows, keychain elsewhere, plaintext
    (flagged) when keyring is unavailable. Empty key removes the secret."""
    key = (key or "").strip()
    path = _settings_file(directory)
    stored = _read_json(path) or {}
    for field in _SECRET_FIELDS:
        stored.pop(field, None)
    if sys.platform == "win32" or encrypt is not None:
        stored.pop(LEGACY_KEY_FIELD, None)
    if key:
        # An injected crypto function is an explicit isolated-storage route for
        # tests and legacy migration. It must never fall through to a real
        # macOS Keychain merely because the host running the test is Darwin.
        if sys.platform == "win32" or encrypt is not None:
            encrypt_function = encrypt or dpapi_encrypt
            blob = encrypt_function(key.encode("utf-16-le"))
            stored["api_key_enc"] = base64.b64encode(blob).decode("ascii")
            stored[LEGACY_KEY_FIELD] = binascii.hexlify(blob).decode("ascii")
        else:
            try:
                _keyring_module().set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, key)
            except Exception:  # no backend / locked keychain: flagged plaintext
                stored["api_key"] = key
                stored["plaintext_key"] = True
    _write_json(path, stored)


def get_api_key(directory: str | None = None, decrypt=None) -> str:
    """Return the stored key or '' when absent/undecryptable. Never raises."""
    try:
        return _get_api_key_impl(directory, decrypt)
    except Exception:
        return ""


def _get_api_key_impl(directory: str | None, decrypt) -> str:
    stored = _read_json(_settings_file(directory)) or {}
    if sys.platform == "win32" or decrypt is not None:
        # txt.ps1 rewrites EncryptedApiKey on every save, so it is the latest
        # key typed in either app; api_key_enc is only the fallback.
        legacy_value = str(stored.get(LEGACY_KEY_FIELD) or "").strip()
        if legacy_value:
            legacy_key = _decode_legacy_api_key(legacy_value, decrypt)
            if legacy_key:
                return legacy_key
        blob = stored.get("api_key_enc")
        if blob:
            decrypt_function = decrypt or dpapi_decrypt
            return _decode_secret_text(decrypt_function(base64.b64decode(blob)))
        return str(stored.get("api_key", "") or "")  # tolerated plaintext
    try:
        value = _keyring_module().get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
        if value:
            return value
    except Exception:
        pass
    return str(stored.get("api_key", "") or "")


# ---- Bridge passwords ---------------------------------------------------------

BRIDGE_PASSWORDS_FIELD = "EncryptedBridgePasswords"


def _bridge_account(key: str) -> str:
    return f"bridge-{key}"


def set_bridge_passwords(passwords: dict, directory: str | None = None,
                         encrypt=None) -> None:
    """Store the bridge passwords {key: password}; blank ones are removed.

    Windows writes txt.ps1's own field (hex DPAPI blobs), so both apps share
    them; elsewhere they go to the OS keychain and never touch the file."""
    cleaned = {str(key): str(value).strip() for key, value in (passwords or {}).items()}
    if sys.platform == "win32" or encrypt is not None:
        encrypt_function = encrypt or dpapi_encrypt
        path = _settings_file(directory)
        stored = _read_json(path) or {}
        stored[BRIDGE_PASSWORDS_FIELD] = {
            key: binascii.hexlify(
                encrypt_function(value.encode("utf-16-le"))).decode("ascii")
            for key, value in cleaned.items() if value
        }
        _write_json(path, stored)
        return
    try:
        keyring = _keyring_module()
        for key, value in cleaned.items():
            if value:
                keyring.set_password(KEYRING_SERVICE, _bridge_account(key), value)
            else:
                try:
                    keyring.delete_password(KEYRING_SERVICE, _bridge_account(key))
                except Exception:
                    pass
    except Exception:
        pass  # no keychain backend: the passwords last for this session only


def get_bridge_passwords(keys, directory: str | None = None, decrypt=None) -> dict:
    """Stored passwords for the given bridge keys; never raises."""
    found: dict[str, str] = {}
    if sys.platform == "win32" or decrypt is not None:
        stored = _read_json(_settings_file(directory)) or {}
        blobs = stored.get(BRIDGE_PASSWORDS_FIELD)
        if not isinstance(blobs, dict):
            return found
        for key in keys:
            value = str(blobs.get(key) or "").strip()
            if not value:
                continue
            try:
                password = _decode_secret_text(
                    (decrypt or dpapi_decrypt)(binascii.unhexlify(value)))
            except Exception:
                continue
            if password:
                found[key] = password
        return found
    for key in keys:
        try:
            value = _keyring_module().get_password(KEYRING_SERVICE, _bridge_account(key))
        except Exception:
            value = None
        if value:
            found[key] = value
    return found


# ---- Legacy migration (Windows) ---------------------------------------------

def _decode_legacy_api_key(value: str, decrypt) -> str:
    """Legacy EncryptedApiKey: hex-encoded DPAPI blob (UTF-16-LE plaintext);
    a plaintext value is imported as-is when it is not a decodable blob."""
    value = (value or "").strip()
    if not value:
        return ""
    if decrypt is not None:
        try:
            return _decode_secret_text(decrypt(binascii.unhexlify(value)))
        except Exception:
            return value
    try:
        blob = binascii.unhexlify(value)
        return _decode_secret_text(dpapi_decrypt(blob))
    except Exception:
        return value


def migrate_legacy_settings(directory: str | None = None, legacy_dir: str | None = None,
                            encrypt=None, decrypt=None) -> bool:
    """Import the API key from the legacy %LOCALAPPDATA%\\TXT Preview
    settings.json into the new settings file. Windows only; True when imported.

    On Windows both files share the same directory, so the legacy file is
    migrated in place: it counts as already migrated once it carries any
    new-format secret field (api_key_enc / api_key / plaintext_key). With a
    distinct legacy folder the import only happens when the new settings file
    does not exist yet (first load; never clobber existing settings)."""
    # Production migration remains Windows-only. Injected crypto explicitly
    # selects the isolated legacy/DPAPI path so cross-platform tests never use
    # or pollute the host Keychain.
    if sys.platform != "win32" and encrypt is None and decrypt is None:
        return False
    legacy_path = os.path.join(legacy_dir or legacy_settings_dir(),
                               SETTINGS_FILE_NAME)
    if not os.path.isfile(legacy_path):
        return False
    path = _settings_file(directory)
    same_file = os.path.abspath(legacy_path) == os.path.abspath(path)
    if os.path.isfile(path) and not same_file:
        return False  # first load only; never clobber existing new settings
    legacy = _read_json(legacy_path) or {}
    if same_file and any(field in legacy for field in _SECRET_FIELDS):
        return False  # already migrated (or written by this app)
    key = _decode_legacy_api_key(str(legacy.get("EncryptedApiKey") or ""), decrypt)
    if not key:
        return False
    set_api_key(key, directory, encrypt=encrypt)
    return True
