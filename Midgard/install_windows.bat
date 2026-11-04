@echo off
rem Midgard installer for Windows: double-click this file.
rem Options: -Server host[:port]  -Tls  -Fingerprint AB:CD:...  -NoShortcut  -Executable  -Language auto/en/es
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_windows.ps1" %*
echo.
pause
