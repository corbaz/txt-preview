"""Doctor de dependencias de TXT Preview.

Comprueba las dependencias de la app multiplataforma (S3): git, Python, pip,
los paquetes de Python, ffmpeg y el runtime de WebView. Salida legible para un
humano y, con --json, en JSON para una IA o un script.

Uso:
    python app/doctor.py            # tabla para humanos
    python app/doctor.py --json     # JSON para agentes
    python app/doctor.py --fix      # intenta instalar lo que falta

Códigos de salida: 0 todo OK, 1 falta algo (sin --fix), 2 se intentó
arreglar con --fix y sigue faltando algo.

Solo usa la biblioteca estándar para poder correr antes de instalar nada.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from typing import Callable, Dict, List, Optional, Tuple

CHECK_IDS = [
    "git",
    "python",
    "pip",
    "pywebview",
    "markdown",
    "pymupdf",
    "edge-tts",
    "ffmpeg",
    "webview-runtime",
]

# Paquetes que --fix puede instalar con pip; el resto solo recibe una sugerencia.
FIXABLE_PACKAGES = {"pywebview", "markdown", "pymupdf", "edge-tts"}
PACKAGE_PIP_NAMES = {"pywebview": "pywebview", "markdown": "markdown",
                     "pymupdf": "pymupdf", "edge-tts": "edge-tts"}

MIN_PYTHON = (3, 10)
EDGE_TTS_PROBE_TIMEOUT = 15

# Clave de registro del WebView2 Runtime Evergreen (fuente: docs de Microsoft).
WEBVIEW2_REG_KEY = r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A20A2C48}"
WEBVIEW2_REG_KEY_USER = r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A20A2C48}"


def detect_platform() -> str:
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    if system == "darwin":
        return "macos"
    return "other"


def _which(programs: List[str]) -> Optional[str]:
    for program in programs:
        found = shutil.which(program)
        if found:
            return found
    return None


def _run(argv: List[str], timeout: Optional[int] = None) -> Optional[str]:
    """Corre un comando y devuelve stdout, o None si falla."""
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip()


def _make(id: str, ok: bool, detail: str, fix: Optional[str]) -> Dict:
    return {"id": id, "ok": ok, "detail": detail, "fix": fix if ok is False or fix else fix}


def check_git() -> Dict:
    version = _run(["git", "--version"])
    if version:
        return _make("git", True, version, None)
    fix = "winget install --id Git.Git -e" if detect_platform() == "windows" else "brew install git"
    return _make("git", False, "git no está instalado (lo usa el flujo de actualización con git pull).", fix)


def _python_candidates() -> List[str]:
    return ["python"] if detect_platform() != "macos" else ["python3", "python"]


def check_python() -> Dict:
    for command in _python_candidates():
        version = _run([command, "--version"])  # "Python 3.12.1"
        if not version:
            continue
        parts = version.split()[-1].split(".")
        try:
            numbers = tuple(int(p) for p in parts[:2])
        except ValueError:
            continue
        if numbers >= MIN_PYTHON:
            return _make("python", True, f"{version} ({command})", None)
        return _make(
            "python", False,
            f"{version}: la app necesita Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} o superior.",
            "winget install --id Python.Python.3.12 -e" if detect_platform() == "windows"
            else "brew install python")
    if detect_platform() == "windows":
        return _make("python", False, "Python no está instalado.",
                     "winget install --id Python.Python.3.12 -e")
    return _make("python", False, "Python no está instalado (proba con python3).",
                 "brew install python")


def check_pip() -> Dict:
    for command in _python_candidates():
        version = _run([command, "-m", "pip", "--version"])
        if version:
            return _make("pip", True, version, None)
    return _make("pip", False, "pip no está disponible para el Python detectado.",
                 "python -m ensurepip --upgrade")


def _check_package(id: str, description: str) -> Dict:
    try:
        version = importlib.metadata.version(id)
    except importlib.metadata.PackageNotFoundError:
        version = None
    if version:
        return _make(id, True, f"paquete {id} {version} ({description})", None)
    return _make(id, False, f"Falta el paquete de Python {id} ({description}).",
                 f"python -m pip install --user {PACKAGE_PIP_NAMES[id]}")


def check_pywebview() -> Dict:
    return _check_package("pywebview", "ventana nativa con WebView2/WKWebView")


def check_markdown() -> Dict:
    return _check_package("markdown", "render de la vista previa")


def check_pymupdf() -> Dict:
    return _check_package("pymupdf", "lectura de PDF adjuntos y export a PDF")


def check_edge_tts() -> Dict:
    check = _check_package("edge-tts", "voces Edge en línea")
    if not check["ok"]:
        return check
    # Sonda opcional: confirma que el servicio de voces responde. Sin red la
    # sonda falla pero el paquete sirve, así que no marca el check como fallo.
    voices = _run([sys.executable, "-m", "edge_tts", "--list-voices"],
                  timeout=EDGE_TTS_PROBE_TIMEOUT)
    if voices:
        count = len([line for line in voices.splitlines() if line.strip() and not line.startswith("-")])
        check["detail"] = f"paquete edge-tts {importlib.metadata.version('edge-tts')} (voces en línea OK, {count} voces)"
    else:
        check["detail"] = (f"paquete edge-tts {importlib.metadata.version('edge-tts')} instalado; "
                           "no se pudo consultar la lista de voces (¿sin conexión?)")
    return check


def check_ffmpeg() -> Dict:
    ffplay = _which(["ffplay"])
    ffprobe = _which(["ffprobe"])
    if ffplay and ffprobe:
        return _make("ffmpeg", True, f"ffplay y ffprobe disponibles ({ffplay}).", None)
    missing = []
    if not ffplay:
        missing.append("ffplay")
    if not ffprobe:
        missing.append("ffprobe")
    fix = "winget install --id Gyan.FFmpeg -e" if detect_platform() == "windows" else "brew install ffmpeg"
    return _make("ffmpeg", False,
                 f"Falta ffmpeg ({', '.join(missing)}): lo usan las voces Edge y el export a MP3.",
                 fix)


def _webview2_present_windows() -> bool:
    try:
        import winreg
    except ImportError:  # pragma: no cover - win32 siempre tiene winreg
        return False
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root, WEBVIEW2_REG_KEY) as key:
                if winreg.QueryValueEx(key, "pv")[0]:
                    return True
        except OSError:
            pass
        try:
            with winreg.OpenKey(root, WEBVIEW2_REG_KEY_USER) as key:
                if winreg.QueryValueEx(key, "pv")[0]:
                    return True
        except OSError:
            pass
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    return os.path.isdir(os.path.join(program_files_x86, "Microsoft", "EdgeWebView", "Application"))


def check_webview_runtime() -> Dict:
    where = detect_platform()
    if where == "macos":
        # WKWebView viene integrado en macOS; no hay nada que instalar.
        return _make("webview-runtime", True,
                     "n/a — macOS trae WKWebView integrado, no se necesita instalar nada.", None)
    if where == "windows":
        if _webview2_present_windows():
            return _make("webview-runtime", True, "WebView2 runtime detectado.", None)
        return _make("webview-runtime", False,
                     "Falta el WebView2 runtime, necesario para abrir la ventana en Windows.",
                     "winget install --id Microsoft.EdgeWebView -e")
    try:
        import webview  # noqa: F401
    except ImportError:
        return _make("webview-runtime", True,
                     "n/a — en esta plataforma el runtime de web lo aporta pywebview.", None)
    return _make("webview-runtime", True, "Runtime de web disponible vía pywebview.", None)


def _runner(cid: str) -> Callable[[], Dict]:
    return globals()["check_" + cid.replace("-", "_")]


def run_check(cid: str) -> Dict:
    return _runner(cid)()


def run_checks() -> List[Dict]:
    return [run_check(cid) for cid in CHECK_IDS]


def build_report(results: List[Dict]) -> Dict:
    return {
        "ok": all(check["ok"] for check in results),
        "checks": results,
        "platform": detect_platform(),
    }


def decide_exit_code(results: List[Dict], fixed) -> int:
    if all(check["ok"] for check in results):
        return 0
    if fixed:
        return 2
    return 1


def fix_missing(results: List[Dict], log: Callable[[str], None]) -> Tuple[List[str], List[str]]:
    """Instala con pip lo que se puede; lo demás solo se explica.

    Devuelve (ids arreglados, ids que siguen sin estar OK).
    """
    fixed: List[str] = []
    unfixable: List[str] = []
    for check in results:
        if check["ok"]:
            continue
        cid = check["id"]
        if cid in FIXABLE_PACKAGES:
            package = PACKAGE_PIP_NAMES[cid]
            log(f"Instalando el paquete {package}...")
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--user", package],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            if result.returncode == 0:
                fixed.append(cid)
                continue
            log(f"No se pudo instalar {package}. Solución manual: {check['fix']}")
        else:
            log(f"No se puede instalar {cid} automáticamente en {detect_platform()}. "
                f"Solución: {check['fix']}")
        unfixable.append(cid)
    return fixed, unfixable


def _format_check(check: Dict) -> List[str]:
    lines = []
    state = "  OK " if check["ok"] else "FALTA"
    lines.append(f"{state}  {check['id']:<16} {check['detail']}")
    if not check["ok"] and check["fix"]:
        lines.append(f"{'':6}{'Solución:':<17}{check['fix']}")
    return lines


def render_report(report: Dict, fix_notes: Optional[List[str]] = None) -> str:
    lines = ["Doctor de dependencias de TXT Preview",
             f"Plataforma: {report['platform']}", ""]
    for check in report["checks"]:
        lines.extend(_format_check(check))
    lines.append("")
    if report["ok"]:
        lines.append("Resultado: OK — todo listo. Ejecutá la app con run.cmd (Windows) o ./run.sh (macOS).")
    else:
        missing = [check for check in report["checks"] if not check["ok"]]
        lines.append(f"Resultado: faltan {len(missing)} dependencia(s): "
                     + ", ".join(check["id"] for check in missing))
        if fix_notes:
            lines.extend(fix_notes)
        lines.append("Podés arreglarlo con: python app/doctor.py --fix")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None, out: Optional[object] = None) -> int:
    parser = argparse.ArgumentParser(description="Comprueba las dependencias de TXT Preview.")
    parser.add_argument("--json", action="store_true", help="salida en JSON (para una IA o un script)")
    parser.add_argument("--fix", action="store_true", help="instala con pip los paquetes de Python que falten")
    args = parser.parse_args(argv)
    write = (out or sys.stdout).write

    results = run_checks()
    fix_notes: List[str] = []
    fixed: List[str] = []
    unfixable: List[str] = []
    if args.fix:
        missing = [check for check in results if not check["ok"]]
        notes: List[str] = []
        fixed, unfixable = fix_missing(missing, notes.append)
        for cid in fixed:
            results = [run_check(check["id"]) if check["id"] == cid else check for check in results]
        if unfixable:
            fix_notes.append("Sin arreglo automático (instalalos con las soluciones de arriba): "
                             + ", ".join(unfixable))

    report = build_report(results)
    if args.json:
        write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    else:
        write(render_report(report, fix_notes) + "\n")
    # Aunque ningún arreglo haya tenido éxito, el intento (--fix) cuenta:
    # el código 2 avisa de que corrimos --fix y sigue faltando algo.
    return decide_exit_code(results, fixed or unfixable)


if __name__ == "__main__":
    sys.exit(main())
