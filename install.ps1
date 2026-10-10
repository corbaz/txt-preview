# Installs TXT Preview from this clone: dependencies, desktop shortcut and first launch.
# Usage after cloning:
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
param(
    [string]$ShortcutDirectory = [Environment]::GetFolderPath("Desktop"),
    [switch]$NoLaunch,
    [switch]$SkipPython,
    [switch]$SkipFfmpeg
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$appDirectory = $PSScriptRoot
$appScript = Join-Path $appDirectory "txt.ps1"
if (-not (Test-Path -LiteralPath $appScript)) {
    throw "No se encontró txt.ps1 en $appDirectory."
}

$portablePwshDirectory = Join-Path $env:LOCALAPPDATA "Programs\PowerShell\7"

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

# The app needs PowerShell 7 (pwsh): it uses .NET APIs that Windows PowerShell 5.1 lacks.
function Find-Pwsh {
    $command = Get-Command pwsh.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    foreach ($candidate in @(
        (Join-Path $env:ProgramFiles "PowerShell\7\pwsh.exe"),
        (Join-Path $portablePwshDirectory "pwsh.exe")
    )) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    return $null
}

# Fallback without winget or admin rights: unpack the official portable zip per user.
function Install-PortablePwsh {
    Write-Host "Descargando PowerShell 7 portable..."
    try {
        $release = Invoke-RestMethod -UseBasicParsing "https://api.github.com/repos/PowerShell/PowerShell/releases/latest"
        $architecture = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "x64" }
        $asset = $release.assets | Where-Object { $_.name -like "PowerShell-*-win-$architecture.zip" } | Select-Object -First 1
        if (-not $asset) {
            return
        }
        $zipPath = Join-Path $env:TEMP $asset.name
        Invoke-WebRequest -UseBasicParsing -Uri $asset.browser_download_url -OutFile $zipPath
        try {
            Install-PwshFromZip $zipPath
        } finally {
            Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
        }
    } catch {
        Write-Host "No se pudo descargar PowerShell 7: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

# Extracts into a staging folder and swaps it in only after pwsh.exe runs, so an
# interrupted download or extraction never leaves a broken pwsh.exe in place.
function Install-PwshFromZip {
    param([string]$ZipPath)
    $stagingDirectory = "$portablePwshDirectory.staging"
    Remove-Item -LiteralPath $stagingDirectory -Recurse -Force -ErrorAction SilentlyContinue
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::ExtractToDirectory($ZipPath, $stagingDirectory)
        $stagedPwsh = Join-Path $stagingDirectory "pwsh.exe"
        if ((Invoke-Native $stagedPwsh @("-NoProfile", "-Command", "exit 0")) -ne 0) {
            throw "El PowerShell 7 descargado no arranca."
        }
        Remove-Item -LiteralPath $portablePwshDirectory -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Path (Split-Path $portablePwshDirectory) -Force | Out-Null
        Move-Item -LiteralPath $stagingDirectory -Destination $portablePwshDirectory
    } finally {
        Remove-Item -LiteralPath $stagingDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }
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

$powershellPath = Find-Pwsh
if (-not $powershellPath) {
    Install-WingetPackage "Microsoft.PowerShell" "PowerShell 7"
    $powershellPath = Find-Pwsh
}
if (-not $powershellPath) {
    Install-PortablePwsh
    $powershellPath = Find-Pwsh
}
if (-not $powershellPath) {
    throw "No se pudo instalar PowerShell 7. Instalalo con 'winget install Microsoft.PowerShell' y volvé a ejecutar install.ps1."
}

if (-not $SkipPython) {
    # Online voices need Python with the edge-tts package; Windows voices work without them.
    $python = Find-Python
    if (-not $python) {
        Install-WingetPackage "Python.Python.3.12" "Python"
        $python = Find-Python
    }
    if (-not $python) {
        Write-Host "No se pudo instalar Python: las voces en línea quedan desactivadas (las de Windows funcionan igual)." -ForegroundColor Yellow
    } elseif ((Invoke-Native $python @("-c", "import edge_tts")) -ne 0) {
        Write-Host "Instalando edge-tts para las voces en línea..."
        if ((Invoke-Native $python @("-m", "pip", "install", "--user", "--quiet", "edge-tts")) -ne 0) {
            Write-Host "No se pudo instalar edge-tts; las voces de Windows funcionan igual." -ForegroundColor Yellow
        }
    }
}

if (-not $SkipFfmpeg -and -not (Get-Command ffplay.exe -ErrorAction SilentlyContinue)) {
    # FFmpeg plays Edge voices, powers Repetir and exports MP3.
    Install-WingetPackage "Gyan.FFmpeg" "FFmpeg"
    if (-not (Get-Command ffplay.exe -ErrorAction SilentlyContinue)) {
        Write-Host "No se pudo instalar FFmpeg: las voces de Edge no van a sonar." -ForegroundColor Yellow
    }
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

Write-Host "Listo. Al abrir la app, cargá tu API key de Groq en Configuración." -ForegroundColor Green
if (-not $NoLaunch) {
    Start-Process -FilePath $powershellPath -ArgumentList $launchArguments -WorkingDirectory $appDirectory
}
