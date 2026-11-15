"""In-app update check (T11/S4): cross-platform port of the legacy
Get-AvailableAppUpdate / Install-AppUpdate / Compare-AppVersions flow
(txt.ps1 ~2116-2240). Git runs through subprocess with a quiet fetch, a
timeout, and GIT_TERMINAL_PROMPT=0, so the same code serves Windows and
macOS. Local changes are never overwritten: a non-empty
`git status --porcelain` refuses the update (legacy Install-AppUpdate).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

BRANCH = "main"
VERSION_FILE_NAME = "VERSION"
GIT_TIMEOUT_SECONDS = 30

STATE_UP_TO_DATE = "up_to_date"
STATE_AVAILABLE = "available"
STATE_DIRTY = "dirty"
STATE_WRONG_BRANCH = "wrong_branch"
STATE_NO_GIT = "no_git"
STATE_ERROR = "error"

# Legacy wording (txt.ps1). MSG_FETCH_ERROR replaces the legacy
# "No se pudo consultar origin/main. ..." with the contact variant.
MSG_NO_GIT_BINARY = "Git no está instalado o no está disponible en PATH."
MSG_NO_GIT_CLONE = ("La aplicación no se ejecuta desde un clon Git; "
                    "no se puede actualizar automáticamente.")
MSG_FETCH_ERROR = "No se pudo consultar origin/main."
MSG_VERSION_FORMAT = "La versión publicada no usa el formato esperado v:yy.mm.dd-HH.mm."
MSG_REMOTE_VERSION = "No se pudo leer VERSION desde origin/main."
MSG_LOCAL_VERSION = "No se pudo leer el archivo VERSION local."
MSG_BRANCH_CHECK = "No se pudo revisar la rama actual."
MSG_STATUS_CHECK = "No se pudo revisar el estado del repositorio."
MSG_DIRTY = "Hay cambios locales. Guardalos o confirmalos antes de actualizar."
MSG_WRONG_BRANCH = "La actualización automática requiere estar en la rama main."
MSG_PULL_FAILED = "Git no pudo aplicar la actualización sin sobrescribir cambios."


@dataclass
class UpdateStatus:
    """Result of a check or an applied update.

    `updated` is True only right after a successful apply, so the UI can
    tell "Actualizado a ...; reiniciá" apart from a plain "sin novedades".
    """
    state: str
    remote_version: str
    local_version: str
    detail: str
    updated: bool = False

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "remote_version": self.remote_version,
            "local_version": self.local_version,
            "detail": self.detail,
            "updated": self.updated,
        }


_VERSION_PATTERN = re.compile(r"^v:\d{2}\.\d{2}\.\d{2}-\d{2}\.\d{2}$")


def compare_versions(left: str, right: str) -> bool:
    """True when the left version is newer. Legacy Compare-AppVersions: both
    must match v:yy.mm.dd-HH.mm and are compared by their digits."""
    left, right = left.strip(), right.strip()
    if not _VERSION_PATTERN.match(left) or not _VERSION_PATTERN.match(right):
        raise ValueError(MSG_VERSION_FORMAT)
    return int(re.sub(r"\D", "", left)) > int(re.sub(r"\D", "", right))


def classify(local_version: str, remote_version: str,
             branch: str, dirty: bool) -> str:
    """Legacy precedence: the branch is checked first, local changes only
    block the installation (see apply_update), then the version comparison."""
    if branch != BRANCH:
        return STATE_WRONG_BRANCH
    if dirty:
        return STATE_DIRTY
    if compare_versions(remote_version, local_version):
        return STATE_AVAILABLE
    return STATE_UP_TO_DATE


def _run_git(repo_root: Path, arguments: list[str],
             timeout: int = GIT_TIMEOUT_SECONDS) -> tuple[int, str, str]:
    """One quiet git command; returns (exit code, stdout, stderr)."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        completed = subprocess.run(
            ["git", *arguments], cwd=str(repo_root), env=env,
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 124, "", "tiempo de espera agotado"
    return completed.returncode, (completed.stdout or "").strip(), \
        (completed.stderr or "").strip()


def _fetch_error(stderr: str) -> str:
    detail = MSG_FETCH_ERROR
    if stderr:
        detail = f"{MSG_FETCH_ERROR} {stderr}"
    return detail


def _is_dirty(repo: Path) -> bool | None:
    """Changes to tracked files only: files the app or the system leave next
    to the code (caches, .DS_Store) never block an update."""
    # core.fileMode=false: an executable bit set by the installer (run.sh on
    # macOS) is not a local change either.
    code, stdout, _ = _run_git(repo, ["-c", "core.fileMode=false", "status",
                                      "--porcelain", "--untracked-files=no"])
    if code != 0:
        return None
    return bool(stdout.strip())


def check_update(repo_root: str | Path, running_version: str | None = None) -> UpdateStatus:
    """Legacy Get-AvailableAppUpdate: main branch, fetch, VERSION compare.
    Local changes do not affect the check; they only block installing.

    The published version is compared with the version this process is
    RUNNING (txt.ps1 $appVersion), not with the VERSION file: when the files
    were already updated but the app was not restarted, the update is still
    offered, and installing it leads to the restart."""
    repo = Path(repo_root)
    if not (repo / ".git").exists():
        return UpdateStatus(STATE_NO_GIT, "", "", MSG_NO_GIT_CLONE)
    if not shutil.which("git"):
        return UpdateStatus(STATE_ERROR, "", "", MSG_NO_GIT_BINARY)

    code, _, stderr = _run_git(repo, ["fetch", "--quiet", "origin", BRANCH])
    if code != 0:
        return UpdateStatus(STATE_ERROR, "", "", _fetch_error(stderr))

    code, stdout, _ = _run_git(repo, ["show", f"origin/{BRANCH}:{VERSION_FILE_NAME}"])
    if code != 0:
        return UpdateStatus(STATE_ERROR, "", "", MSG_REMOTE_VERSION)
    remote_version = stdout.strip()

    local_file = repo / VERSION_FILE_NAME
    if not local_file.exists():
        return UpdateStatus(STATE_ERROR, remote_version, "", MSG_LOCAL_VERSION)
    local_version = (running_version or "").strip() \
        or local_file.read_text(encoding="utf-8").strip()

    code, stdout, _ = _run_git(repo, ["branch", "--show-current"])
    if code != 0:
        return UpdateStatus(STATE_ERROR, remote_version, local_version,
                            MSG_BRANCH_CHECK)
    try:
        state = classify(local_version, remote_version, stdout.strip(), False)
    except ValueError as error:
        return UpdateStatus(STATE_ERROR, remote_version, local_version, str(error))
    detail = MSG_WRONG_BRANCH if state == STATE_WRONG_BRANCH else ""
    return UpdateStatus(state, remote_version, local_version, detail)


def apply_update(repo_root: str | Path, running_version: str | None = None) -> UpdateStatus:
    """Legacy Install-AppUpdate: main branch, clean worktree, then
    `git pull --ff-only`."""
    repo = Path(repo_root)
    verified = check_update(repo, running_version)
    if verified.state != STATE_AVAILABLE:
        return verified

    local_file = repo / VERSION_FILE_NAME
    on_disk = (local_file.read_text(encoding="utf-8").strip()
               if local_file.exists() else "")
    if on_disk == verified.remote_version:
        # The files are already at the published version (updated under the
        # running app): nothing to pull, only the restart is missing.
        return UpdateStatus(
            STATE_UP_TO_DATE, verified.remote_version, on_disk,
            "Actualización instalada. Cerrá y abrí la aplicación.", updated=True)

    dirty = _is_dirty(repo)
    if dirty is None:
        return UpdateStatus(STATE_ERROR, verified.remote_version,
                            verified.local_version, MSG_STATUS_CHECK)
    if dirty:
        return UpdateStatus(STATE_DIRTY, verified.remote_version,
                            verified.local_version, MSG_DIRTY)

    code, _, stderr = _run_git(repo, ["-c", "core.fileMode=false", "pull",
                                      "--ff-only", "origin", BRANCH])
    if code != 0:
        return UpdateStatus(
            STATE_ERROR, verified.remote_version, verified.local_version,
            f"{MSG_PULL_FAILED} {stderr}".strip(),
        )

    local_file = repo / VERSION_FILE_NAME
    local_version = (local_file.read_text(encoding="utf-8").strip()
                     if local_file.exists() else "")
    return UpdateStatus(
        STATE_UP_TO_DATE, verified.remote_version, local_version,
        "Actualización instalada. Cerrá y abrí la aplicación.",
        updated=True,
    )
