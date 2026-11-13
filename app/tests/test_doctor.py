"""Tests for the dependency doctor (S3): report shape, exit codes and fix mode.

Every test fakes the check functions, so no subprocess or network is touched.
"""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import doctor  # noqa: E402


def ok_check(cid, detail="ok"):
    return {"id": cid, "ok": True, "detail": detail, "fix": None}


def missing_check(cid, fix="arreglalo"):
    return {"id": cid, "ok": False, "detail": f"{cid} no está disponible.", "fix": fix}


CHECK_IDS = [
    "git", "python", "pip", "pywebview", "markdown", "pymupdf",
    "edge-tts", "ffmpeg", "webview-runtime",
]


class BuildReportTests(unittest.TestCase):
    def test_all_ok_report_is_ok(self):
        results = [ok_check(cid) for cid in CHECK_IDS]
        report = doctor.build_report(results)
        self.assertTrue(report["ok"])
        self.assertEqual(report["platform"], doctor.detect_platform())
        self.assertEqual([c["id"] for c in report["checks"]], CHECK_IDS)

    def test_one_missing_report_is_not_ok(self):
        results = [ok_check(cid) for cid in CHECK_IDS[:-1]]
        results.append(missing_check("edge-tts"))
        report = doctor.build_report(results)
        self.assertFalse(report["ok"])
        self.assertFalse(report["checks"][-1]["ok"])

    def test_check_dicts_have_the_schema_keys(self):
        results = [ok_check(cid) for cid in CHECK_IDS]
        results.append(missing_check("extra"))
        for check in doctor.build_report(results)["checks"]:
            self.assertEqual(set(check), {"id", "ok", "detail", "fix"})


class DecideExitCodeTests(unittest.TestCase):
    def test_all_ok_is_zero(self):
        results = [ok_check(cid) for cid in CHECK_IDS]
        self.assertEqual(doctor.decide_exit_code(results, fixed=False), 0)
        self.assertEqual(doctor.decide_exit_code(results, fixed=["git"]), 0)

    def test_missing_without_fix_is_one(self):
        results = [ok_check(cid) for cid in CHECK_IDS]
        results[3] = missing_check("pywebview")
        self.assertEqual(doctor.decide_exit_code(results, fixed=False), 1)

    def test_fix_attempted_but_still_missing_is_two(self):
        results = [ok_check(cid) for cid in CHECK_IDS]
        results[3] = missing_check("pywebview")
        self.assertEqual(doctor.decide_exit_code(results, fixed=["pywebview"]), 2)


class JsonCliTests(unittest.TestCase):
    def run_cli(self, argv, patches):
        out = io.StringIO()
        with mock.patch.multiple(doctor, **patches):
            code = doctor.main(argv, out=out)
        return code, out.getvalue()

    def patched_all_ok(self):
        patches = {f"check_{cid.replace('-', '_')}": mock.MagicMock(return_value=ok_check(cid))
                   for cid in CHECK_IDS}
        patches["detect_platform"] = mock.MagicMock(return_value="windows")
        return patches

    def test_all_ok_prints_json_and_exits_zero(self):
        patches = self.patched_all_ok()
        code, stdout = self.run_cli(["--json"], patches)
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["platform"], "windows")
        self.assertEqual([c["id"] for c in payload["checks"]], CHECK_IDS)
        for check in payload["checks"]:
            self.assertEqual(set(check), {"id", "ok", "detail", "fix"})

    def test_one_missing_prints_json_with_fix_and_exits_one(self):
        patches = self.patched_all_ok()
        patches["check_edge_tts"] = mock.MagicMock(return_value=missing_check(
            "edge-tts", fix="python -m pip install --user edge-tts"))
        code, stdout = self.run_cli(["--json"], patches)
        self.assertEqual(code, 1)
        payload = json.loads(stdout)
        self.assertFalse(payload["ok"])
        edge = [c for c in payload["checks"] if c["id"] == "edge-tts"][0]
        self.assertFalse(edge["ok"])
        self.assertEqual(edge["fix"], "python -m pip install --user edge-tts")
        self.assertTrue(edge["detail"])

    def test_human_output_names_the_missing_check_and_its_fix(self):
        patches = self.patched_all_ok()
        patches["check_ffmpeg"] = mock.MagicMock(return_value=missing_check(
            "ffmpeg", fix="winget install --id Gyan.FFmpeg -e"))
        code, stdout = self.run_cli([], patches)
        self.assertEqual(code, 1)
        self.assertIn("FALTA", stdout)
        self.assertIn("ffmpeg", stdout)
        self.assertIn("winget install --id Gyan.FFmpeg -e", stdout)

    def test_human_output_all_ok_reports_success(self):
        patches = self.patched_all_ok()
        code, stdout = self.run_cli([], patches)
        self.assertEqual(code, 0)
        self.assertIn("OK", stdout)
        self.assertNotIn("FALTA", stdout)


class FixModeTests(unittest.TestCase):
    def setUp(self):
        self.results = [ok_check(cid) for cid in CHECK_IDS]
        self.results[6] = missing_check("edge-tts", fix="python -m pip install --user edge-tts")
        self.results[7] = missing_check("ffmpeg", fix="brew install ffmpeg")

    def test_fix_installs_python_packages_and_reports_unfixable(self):
        log = []
        with mock.patch.object(doctor.subprocess, "run",
                               return_value=mock.Mock(returncode=0)) as run:
            fixed, unfixable = doctor.fix_missing(self.results, log.append)
        self.assertEqual(fixed, ["edge-tts"])
        self.assertEqual(unfixable, ["ffmpeg"])
        self.assertIn("edge-tts", run.call_args.args[0])
        self.assertIn("--user", run.call_args.args[0])
        self.assertIn("pip", run.call_args.args[0])
        joined = "\n".join(log)
        self.assertIn("brew install ffmpeg", joined)
        self.assertIn("ffmpeg", joined)

    def test_failed_pip_install_is_not_counted_as_fixed(self):
        with mock.patch.object(doctor.subprocess, "run", return_value=mock.Mock(returncode=1)):
            fixed, unfixable = doctor.fix_missing(self.results, lambda line: None)
        self.assertEqual(fixed, [])
        self.assertEqual(sorted(unfixable), ["edge-tts", "ffmpeg"])

    def fix_cli(self, fix_result):
        patches = {f"check_{cid.replace('-', '_')}": mock.MagicMock(return_value=ok_check(cid))
                   for cid in CHECK_IDS}
        # 1ª llamada: run_checks detecta el paquete faltante;
        # 2ª llamada: re-check posterior al arreglo.
        patches["check_edge_tts"] = mock.MagicMock(
            side_effect=[missing_check("edge-tts"), ok_check("edge-tts")])
        patches["fix_missing"] = mock.MagicMock(return_value=fix_result)
        out = io.StringIO()
        with mock.patch.multiple(doctor, **patches):
            code = doctor.main(["--fix"], out=out)
        return code, out.getvalue()

    def test_fix_all_fixed_exits_zero(self):
        # fix_missing devuelve listas: (ids arreglados, ids sin arreglo).
        code, _ = self.fix_cli((["edge-tts"], []))
        self.assertEqual(code, 0)

    def test_fix_still_missing_exits_two(self):
        code, output = self.fix_cli(([], ["edge-tts"]))
        self.assertEqual(code, 2)
        self.assertIn("edge-tts", output)
        self.assertIn("Sin arreglo automático", output)


class WebviewRuntimeTests(unittest.TestCase):
    def test_macos_webview_runtime_is_na(self):
        with mock.patch.object(doctor, "detect_platform", return_value="macos"):
            check = doctor.check_webview_runtime()
        self.assertTrue(check["ok"])
        self.assertIn("n/a", check["detail"])
        self.assertIsNone(check["fix"])


if __name__ == "__main__":
    unittest.main()
