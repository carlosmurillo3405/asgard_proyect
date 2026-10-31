@echo off
rem Demostracion de las ventanas (sin red, servidor ni hardware): doble clic en este archivo.
rem Opciones: ambas (predeterminado), midgard o asgard. Ejemplo: probar_ventanas.bat midgard
setlocal
chcp 65001 >nul
set "PY=%~dp0..\Midgard\Software\.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo No se encontro el entorno de Midgard.
    echo Ejecuta primero Midgard\Software\instalar_windows.bat y vuelve a abrir este archivo.
    echo.
    pause
    exit /b 1
)
"%PY%" -c "import PySide6.QtWidgets" >nul 2>&1
if errorlevel 1 (
    echo Instalando la interfaz Qt en el entorno de Midgard...
    "%PY%" -m pip install -r "%~dp0..\Midgard\Software\requirements.txt"
    if errorlevel 1 (
        echo No se pudo instalar. Revisa la conexion a Internet.
        pause
        exit /b 1
    )
)
"%PY%" "%~dp0probar_ventanas.py" %*
if errorlevel 1 (
    echo.
    echo La demostracion termino con un error; el detalle esta arriba.
    pause
)
