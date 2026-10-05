# Installs TXT Preview from this clone: desktop shortcut, optional online voices, first launch.
# Usage after cloning:
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
param(
    [string]$ShortcutDirectory = [Environment]::GetFolderPath("Desktop"),
    [switch]$NoLaunch,
    [switch]$SkipPython
)

$ErrorActionPreference = "Stop"

$appDirectory = $PSScriptRoot
$appScript = Join-Path $appDirectory "txt.ps1"
if (-not (Test-Path -LiteralPath $appScript)) {
    throw "No se encontró txt.ps1 en $appDirectory."
}

# The app needs PowerShell 7 (pwsh): Windows PowerShell 5.1 reads its UTF-8 source as
# ANSI and shows broken accents.
function Find-Pwsh {
    $command = Get-Command pwsh.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $defaultPath = Join-Path $env:ProgramFiles "PowerShell\7\pwsh.exe"
    if (Test-Path -LiteralPath $defaultPath) {
        return $defaultPath
    }
    return $null
}

$powershellPath = Find-Pwsh
if (-not $powershellPath) {
    Write-Host "Instalando PowerShell 7..."
    & winget install --id Microsoft.PowerShell -e --source winget --accept-package-agreements --accept-source-agreements
    $powershellPath = Find-Pwsh
}
if (-not $powershellPath) {
    Write-Host "No se pudo instalar PowerShell 7; se usará Windows PowerShell y algunos acentos pueden verse mal." -ForegroundColor Yellow
    $powershellPath = (Get-Command powershell.exe).Source
}
$launchArguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$appScript`""

New-Item -ItemType Directory -Path $ShortcutDirectory -Force | Out-Null
$shortcutPath = Join-Path $ShortcutDirectory "TXT Preview.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $powershellPath
$shortcut.Arguments = $launchArguments
$shortcut.WorkingDirectory = $appDirectory
$shortcut.IconLocation = "$powershellPath,0"
$shortcut.Description = "TXT Preview"
$shortcut.Save()
Write-Host "Acceso directo creado: $shortcutPath" -ForegroundColor Green

if (-not $SkipPython) {
    # Online voices need the edge-tts package; Windows voices work without Python.
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -eq $python) {
        Write-Host "Python no está instalado: las voces en línea quedan desactivadas (las de Windows funcionan igual)." -ForegroundColor Yellow
    } else {
        & $python.Source -c "import edge_tts" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Instalando edge-tts para las voces en línea..."
            & $python.Source -m pip install --user --quiet edge-tts
            if ($LASTEXITCODE -ne 0) {
                Write-Host "No se pudo instalar edge-tts; las voces de Windows funcionan igual." -ForegroundColor Yellow
            }
        }
    }
}

Write-Host "Listo. Al abrir la app, cargá tu API key de Groq en Configuración." -ForegroundColor Green
if (-not $NoLaunch) {
    Start-Process -FilePath $powershellPath -ArgumentList $launchArguments -WorkingDirectory $appDirectory
}
