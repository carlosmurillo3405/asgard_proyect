@echo off
rem Prepara el entorno de esta PC: .venv en la raiz con OpenCV (cv2), Qt, audio,
rem IA y todo lo que usan la demo, Midgard, Bifrost y Asgard en simulacion.
rem Doble clic, o desde la terminal: instalar_entorno.bat [--sin-ia] [--comprobar]
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "ESTADO=1"
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if defined PY goto correr
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto correr
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto correr
echo No se encontro Python 3.10 o superior.
echo Instalalo desde https://www.python.org/downloads/ (marca "Add python.exe to PATH") y vuelve a abrir este archivo.
goto fin
:correr
%PY% Comun\entorno.py %*
set "ESTADO=%ERRORLEVEL%"
:fin
if not "%ASGARD_SIN_PAUSA%"=="1" pause
exit /b %ESTADO%
