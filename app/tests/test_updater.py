"""In-app update check (T11/S4): VERSION compare against origin/main,
`git pull --ff-only` application and the legacy refusal messages.

Real-git tests build a local origin repo and a clone (file:// remote, no
network, git guaranteed on the dev machine); error paths use mocked
subprocess calls. Legacy wording comes from txt.ps1
Get-AvailableAppUpdate / Install-AppUpdate / Update-AppUpdateControls.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from txt_core import updater

LOCAL_VERSION = "v:26.10.30-15.28"
REMOTE_VERSION = "v:99.12.31-23.59"

MSG_NO_GIT_BINARY = "Git no está instalado o no está disponible en PATH."
MSG_NO_GIT_CLONE = ("La aplicación no se ejecuta desde un clon Git; "
                    "no se puede actualizar automáticamente.")
MSG_REMOTE_VERSION = "No se pudo leer VERSION desde origin/main."
MSG_DIRTY = "Hay cambios locales. Guardalos o confirmalos antes de actualizar."
MSG_WRONG_BRANCH = "La actualización automática requiere estar en la rama main."
MSG_PULL_FAILED_PREFIX = "Git no pudo aplicar la actualización sin sobrescribir cambios."


def git_exe():
    return shutil.which("git")


def run_git(repo, *args):
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                          text=True, env=env, timeout=60)


def git(repo, *args):
    """Asserting git helper for fixture setup."""
    result = run_git(repo, *args)
    if result.returncode != 0:
        raise AssertionError(f"git {args} failed: {result.stderr}")
    return result.stdout.strip()


class RepoFixture(unittest.TestCase):
    """A local origin repo plus a clone; VERSION committed on main."""

    def setUp(self):
        if not git_exe():
            self.skipTest("git no está disponible")
        self.base = Path(tempfile.mkdtemp(prefix="txt-updater-test-"))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.origin = self.base / "origin"
        self.work = self.base / "work"
        self.origin.mkdir()
        git(self.origin, "init", "-b", "main")
        self.write_version(self.origin, LOCAL_VERSION)
        self.commit_all(self.origin, "initial")
        git(self.origin, "clone", self.origin.as_uri(), str(self.work))

    @staticmethod
    def write_version(repo, version):
        (repo / "VERSION").write_text(version + "\n", encoding="utf-8")

    @staticmethod
    def commit_all(repo, message):
        git(repo, "-c", "user.email=test@example.com",
            "-c", "user.name=Test", "add", "-A")
        git(repo, "-c", "user.email=test@example.com",
            "-c", "user.name=Test", "commit", "-m", message)

    def bump_origin_version(self):
        """Push a newer VERSION to origin so the clone sees an update."""
        self.write_version(self.origin, REMOTE_VERSION)
        self.commit_all(self.origin, "bump")


class TestCompareVersions(unittest.TestCase):
    def test_newer_remote_string_compares_true(self):
        self.assertTrue(updater.compare_versions(REMOTE_VERSION, LOCAL_VERSION))

    def test_same_version_is_false(self):
        self.assertFalse(updater.compare_versions(LOCAL_VERSION, LOCAL_VERSION))

    def test_older_remote_is_false(self):
        self.assertFalse(updater.compare_versions(LOCAL_VERSION, REMOTE_VERSION))

    def test_versions_are_trimmed_before_compare(self):
        self.assertFalse(
            updater.compare_versions("  v:26.10.30-15.28 \n", LOCAL_VERSION))


class TestClassify(unittest.TestCase):
    def test_up_to_date_when_versions_match(self):
        self.assertEqual(updater.classify(LOCAL_VERSION, LOCAL_VERSION,
                                          "main", False), "up_to_date")

    def test_available_when_remote_is_newer(self):
        self.assertEqual(updater.classify(LOCAL_VERSION, REMOTE_VERSION,
                                          "main", False), "available")

    def test_wrong_branch_beats_availability(self):
        self.assertEqual(updater.classify(LOCAL_VERSION, REMOTE_VERSION,
                                          "feat/x", False), "wrong_branch")

    def test_dirty_beats_availability(self):
        self.assertEqual(updater.classify(LOCAL_VERSION, REMOTE_VERSION,
                                          "main", True), "dirty")

    def test_wrong_branch_wins_over_dirty_like_legacy_install_order(self):
        self.assertEqual(updater.classify(LOCAL_VERSION, REMOTE_VERSION,
                                          "feat/x", True), "wrong_branch")


class TestCheckUpdateRealRepo(RepoFixture):
    def test_up_to_date_when_versions_match(self):
        status = updater.check_update(self.work)
        self.assertEqual(status.state, "up_to_date")
        self.assertEqual(status.local_version, LOCAL_VERSION)
        self.assertEqual(status.remote_version, LOCAL_VERSION)

    def test_available_after_origin_bump(self):
        self.bump_origin_version()
        status = updater.check_update(self.work)
        self.assertEqual(status.state, "available")
        self.assertEqual(status.remote_version, REMOTE_VERSION)
        self.assertEqual(status.local_version, LOCAL_VERSION)

    def test_local_changes_do_not_affect_the_check(self):
        """txt.ps1 parity: local changes only block installing, so the check
        still offers the new version."""
        self.bump_origin_version()
        (self.work / "notas.txt").write_text("borrador", encoding="utf-8")
        status = updater.check_update(self.work)
        self.assertEqual(status.state, "available")
        self.assertEqual(status.detail, "")

    def test_version_outside_the_expected_format_is_an_error(self):
        self.write_version(self.origin, "2.0.1")
        self.commit_all(self.origin, "bad version")
        status = updater.check_update(self.work)
        self.assertEqual(status.state, "error")
        self.assertEqual(
            status.detail,
            "La versión publicada no usa el formato esperado v:yy.mm.dd-HH.mm.")

    def test_untracked_files_do_not_block_installing(self):
        self.bump_origin_version()
        (self.work / "notas.txt").write_text("borrador", encoding="utf-8")
        (self.work / ".DS_Store").write_bytes(b"x")
        status = updater.apply_update(self.work)
        self.assertTrue(status.updated)
        self.assertEqual(status.local_version, REMOTE_VERSION)

    def test_files_updated_under_a_running_app_still_offer_the_update(self):
        """The check compares with the RUNNING version: after a pull without
        a restart the update is offered, and installing it only needs the
        restart (the pull is a no-op)."""
        self.bump_origin_version()
        git(self.work, "pull", "--ff-only", "origin", "main")
        self.assertEqual(updater.check_update(self.work).state, "up_to_date")
        status = updater.check_update(self.work, LOCAL_VERSION)
        self.assertEqual(status.state, "available")
        self.assertEqual(status.local_version, LOCAL_VERSION)
        # Local edits cannot block it: there is nothing left to pull.
        (self.work / "README.md").write_text("x", encoding="utf-8")
        git(self.work, "add", "README.md")
        installed = updater.apply_update(self.work, LOCAL_VERSION)
        self.assertTrue(installed.updated)
        self.assertEqual(installed.local_version, REMOTE_VERSION)

    def test_versions_compare_by_their_digits(self):
        self.assertTrue(updater.compare_versions("v:26.11.14-12.03", "v:26.11.14-09.47"))
        self.assertFalse(updater.compare_versions("v:26.11.14-09.47", "v:26.11.14-09.47"))
        self.assertFalse(updater.compare_versions("v:25.12.31-23.59", "v:26.01.01-00.00"))

    def test_wrong_branch(self):
        git(self.work, "checkout", "-b", "otra")
        status = updater.check_update(self.work)
        self.assertEqual(status.state, "wrong_branch")
        self.assertEqual(status.detail, MSG_WRONG_BRANCH)

    def test_no_git_when_not_a_clone(self):
        status = updater.check_update(self.base)
        self.assertEqual(status.state, "no_git")
        self.assertEqual(status.detail, MSG_NO_GIT_CLONE)


class TestApplyUpdateRealRepo(RepoFixture):
    def test_success_pulls_ff_only_and_reports_restart_message(self):
        self.bump_origin_version()
        status = updater.apply_update(self.work)
        self.assertEqual(status.state, "up_to_date")
        self.assertEqual(status.local_version, REMOTE_VERSION)
        self.assertEqual(status.detail,
                         "Actualización instalada. Cerrá y abrí la aplicación.")
        self.assertTrue(status.updated)
        self.assertEqual((self.work / "VERSION").read_text(
            encoding="utf-8").strip(), REMOTE_VERSION)

    def test_refuses_when_dirty_and_leaves_version_file(self):
        self.bump_origin_version()
        self.write_version(self.work, "v:26.10.30-00.00")
        status = updater.apply_update(self.work)
        self.assertEqual(status.state, "dirty")
        self.assertEqual(status.detail, MSG_DIRTY)
        self.assertEqual((self.work / "VERSION").read_text(
            encoding="utf-8").strip(), "v:26.10.30-00.00")

    def test_refuses_when_wrong_branch(self):
        self.bump_origin_version()
        git(self.work, "checkout", "-b", "otra")
        status = updater.apply_update(self.work)
        self.assertEqual(status.state, "wrong_branch")

    def test_nothing_to_do_reports_up_to_date(self):
        status = updater.apply_update(self.work)
        self.assertEqual(status.state, "up_to_date")

    def test_diverged_history_fails_with_legacy_message(self):
        self.bump_origin_version()
        self.write_version(self.work, "v:26.10.30-01.00")
        self.commit_all(self.work, "local change")
        status = updater.apply_update(self.work)
        self.assertEqual(status.state, "error")
        self.assertTrue(status.detail.startswith(MSG_PULL_FAILED_PREFIX))
        self.assertEqual((self.work / "VERSION").read_text(
            encoding="utf-8").strip(), "v:26.10.30-01.00")


class FakeGitRunner:
    """Scripted _run_git replacement: list of (rc, stdout, stderr)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, repo, args, timeout=None):
        self.calls.append(list(args))
        rc, out, err = self.responses.pop(0)
        return rc, out, err


def fake_repo(tmp, with_git_dir=True):
    repo = Path(tmp)
    if with_git_dir:
        (repo / ".git").mkdir()
    (repo / "VERSION").write_text(LOCAL_VERSION + "\n", encoding="utf-8")
    return repo


class TestCheckUpdateErrorPaths(unittest.TestCase):
    """Mocked subprocess: no real git and no network in these tests."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = fake_repo(self._tmp.name)
        which = mock.patch.object(updater.shutil, "which", return_value="C:/git/git.exe")
        which.start()
        self.addCleanup(which.stop)

    def test_missing_git_binary(self):
        with mock.patch.object(updater.shutil, "which", return_value=None):
            status = updater.check_update(self.repo)
        self.assertEqual(status.state, "error")
        self.assertEqual(status.detail, MSG_NO_GIT_BINARY)

    def test_fetch_failure_reports_github_contact_error(self):
        runner = FakeGitRunner([(1, "", "could not resolve host")])
        with mock.patch.object(updater, "_run_git", runner):
            status = updater.check_update(self.repo)
        self.assertEqual(status.state, "error")
        self.assertTrue(status.detail.startswith("No se pudo consultar origin/main."))
        self.assertEqual(runner.calls[0][:2], ["fetch", "--quiet"])

    def test_fetch_timeout_reports_github_contact_error(self):
        with mock.patch.object(updater.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30)):
            status = updater.check_update(self.repo)
        self.assertEqual(status.state, "error")
        self.assertTrue(status.detail.startswith("No se pudo consultar origin/main."))

    def test_unreadable_remote_version(self):
        runner = FakeGitRunner([(0, "", ""), (128, "", "fatal: not a valid ref")])
        with mock.patch.object(updater, "_run_git", runner):
            status = updater.check_update(self.repo)
        self.assertEqual(status.state, "error")
        self.assertEqual(status.detail, MSG_REMOTE_VERSION)

    def test_missing_local_version_file(self):
        (self.repo / "VERSION").unlink()
        runner = FakeGitRunner([(0, "", ""), (0, REMOTE_VERSION, "")])
        with mock.patch.object(updater, "_run_git", runner):
            status = updater.check_update(self.repo)
        self.assertEqual(status.state, "error")
        self.assertEqual(status.detail, updater.MSG_LOCAL_VERSION)

    def test_available_with_mocked_git(self):
        runner = FakeGitRunner([
            (0, "", ""),               # fetch
            (0, REMOTE_VERSION, ""),   # show origin/main:VERSION
            (0, "main", ""),           # branch --show-current
            (0, "", ""),               # status --porcelain
        ])
        with mock.patch.object(updater, "_run_git", runner):
            status = updater.check_update(self.repo)
        self.assertEqual(status.state, "available")
        self.assertEqual(status.remote_version, REMOTE_VERSION)
        self.assertEqual(status.local_version, LOCAL_VERSION)

    def test_apply_refuses_to_pull_when_check_is_not_available(self):
        runner = FakeGitRunner([
            (0, "", ""),               # fetch
            (0, LOCAL_VERSION, ""),    # show (same version)
            (0, "main", ""),
            (0, "", ""),
        ])
        with mock.patch.object(updater, "_run_git", runner):
            status = updater.apply_update(self.repo)
        self.assertEqual(status.state, "up_to_date")
        self.assertEqual(len(runner.calls), 3)  # no status check, no pull
        self.assertNotIn(["pull", "--ff-only", "origin", "main"], runner.calls)


class TestApiUpdateWiring(unittest.TestCase):
    """Api bridge: check_for_updates / apply_update return plain dicts."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.api = main.Api(settings_dir=self._tmp.name,
                            legacy_dir=self._tmp.name + "-legacy")

    def test_check_for_updates_returns_status_dict(self):
        status = updater.UpdateStatus("available", REMOTE_VERSION, LOCAL_VERSION, "")
        with mock.patch.object(main.updater, "check_update", return_value=status):
            result = self.api.check_for_updates()
        self.assertEqual(result["state"], "available")
        self.assertEqual(result["remote_version"], REMOTE_VERSION)
        self.assertEqual(result["local_version"], LOCAL_VERSION)
        self.assertIn("detail", result)
        self.assertIn("updated", result)

    def test_apply_update_returns_status_dict(self):
        status = updater.UpdateStatus("up_to_date", REMOTE_VERSION, REMOTE_VERSION,
                                      f"Actualizado a {REMOTE_VERSION}. Reiniciá la aplicación.",
                                      updated=True)
        with mock.patch.object(main.updater, "apply_update", return_value=status):
            result = self.api.apply_update()
        self.assertEqual(result["state"], "up_to_date")
        self.assertTrue(result["updated"])
        self.assertIn("Reiniciá la aplicación.", result["detail"])

    def test_startup_check_offers_an_available_update(self):
        """Legacy Invoke-StartupUpdateCheck: an available version is offered
        with the Yes/No question; any other result only refreshes the label."""
        available = updater.UpdateStatus("available", REMOTE_VERSION, LOCAL_VERSION, "")
        silent = updater.UpdateStatus("up_to_date", LOCAL_VERSION, LOCAL_VERSION, "")
        window = types.SimpleNamespace(evaluate_js=mock.Mock())
        self.api._window = window
        with mock.patch.object(main.updater, "check_update", return_value=available):
            self.api._startup_update_check(delay=0)
        script = window.evaluate_js.call_args[0][0]
        prefix = "window.txtUI && window.txtUI.offerStartupUpdate("
        self.assertTrue(script.startswith(prefix))
        self.assertEqual(json.loads(script[len(prefix):-1])["state"], "available")
        with mock.patch.object(main.updater, "check_update", return_value=silent):
            self.api._startup_update_check(delay=0)
        script = window.evaluate_js.call_args[0][0]
        self.assertTrue(script.startswith("window.txtUI && window.txtUI.applyUpdateStatus("))

    def test_restart_relaunches_the_app_and_closes_the_window(self):
        window = types.SimpleNamespace(destroy=mock.Mock())
        self.api._window = window
        self.api.engine = mock.Mock()
        with mock.patch.object(main.subprocess, "Popen") as popen:
            result = self.api.restart_app()
        argv = popen.call_args[0][0]
        self.assertEqual(argv[0], sys.executable)
        self.assertTrue(argv[1].endswith("main.py"))
        window.destroy.assert_called_once()
        self.assertEqual(result, {"ok": True})


class TestUpdateUiTexts(unittest.TestCase):
    """The Configuración texts and dialogs of txt.ps1."""

    JS = (Path(__file__).resolve().parents[1] / "www" / "js" / "main.js").read_text(
        encoding="utf-8")

    def test_legacy_messages(self):
        for text in (
            "La aplicación está actualizada (${status.local_version}).",
            "Nueva versión ${status.remote_version} disponible.",
            "Actualización instalada. Cerrá y abrí la aplicación.",
            "No se pudo actualizar",
            "No se pudo comprobar",
            "Aplicando la actualización...",
            "Buscando una versión nueva en origin/main...",
            "Se actualizará TXT Preview a ${availableUpdateVersion} desde origin/main. ",
            "La aplicación se reiniciará sola.",
            "Hay una versión nueva de TXT Preview: ${availableUpdateVersion} (tenés ${status.local_version}).",
            "¿Querés actualizar ahora? La aplicación se reiniciará sola.",
            "disponible. Podés actualizar desde Configuración.",
        ):
            self.assertIn(text, self.JS)

    def test_actualizar_ahora_restarts_without_asking_again(self):
        body = self.JS.split('$("apply-update").addEventListener("click"', 1)[1][:900]
        self.assertLess(body.index("installUpdate()"), body.index("api.restart_app()"))
        self.assertNotIn("window.alert(", body)

    def test_accepting_the_startup_offer_installs_and_restarts(self):
        body = self.JS.split("async function offerStartupUpdate(status) {", 1)[1][:900]
        self.assertIn("window.confirm(", body)
        self.assertLess(body.index("installUpdate()"), body.index("api.restart_app()"))


if __name__ == "__main__":
    unittest.main()
