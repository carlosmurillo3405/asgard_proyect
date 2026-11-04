@echo off
rem Demo of the windows (no network, server or hardware): double-click this file.
rem Options: both (default), midgard or asgard; --self-test; --language auto/en/es.
rem Example: run_demo.bat midgard
rem Uses the root .venv environment; when it is missing it prepares it the first time.
setlocal
chcp 65001 >nul
set "ROOT=%~dp0.."
set "PY=%ROOT%\.venv\Scripts\python.exe"
rem Mensajes en espanol si Windows esta en espanol.
set "UILANG=en"
for /f %%L in ('powershell -NoProfile -Command "(Get-UICulture).TwoLetterISOLanguageName" 2^>nul') do set "UILANG=%%L"
if not exist "%PY%" goto prepare
"%PY%" -c "import cv2, PySide6.QtWidgets" >nul 2>&1
if not errorlevel 1 goto run
:prepare
if "%UILANG%"=="es" (echo Preparando el entorno de esta PC, solo la primera vez...) else (echo Preparing this PC's environment, only the first time...)
set "ASGARD_NO_PAUSE=1"
call "%ROOT%\setup_env.bat"
if errorlevel 1 goto env_error
:run
"%PY%" "%~dp0run_demo.py" %*
if errorlevel 1 goto demo_error
exit /b 0
:env_error
if "%UILANG%"=="es" (echo No se pudo preparar el entorno; el detalle esta arriba.) else (echo The environment could not be prepared; the details are above.)
pause
exit /b 1
:demo_error
echo.
if "%UILANG%"=="es" (echo La demostracion termino con un error; el detalle esta arriba.) else (echo The demo ended with an error; the details are above.)
pause
exit /b 1
