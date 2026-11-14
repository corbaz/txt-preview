"""S17/T24: native system TLS trust (truststore) for every Edge subprocess.

macOS Python 3.14 rejects the certifi CA bundle ("Basic Constraints of CA
cert not marked critical"), so every Edge script must inject truststore
(native macOS Keychain / Windows CryptoAPI trust) BEFORE importing
edge_tts — edge_tts builds its SSL context at import time.

Offline tests: source-order inspection via ast, plus the voice wrapper
exercised against stubbed truststore/edge_tts modules. No network, no real
truststore import required. Certificate verification is never disabled.
"""
import ast
import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt_core.speech import voices  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
WORDS_SCRIPT = REPO / "edge_tts_words.py"
WRAPPER_SCRIPT = REPO / "app" / "edge_tts_voices.py"
EXPORT_SCRIPT = REPO / "app" / "edge_tts_export.py"
EXPORTS_MODULE = REPO / "app" / "txt_core" / "exports.py"

# S17: never bypass TLS verification in the Edge scripts.
FORBIDDEN_TLS_SNIPPETS = (
    "verify=False",
    "verify = False",
    "check_hostname=False",
    "check_hostname = False",
    "ssl._create_unverified_context",
    "CERT_NONE",
    "VERIFY_X509_STRICT",
)


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def injection_and_edge_import_lines(path: Path):
    """(line of truststore.inject_into_ssl(), line of `import edge_tts`)."""
    tree = ast.parse(source(path))
    inject_line = None
    edge_import_line = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = ([alias.name for alias in node.names]
                     if isinstance(node, ast.Import) else [node.module or ""])
            if (edge_import_line is None
                    and any(n == "edge_tts" or n.startswith("edge_tts.")
                            for n in names)):
                edge_import_line = node.lineno
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "inject_into_ssl"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "truststore"
                and inject_line is None):
            inject_line = node.lineno
    return inject_line, edge_import_line


class TruststoreInjectionOrderTests(unittest.TestCase):
    def test_audio_generator_injects_truststore_before_importing_edge_tts(self):
        inject_line, edge_import_line = injection_and_edge_import_lines(WORDS_SCRIPT)
        self.assertIsNotNone(inject_line,
                             "edge_tts_words.py never calls truststore.inject_into_ssl()")
        self.assertIsNotNone(edge_import_line,
                             "edge_tts_words.py does not import edge_tts")
        self.assertLess(inject_line, edge_import_line,
                        "truststore must be injected BEFORE importing edge_tts "
                        "(edge_tts builds its SSL context at import time)")

    def test_voice_wrapper_injects_truststore_before_importing_edge_tts(self):
        inject_line, edge_import_line = injection_and_edge_import_lines(WRAPPER_SCRIPT)
        self.assertIsNotNone(inject_line,
                             "app/edge_tts_voices.py never calls truststore.inject_into_ssl()")
        self.assertIsNotNone(edge_import_line,
                             "app/edge_tts_voices.py does not import edge_tts")
        self.assertLess(inject_line, edge_import_line,
                        "truststore must be injected BEFORE importing edge_tts")

    def test_export_wrapper_injects_truststore_before_importing_edge_tts(self):
        inject_line, edge_import_line = injection_and_edge_import_lines(EXPORT_SCRIPT)
        self.assertIsNotNone(
            inject_line,
            "app/edge_tts_export.py never calls truststore.inject_into_ssl()")
        self.assertIsNotNone(
            edge_import_line, "app/edge_tts_export.py does not import edge_tts")
        self.assertLess(
            inject_line, edge_import_line,
            "truststore must be injected BEFORE importing edge_tts "
            "(edge_tts builds its SSL context at import time)")

    def test_edge_scripts_never_bypass_tls_verification(self):
        for path in (WORDS_SCRIPT, WRAPPER_SCRIPT, EXPORT_SCRIPT):
            text = source(path)
            for snippet in FORBIDDEN_TLS_SNIPPETS:
                self.assertNotIn(snippet, text,
                                 f"{path} must never contain {snippet!r}")

    def test_export_mp3_never_invokes_python_dash_m_edge_tts(self):
        text = source(EXPORTS_MODULE)
        self.assertNotIn('"-m"', text,
                         "export_mp3 must not run `python -m edge_tts`; it "
                         "bypasses the native macOS trust store on 3.14")
        self.assertNotIn("--write-media", text)
        self.assertIn("edge_tts_export", text,
                      "export_mp3 must launch the truststore wrapper")
        self.assertTrue(EXPORT_SCRIPT.is_file(),
                        "app/edge_tts_export.py must exist in the repository")


def load_wrapper_with_stubs(list_voices_impl, injected_log=None):
    """Import app/edge_tts_voices.py with stubbed truststore/edge_tts."""
    calls = injected_log if injected_log is not None else []

    fake_truststore = ModuleType("truststore")
    fake_truststore.inject_into_ssl = lambda: calls.append("inject")
    fake_edge_tts = ModuleType("edge_tts")
    fake_edge_tts.list_voices = list_voices_impl

    saved = {name: sys.modules.get(name) for name in ("truststore", "edge_tts")}
    sys.modules["truststore"] = fake_truststore
    sys.modules["edge_tts"] = fake_edge_tts
    try:
        spec = importlib.util.spec_from_file_location(
            "edge_tts_voices_under_test", WRAPPER_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return module


class VoiceWrapperTests(unittest.TestCase):
    """app/edge_tts_voices.py behavior (offline, edge_tts stubbed)."""

    def wrapper(self, impl, injected_log=None):
        return load_wrapper_with_stubs(impl, injected_log)

    def test_wrapper_path_matches_the_catalog_module(self):
        self.assertEqual(voices.VOICE_CATALOG_WRAPPER, WRAPPER_SCRIPT)
        self.assertTrue(WRAPPER_SCRIPT.is_file(),
                        "app/edge_tts_voices.py must exist in the repository")

    def test_prints_one_parser_compatible_line_per_voice(self):
        async def impl(**kwargs):
            return [
                {"ShortName": "es-ES-ElviraNeural", "Gender": "Female",
                 "Locale": "es-ES"},
                {"ShortName": "en-US-JennyNeural", "Gender": "Female",
                 "Locale": "en-US"},
                {"ShortName": "fr-FR-DeniseNeural", "Gender": "Female",
                 "Locale": "fr-FR"},
                {"ShortName": "es-MX-Incomplete", "Gender": "Male"},  # sin Locale
            ]

        module = self.wrapper(impl)
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = module.main()
        self.assertEqual(code, 0)
        lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
        self.assertEqual(lines, [
            "es-ES-ElviraNeural Female es-ES",
            "en-US-JennyNeural Female en-US",
            "fr-FR-DeniseNeural Female fr-FR",
        ])
        self.assertEqual(stderr.getvalue(), "")
        # Cada línea es compatible con el parser legacy del catálogo.
        parsed = voices.parse_voice_catalog("\n".join(lines))
        self.assertEqual([voice["name"] for voice in parsed],
                         ["es-ES-ElviraNeural", "en-US-JennyNeural"])
        self.assertEqual(parsed[0]["gender"], "Female")

    def test_fails_nonzero_with_useful_stderr_when_the_query_fails(self):
        async def impl(**kwargs):
            raise RuntimeError("TLS roto en la sonda")

        module = self.wrapper(impl)
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = module.main()
        self.assertNotEqual(code, 0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("No se pudo consultar", stderr.getvalue())
        self.assertIn("TLS roto en la sonda", stderr.getvalue())

    def test_fails_nonzero_when_the_service_returns_no_voices(self):
        async def impl(**kwargs):
            return []

        module = self.wrapper(impl)
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = module.main()
        self.assertNotEqual(code, 0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("No se pudo consultar", stderr.getvalue())

    def test_wrapper_injects_truststore_when_loaded(self):
        log = []

        async def impl(**kwargs):
            return [{"ShortName": "es-ES-ElviraNeural", "Gender": "Female",
                     "Locale": "es-ES"}]

        module = self.wrapper(impl, injected_log=log)
        self.assertEqual(log, ["inject"])
        module.main()


if __name__ == "__main__":
    unittest.main()
