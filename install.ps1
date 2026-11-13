# Installs the cross-platform TXT Preview (Python + pywebview) from this clone:
# Python 3.12, the app dependencies, FFmpeg, a desktop shortcut and first launch.
# Usage after cloning:
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
#   powershell -ExecutionPolicy Bypass -File .\install.ps1 -SkipInstalls -NoLaunch   # solo doctor
# The legacy PowerShell app keeps its own flow in txt.ps1 (see git history).
param(
    [string]$ShortcutDirectory = [Environment]::GetFolderPath("Desktop"),
    [switch]$NoLaunch,
    # -SkipInstalls: no instala nada ni crea el acceso directo; solo revisa y
    # muestra el doctor. Útil para validar el instalador sin tocar el sistema.
    [switch]$SkipInstalls,
    [switch]$SkipPython,
    [switch]$SkipFfmpeg
)

$ErrorActionPreference = "Stop"

$appDirectory = Join-Path $PSScriptRoot "app"
$appScript = Join-Path $appDirectory "main.py"
if (-not (Test-Path -LiteralPath $appScript)) {
    throw "No se encontró app\main.py en $PSScriptRoot."
}
$doctorScript = Join-Path $appDirectory "doctor.py"

# Windows PowerShell 5.1 turns stderr from native commands into terminating errors when
# ErrorActionPreference is Stop, so native tools run through this helper.
function Invoke-Native {
    param([string]$FilePath, [string[]]$Arguments)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $FilePath @Arguments 2>&1 | Out-Null
        return $LASTEXITCODE
    } catch {
        return 1
    } finally {
        $ErrorActionPreference = $previous
    }
}

# Runs a native command showing its output (used for the doctor report); the
# caller needs only the exit code, so the output goes straight to the console.
function Invoke-NativeShown {
    param([string]$FilePath, [string[]]$Arguments)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $FilePath @Arguments | Out-Host
        return $LASTEXITCODE
    } catch {
        return 1
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Update-SessionPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

function Install-WingetPackage {
    param([string]$Id, [string]$Name)
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        Write-Host "winget no está disponible; no se pudo instalar $Name." -ForegroundColor Yellow
        return
    }
    Write-Host "Instalando $Name..."
    [void](Invoke-Native "winget.exe" @(
        "install", "--id", $Id, "-e", "--source", "winget",
        "--accept-package-agreements", "--accept-source-agreements", "--silent"
    ))
    Update-SessionPath
}

# Ignores the Microsoft Store stub in WindowsApps, which opens the Store instead of running Python.
function Find-Python {
    $candidates = @(Get-Command python.exe -All -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notlike "*\WindowsApps\*" } |
        ForEach-Object { $_.Source })
    $candidates += @(Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA "Programs\Python\Python3*\python.exe") -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending |
        ForEach-Object { $_.FullName })
    foreach ($candidate in $candidates) {
        if ((Invoke-Native $candidate @("--version")) -eq 0) {
            return $candidate
        }
    }
    return $null
}

# Tests dot-source this script to call the functions above without installing anything.
if ($env:TXT_PREVIEW_INSTALL_TEST_MODE -eq "1") {
    return
}

$python = Find-Python
if (-not $SkipInstalls) {
    if (-not $SkipPython) {
        if (-not $python) {
            if (Get-Command winget.exe -ErrorAction SilentlyContinue) {
                Install-WingetPackage "Python.Python.3.12" "Python"
                $python = Find-Python
            } else {
                throw ("winget no está disponible. Instalá Python 3.12 manualmente desde " +
                    "https://www.python.org/downloads/ (marcá 'Add python.exe to PATH') " +
                    "y volvé a ejecutar install.ps1.")
            }
        }
        if (-not $python) {
            throw "No se pudo instalar Python. Instalalo desde https://www.python.org/downloads/ y volvé a ejecutar install.ps1."
        }

        # Same packages the doctor checks: the app, PDF/MP3 exports and Edge voices.
        Write-Host "Instalando las dependencias de Python (app\requirements.txt)..."
        if ((Invoke-Native $python @(
                "-m", "pip", "install", "--user", "--quiet", "--upgrade",
                "-r", (Join-Path $appDirectory "requirements.txt")
            )) -ne 0) {
            Write-Host "No se pudieron instalar las dependencias de Python; mirá el mensaje de pip." -ForegroundColor Yellow
        }
        # Always the latest: Microsoft changes the voice service and an old edge-tts gets HTTP 403.
        Write-Host "Instalando o actualizando edge-tts para las voces en línea..."
        if ((Invoke-Native $python @("-m", "pip", "install", "--user", "--quiet", "--upgrade", "edge-tts")) -ne 0) {
            Write-Host "No se pudo instalar edge-tts; las voces de Edge no van a sonar." -ForegroundColor Yellow
        }
    }

    if (-not $SkipFfmpeg -and -not (Get-Command ffplay.exe -ErrorAction SilentlyContinue)) {
        # FFmpeg plays Edge voices, powers Repetir and exports MP3.
        Install-WingetPackage "Gyan.FFmpeg" "FFmpeg"
        if (-not (Get-Command ffplay.exe -ErrorAction SilentlyContinue)) {
            Write-Host "No se pudo instalar FFmpeg: las voces de Edge no van a sonar." -ForegroundColor Yellow
        }
    }
}

# Always end with the doctor: the same report a human or an AI agent can act on.
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
if ($python -or ($python = Find-Python)) {
    Write-Host ""
    Write-Host "Doctor de dependencias de TXT Preview:"
    $doctorExit = Invoke-NativeShown $python @($doctorScript)
    if ($doctorExit -ne 0) {
        Write-Host "El doctor detectó algo pendiente: seguí las 'Solución' de arriba y volvé a correr install.ps1." -ForegroundColor Yellow
    }
} else {
    Write-Host "No hay Python disponible para correr el doctor; instalalo y volvé a ejecutar install.ps1." -ForegroundColor Yellow
}

if (-not $SkipInstalls) {
    if ($python) {
        $pythonw = Join-Path (Split-Path $python) "pythonw.exe"
        if (-not (Test-Path -LiteralPath $pythonw)) {
            $pythonw = $python
        }
        New-Item -ItemType Directory -Path $ShortcutDirectory -Force | Out-Null
        $shortcutPath = Join-Path $ShortcutDirectory "TXT Preview.lnk"
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = $pythonw
        $shortcut.Arguments = "`"$appScript`""
        $shortcut.WorkingDirectory = $appDirectory
        $shortcut.IconLocation = "$pythonw,0"
        $shortcut.Description = "TXT Preview"
        $shortcut.Save()
        Write-Host "Acceso directo creado: $shortcutPath" -ForegroundColor Green
    } else {
        Write-Host "Sin Python no se creó el acceso directo; instalalo y volvé a ejecutar install.ps1." -ForegroundColor Yellow
    }
}

Write-Host "Listo. Al abrir la app, cargá tu API key de Groq en Configuración." -ForegroundColor Green
if (-not $NoLaunch -and -not $SkipInstalls -and $python) {
    $pythonw = Join-Path (Split-Path $python) "pythonw.exe"
    if (-not (Test-Path -LiteralPath $pythonw)) {
        $pythonw = $python
    }
    Start-Process -FilePath $pythonw -ArgumentList "`"$appScript`"" -WorkingDirectory $appDirectory
}
