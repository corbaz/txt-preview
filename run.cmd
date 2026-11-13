@echo off
rem Runs TXT Preview on Windows: the Python app in app\main.py.
rem Tries "python" first; if it is not available falls back to the "py -3" launcher.
rem (The Store python.exe stub is ignored by install.ps1, so a normal install is fine.)
setlocal
set "APP=%~dp0app\main.py"

where python >nul 2>nul
if %errorlevel% equ 0 (
    python "%APP%" %*
    exit /b %errorlevel%
)
py -3 "%APP%" %*
exit /b %errorlevel%
