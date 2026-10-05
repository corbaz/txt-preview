@echo off
:: Removes the TXT RemoteApp registration (run as administrator).
reg delete "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Terminal Server\TSAppAllowList\Applications\TXT" /f
