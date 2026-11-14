"""Persisted settings (T10/S2): platform-aware paths, atomic save, DPAPI seam,
keychain storage on macOS and legacy %LOCALAPPDATA%\\TXT Preview migration.

No network and no real DPAPI/keyring in tests, except the win32-only smoke
test at the bottom that exercises the real DPAPI pair on a temp dir.
"""
import base64
import binascii
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt_core import settings

TEST_KEY = "gsk_test1234567890"


def fake_crypto_pair():
    """Injectable DPAPI stand-in: ENC:<utf-16-le bytes> round-trip."""
    def encrypt(data: bytes) -> bytes:
        return b"ENC:" + data

    def decrypt(data: bytes) -> bytes:
        assert data.startswith(b"ENC:")
        return data[len(b"ENC:"):]
    return encrypt, decrypt


def fake_keyring_module(store: dict):
    return types.SimpleNamespace(
        set_password=lambda service, account, value: store.__setitem__(
            (service, account), value),
        get_password=lambda service, account: store.get((service, account)),
    )


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class TestPlatformPaths(unittest.TestCase):
    def test_windows_uses_localappdata_txt_preview(self):
        with tempfile.TemporaryDirectory() as base:
            with mock.patch("sys.platform", "win32"), \
                 mock.patch.dict(os.environ, {"LOCALAPPDATA": base}):
                self.assertEqual(settings.settings_dir(),
                                 os.path.join(base, "TXT Preview"))

    def test_macos_uses_application_support(self):
        with mock.patch("sys.platform", "darwin"), \
                mock.patch("txt_core.settings.os.path.expanduser",
                           lambda path: "/Users/tester"):
            self.assertEqual(
                settings.settings_dir(),
                os.path.join("/Users/tester", "Library", "Application Support",
                             "TXT Preview"))

    def test_linux_uses_xdg_data_home_convention(self):
        with mock.patch("sys.platform", "linux"), \
                mock.patch("txt_core.settings.os.path.expanduser",
                           lambda path: "/home/tester"):
            self.assertEqual(settings.settings_dir(),
                             os.path.join("/home/tester", ".local", "share",
                                          "TXT Preview"))


class TestLoadAndAtomicSave(unittest.TestCase):
    def test_load_returns_defaults_when_file_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            loaded = settings.load_settings(directory)
            self.assertEqual(loaded["selected_model"], "openai/gpt-oss-120b")
            self.assertEqual(loaded["theme"], "dark")
            self.assertEqual(loaded["speed"], 100)
            self.assertTrue(loaded["speech_voice"].endswith("ElviraNeural"))

    def test_save_then_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            settings.save_settings({"theme": "light", "speed": 150}, directory)
            loaded = settings.load_settings(directory)
            self.assertEqual(loaded["theme"], "light")
            self.assertEqual(loaded["speed"], 150)
            self.assertEqual(loaded["selected_model"], "openai/gpt-oss-120b")

    def test_save_is_atomic_and_leaves_no_temp_files(self):
        with tempfile.TemporaryDirectory() as directory:
            settings.save_settings({"theme": "light"}, directory)
            leftovers = [name for name in os.listdir(directory)
                         if name != "settings.json"]
            self.assertEqual(leftovers, [])
            with open(Path(directory) / "settings.json", encoding="utf-8") as handle:
                json.load(handle)  # file is valid JSON, not a partial write

    def test_save_preserves_secret_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            write_json(path, {"api_key_enc": "QUJD", "selected_model": "allam-2-7b"})
            settings.save_settings({"theme": "light"}, directory)
            with open(path, encoding="utf-8") as handle:
                stored = json.load(handle)
            self.assertEqual(stored["api_key_enc"], "QUJD")
            self.assertEqual(stored["theme"], "light")

    def test_getters_and_setters_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            settings.set_theme("light", directory)
            self.assertEqual(settings.get_theme(directory), "light")
            settings.set_speech_voice("es-AR-TomasNeural", directory)
            self.assertEqual(settings.get_speech_voice(directory),
                             "es-AR-TomasNeural")
            settings.set_speed(150, directory)
            self.assertEqual(settings.get_speed(directory), 150)
            settings.set_selected_model("claude:sonnet-4", directory)
            self.assertEqual(settings.get_selected_model(directory),
                             "claude:sonnet-4")


class TestWindowsSecretStorage(unittest.TestCase):
    def test_injected_crypto_uses_isolated_blob_even_on_macos(self):
        """Test/legacy crypto injection must never touch a real CI Keychain."""
        encrypt, decrypt = fake_crypto_pair()
        keyring_calls: list[tuple] = []
        recording_keyring = types.SimpleNamespace(
            set_password=lambda *args: keyring_calls.append(("set", args)),
            get_password=lambda *args: keyring_calls.append(("get", args)),
        )
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch("sys.platform", "darwin"), \
                mock.patch.dict(sys.modules, {"keyring": recording_keyring}):
            settings.set_api_key(TEST_KEY, directory, encrypt=encrypt)
            self.assertEqual(
                settings.get_api_key(directory, decrypt=decrypt), TEST_KEY)
            with open(Path(directory) / "settings.json", encoding="utf-8") as handle:
                stored = json.load(handle)
            self.assertIn("api_key_enc", stored)
            self.assertNotIn("api_key", stored)
            self.assertEqual(keyring_calls, [])

    def test_set_api_key_stores_base64_blob_without_plaintext(self):
        encrypt, _ = fake_crypto_pair()
        with tempfile.TemporaryDirectory() as directory:
            settings.set_api_key(TEST_KEY, directory, encrypt=encrypt)
            with open(Path(directory) / "settings.json", encoding="utf-8") as handle:
                stored = json.load(handle)
            self.assertNotIn("api_key", stored)
            self.assertNotIn("plaintext_key", stored)
            self.assertEqual(
                base64.b64decode(stored["api_key_enc"]),
                b"ENC:" + TEST_KEY.encode("utf-16-le"))

    def test_get_api_key_roundtrip_with_fake_decrypt(self):
        encrypt, decrypt = fake_crypto_pair()
        with tempfile.TemporaryDirectory() as directory:
            settings.set_api_key(TEST_KEY, directory, encrypt=encrypt)
            self.assertEqual(
                settings.get_api_key(directory, decrypt=decrypt), TEST_KEY)

    def test_empty_key_removes_secret(self):
        encrypt, decrypt = fake_crypto_pair()
        with tempfile.TemporaryDirectory() as directory:
            settings.set_api_key(TEST_KEY, directory, encrypt=encrypt)
            settings.set_api_key("", directory, encrypt=encrypt)
            with open(Path(directory) / "settings.json", encoding="utf-8") as handle:
                stored = json.load(handle)
            self.assertNotIn("api_key_enc", stored)
            self.assertEqual(settings.get_api_key(directory, decrypt=decrypt), "")


class TestKeySharedWithPowerShellApp(unittest.TestCase):
    """txt.ps1 and the Python app share %LOCALAPPDATA%\TXT Preview\settings.json:
    the key saved in either Configuración is the one both apps use."""

    def test_set_api_key_also_writes_legacy_encrypted_api_key(self):
        encrypt, _ = fake_crypto_pair()
        with tempfile.TemporaryDirectory() as directory:
            settings.set_api_key(TEST_KEY, directory, encrypt=encrypt)
            with open(Path(directory) / "settings.json", encoding="utf-8") as handle:
                stored = json.load(handle)
            self.assertEqual(
                binascii.unhexlify(stored["EncryptedApiKey"]),
                b"ENC:" + TEST_KEY.encode("utf-16-le"))

    def test_key_saved_by_powershell_app_wins_over_stale_python_blob(self):
        encrypt, decrypt = fake_crypto_pair()
        with tempfile.TemporaryDirectory() as directory:
            settings.set_api_key("gsk_old_python", directory, encrypt=encrypt)
            path = Path(directory) / "settings.json"
            stored = json.loads(path.read_text(encoding="utf-8"))
            stored["EncryptedApiKey"] = binascii.hexlify(
                b"ENC:" + "gsk_new_ps1".encode("utf-16-le")).decode("ascii")
            path.write_text(json.dumps(stored), encoding="utf-8")
            self.assertEqual(settings.get_api_key(directory, decrypt=decrypt), "gsk_new_ps1")

    def test_empty_key_also_removes_legacy_encrypted_api_key(self):
        encrypt, decrypt = fake_crypto_pair()
        with tempfile.TemporaryDirectory() as directory:
            settings.set_api_key(TEST_KEY, directory, encrypt=encrypt)
            settings.set_api_key("", directory, encrypt=encrypt)
            stored = json.loads((Path(directory) / "settings.json").read_text(encoding="utf-8"))
            self.assertNotIn("EncryptedApiKey", stored)
            self.assertEqual(settings.get_api_key(directory, decrypt=decrypt), "")


class TestKeychainStorage(unittest.TestCase):
    def test_darwin_uses_keyring_and_file_stays_secret_free(self):
        store: dict = {}
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch("sys.platform", "darwin"), \
                mock.patch.dict(sys.modules, {"keyring": fake_keyring_module(store)}):
            settings.set_api_key(TEST_KEY, directory)
            with open(Path(directory) / "settings.json", encoding="utf-8") as handle:
                stored = json.load(handle)
            self.assertNotIn("api_key", stored)
            self.assertNotIn("plaintext_key", stored)
            self.assertEqual(
                store[(settings.KEYRING_SERVICE, settings.KEYRING_ACCOUNT)], TEST_KEY)
            self.assertEqual(settings.get_api_key(directory), TEST_KEY)

    def test_keyring_unavailable_falls_back_to_plaintext_flag(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch("sys.platform", "darwin"), \
                mock.patch.dict(sys.modules, {"keyring": None}):
            settings.set_api_key(TEST_KEY, directory)
            with open(Path(directory) / "settings.json", encoding="utf-8") as handle:
                stored = json.load(handle)
            self.assertEqual(stored["api_key"], TEST_KEY)
            self.assertTrue(stored["plaintext_key"])
            self.assertEqual(settings.get_api_key(directory), TEST_KEY)


class TestLegacyMigration(unittest.TestCase):
    def test_injected_crypto_allows_isolated_migration_on_macos(self):
        encrypt, decrypt = fake_crypto_pair()
        with tempfile.TemporaryDirectory() as legacy, \
                tempfile.TemporaryDirectory() as target, \
                mock.patch("sys.platform", "darwin"):
            write_json(Path(legacy) / "settings.json", {
                "EncryptedApiKey": "gsk_isolated_legacy",
            })
            self.assertTrue(settings.migrate_legacy_settings(
                target, legacy_dir=legacy, encrypt=encrypt, decrypt=decrypt))
            self.assertEqual(
                settings.get_api_key(target, decrypt=decrypt),
                "gsk_isolated_legacy")

    def test_migration_is_windows_only(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch("sys.platform", "darwin"):
                self.assertFalse(settings.migrate_legacy_settings(
                    directory, legacy_dir=directory))

    def test_plaintext_legacy_key_is_imported(self):
        encrypt, decrypt = fake_crypto_pair()
        with tempfile.TemporaryDirectory() as legacy, \
                tempfile.TemporaryDirectory() as target:
            write_json(Path(legacy) / "settings.json", {
                "EncryptedApiKey": "gsk_legacy_plain",
                "Model": "openai/gpt-oss-120b",
                "EncryptedBridgePasswords": {},
            })
            imported = settings.migrate_legacy_settings(
                target, legacy_dir=legacy, encrypt=encrypt, decrypt=decrypt)
            self.assertTrue(imported)
            self.assertEqual(
                settings.get_api_key(target, decrypt=decrypt), "gsk_legacy_plain")

    def test_dpapi_blob_path_with_injected_decrypt(self):
        encrypt, decrypt = fake_crypto_pair()
        blob = binascii.hexlify(b"ENC:" + "gsk_blob".encode("utf-16-le"))
        with tempfile.TemporaryDirectory() as legacy, \
                tempfile.TemporaryDirectory() as target:
            write_json(Path(legacy) / "settings.json", {
                "EncryptedApiKey": blob.decode("ascii"),
                "EncryptedBridgePasswords": {},
            })
            imported = settings.migrate_legacy_settings(
                target, legacy_dir=legacy, encrypt=encrypt, decrypt=decrypt)
            self.assertTrue(imported)
            self.assertEqual(settings.get_api_key(target, decrypt=decrypt), "gsk_blob")

    def test_does_not_clobber_existing_new_settings(self):
        encrypt, decrypt = fake_crypto_pair()
        with tempfile.TemporaryDirectory() as legacy, \
                tempfile.TemporaryDirectory() as target:
            write_json(Path(legacy) / "settings.json", {"EncryptedApiKey": "gsk_old"})
            settings.set_api_key(TEST_KEY, target, encrypt=encrypt)
            imported = settings.migrate_legacy_settings(
                target, legacy_dir=legacy, encrypt=encrypt, decrypt=decrypt)
            self.assertFalse(imported)
            self.assertEqual(settings.get_api_key(target, decrypt=decrypt), TEST_KEY)

    def test_missing_legacy_file_returns_false(self):
        encrypt, decrypt = fake_crypto_pair()
        with tempfile.TemporaryDirectory() as target:
            self.assertFalse(settings.migrate_legacy_settings(
                target, legacy_dir=target, encrypt=encrypt, decrypt=decrypt))

    def test_in_place_migration_when_legacy_file_shares_the_new_directory(self):
        """On Windows both files are %LOCALAPPDATA%\\TXT Preview\\settings.json;
        the legacy file is migrated in place and never re-imported afterwards."""
        encrypt, decrypt = fake_crypto_pair()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            write_json(path, {"EncryptedApiKey": "gsk_in_place",
                              "EncryptedBridgePasswords": {}})
            self.assertTrue(settings.migrate_legacy_settings(
                directory, legacy_dir=directory, encrypt=encrypt, decrypt=decrypt))
            self.assertEqual(
                settings.get_api_key(directory, decrypt=decrypt), "gsk_in_place")
            # Second run: the file now carries a new-format secret, so no re-import.
            self.assertFalse(settings.migrate_legacy_settings(
                directory, legacy_dir=directory, encrypt=encrypt, decrypt=decrypt))
            with open(path, encoding="utf-8") as handle:
                stored = json.load(handle)
            self.assertIn("api_key_enc", stored)


@unittest.skipUnless(os.name == "nt", "Real DPAPI only exists on Windows")
class TestRealDpapiSmoke(unittest.TestCase):
    def test_real_dpapi_roundtrip(self):
        data = "ñandú-áéíóú".encode("utf-16-le")
        self.assertEqual(settings.dpapi_decrypt(settings.dpapi_encrypt(data)), data)

    def test_real_roundtrip_through_settings_file(self):
        with tempfile.TemporaryDirectory() as directory:
            settings.set_api_key("gsk_smoke_test", directory)
            self.assertEqual(settings.get_api_key(directory), "gsk_smoke_test")


if __name__ == "__main__":
    unittest.main()
