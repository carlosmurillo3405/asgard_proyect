@echo off
rem Prueba de conexion con el Bifrost de Hetzner: Asgard simulado + Midgard sin ventana.
rem Guardalo en la raiz de asgard_proyect, junto a prueba_conexion.py, y dale doble clic.
rem NO lo subas a GitHub: contiene el secreto del Asgard.
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Preparando el entorno .venv, solo la primera vez. Tarda unos minutos...
    set "ASGARD_NO_PAUSE=1"
    call setup_env.bat --no-ai
)
".venv\Scripts\python.exe" prueba_conexion.py --server 89.167.30.182 --fingerprint 06:CC:14:2C:D7:B8:5F:C7:B7:87:83:9B:06:A7:4C:3A:4B:10:4B:AB:C1:33:7A:8F:10:F7:0C:B7:35:A0:53:37 --device room-1 --secret=MFKu3huWQtzXRSi7lqYg7Q66PxghIhKI --user carlos
pause