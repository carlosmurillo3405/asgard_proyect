@echo off
rem Instalador de Midgard para Windows: haz doble clic en este archivo.
rem Opciones: -Servidor host[:puerto]  -Tls  -Huella AB:CD:...  -SinAccesoDirecto  -Ejecutable
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_windows.ps1" %*
echo.
pause
