@echo off
rem Demostracion de las ventanas (sin red, servidor ni hardware): doble clic en este archivo.
rem Opciones: ambas (predeterminado), midgard o asgard. Ejemplo: probar_ventanas.bat midgard
rem Usa el entorno .venv de la raiz; si falta, lo prepara solo la primera vez.
setlocal
chcp 65001 >nul
set "RAIZ=%~dp0.."
set "PY=%RAIZ%\.venv\Scripts\python.exe"
if not exist "%PY%" goto preparar
"%PY%" -c "import cv2, PySide6.QtWidgets" >nul 2>&1
if not errorlevel 1 goto correr
:preparar
echo Preparando el entorno de esta PC (solo la primera vez)...
set "ASGARD_SIN_PAUSA=1"
call "%RAIZ%\instalar_entorno.bat"
if errorlevel 1 goto error_entorno
:correr
"%PY%" "%~dp0probar_ventanas.py" %*
if errorlevel 1 goto error_demo
exit /b 0
:error_entorno
echo No se pudo preparar el entorno; el detalle esta arriba.
pause
exit /b 1
:error_demo
echo.
echo La demostracion termino con un error; el detalle esta arriba.
pause
exit /b 1
