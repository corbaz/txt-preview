@echo off
:: Registers ONLY the TXT app as a RemoteApp on this PC (run as administrator).
:: CommandLineSetting=2 forces the RequiredCommandLine below, so a remote client
:: cannot use this entry to run arbitrary PowerShell commands.
:: Undo: uninstall-remoteapp.cmd
set "KEY=HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Terminal Server\TSAppAllowList\Applications\TXT"
set "PWSH=C:\Program Files\PowerShell\7\pwsh.exe"

reg add "%KEY%" /v Name /t REG_SZ /d "TXT" /f
reg add "%KEY%" /v Path /t REG_SZ /d "%PWSH%" /f
reg add "%KEY%" /v VPath /t REG_SZ /d "%PWSH%" /f
reg add "%KEY%" /v IconPath /t REG_SZ /d "%PWSH%" /f
reg add "%KEY%" /v IconIndex /t REG_DWORD /d 0 /f
reg add "%KEY%" /v ShowInTSWA /t REG_DWORD /d 0 /f
reg add "%KEY%" /v SecurityDescriptor /t REG_SZ /d "" /f
reg add "%KEY%" /v CommandLineSetting /t REG_DWORD /d 2 /f
reg add "%KEY%" /v RequiredCommandLine /t REG_SZ /d "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File \"C:\Bat\ps1\TXT\txt.ps1\"" /f
