@echo off
rem Midgard uninstaller for Windows: double-click this file.
rem Options: -Purge  -KeepSettings  -RemoveFolder  -Yes  -DryRun  -Language auto/en/es
rem It runs from %TEMP% so the program folder can be deleted when it is a standalone executable.
cd /d "%TEMP%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall_windows.ps1" -Pause %*
