@echo off
rem Prepares this PC's environment: .venv at the root with OpenCV (cv2), Qt, audio,
rem AI and everything the demo, Midgard, Bifrost and Asgard in simulation use.
rem Double-click, or from the terminal: setup_env.bat [--no-ai] [--check]
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "STATUS=1"
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if defined PY goto run
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto run
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto run
rem Mensajes en espanol si Windows esta en espanol.
set "UILANG=en"
for /f %%L in ('powershell -NoProfile -Command "(Get-UICulture).TwoLetterISOLanguageName" 2^>nul') do set "UILANG=%%L"
if "%UILANG%"=="es" goto no_python_es
echo Python 3.10 or newer was not found.
echo Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH") and open this file again.
goto end
:no_python_es
echo No se encontro Python 3.10 o superior.
echo Instalalo desde https://www.python.org/downloads/ (marca "Add python.exe to PATH") y vuelve a abrir este archivo.
goto end
:run
%PY% Common\setup_env.py %*
set "STATUS=%ERRORLEVEL%"
:end
if not "%ASGARD_NO_PAUSE%"=="1" pause
exit /b %STATUS%
