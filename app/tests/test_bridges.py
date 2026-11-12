"""Tests for local bridge routing, auth and password resolution (S1)."""
import base64
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt_core import bridges


class TestBridgeRouting(unittest.TestCase):
    def test_three_bridges_defined(self):
        self.assertEqual(
            [(b.key, b.port) for b in bridges.LOCAL_BRIDGES],
            [("claude", 4098), ("codex", 4094), ("gemini", 4092)],
        )

    def test_get_bridge_by_prefix(self):
        self.assertEqual(bridges.get_bridge("codex:gpt-6").key, "codex")
        self.assertIsNone(bridges.get_bridge("openai/gpt-oss-120b"))

    def test_strip_prefix(self):
        bridge = bridges.get_bridge("gemini:gemini-3-pro")
        self.assertEqual(bridges.strip_bridge_prefix("gemini:gemini-3-pro", bridge), "gemini-3-pro")


class TestBridgeAuth(unittest.TestCase):
    def test_basic_auth_header(self):
        bridge = bridges.LOCAL_BRIDGES[0]
        header = bridges.bridge_basic_auth_header(bridge, "secreto")
        expected = base64.b64encode(b"claude:secreto").decode("ascii")
        self.assertEqual(header, f"Basic {expected}")


class TestBridgePassword(unittest.TestCase):
    def test_env_var_wins(self):
        bridge = bridges.LOCAL_BRIDGES[1]
        with unittest.mock.patch.dict(os.environ, {"CODEX_BRIDGE_PASSWORD": " env-pass "}):
            self.assertEqual(bridges.get_bridge_password(bridge), "env-pass")

    def test_password_file_fallback(self):
        bridge = bridges.LOCAL_BRIDGES[0]
        with tempfile.TemporaryDirectory() as tmp:
            fake_base = Path(tmp) / "prompting" / "claude-bridge"
            fake_base.mkdir(parents=True)
            (fake_base / "password.txt").write_text("file-pass\n", encoding="utf-8")
            with mock_prompting_base(Path(tmp) / "prompting"):
                self.assertEqual(bridges.get_bridge_password(bridge), "file-pass")

    def test_no_password_returns_empty(self):
        bridge = bridges.LOCAL_BRIDGES[2]
        with unittest.mock.patch.dict(os.environ, {}, clear=False), mock_prompting_base(Path(tempfile.gettempdir()) / "no-existe"):
            os.environ.pop("GEMINI_BRIDGE_PASSWORD", None)
            self.assertEqual(bridges.get_bridge_password(bridge), "")


class mock_prompting_base:
    """Patch bridges._prompting_base_dir to return a test directory."""

    def __init__(self, path):
        self.path = str(path)
        self._patcher = None

    def __enter__(self):
        self._patcher = unittest.mock.patch.object(
            bridges, "_prompting_base_dir", return_value=self.path,
        )
        self._patcher.start()
        return self

    def __exit__(self, *args):
        self._patcher.stop()
        return False


if __name__ == "__main__":
    unittest.main()
