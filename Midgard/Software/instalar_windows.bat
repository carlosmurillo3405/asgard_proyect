@echo off
rem Instalador de Midgard para Windows: haz doble clic en este archivo.
rem Opciones: -SinAccesoDirecto  -Ejecutable
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_windows.ps1" %*
echo.
pause
