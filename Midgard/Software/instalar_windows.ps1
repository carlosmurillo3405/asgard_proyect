# =============================================================================
# Instalador de Midgard para Windows 10/11
#
# Uso: doble clic en instalar_windows.bat, o desde PowerShell:
#   powershell -ExecutionPolicy Bypass -File instalar_windows.ps1 [opciones]
#
# Opciones:
#   -Servidor host[:puerto]   servidor predeterminado (crea servidor.json; los usuarios no escriben nada)
#   -Tls                      el servidor usa TLS (modo público)
#   -Huella AB:CD:...         huella del certificado autofirmado de Bifröst
#   -SinAccesoDirecto         no crea accesos directos
#   -Ejecutable               además genera dist\Midgard\Midgard.exe
#
# Crea el entorno virtual .venv junto al programa, instala las dependencias,
# comprueba que todo cargue y crea accesos directos en el Escritorio y en el
# menú Inicio. Si junto al instalador hay un servidor.json (creado en Bifröst
# con 'main.py cliente'), Midgard se conecta solo a ese servidor.
# =============================================================================
param(
    [string]$Servidor = "",
    [switch]$Tls,
    [string]$Huella = "",
    [switch]$SinAccesoDirecto,
    [switch]$Ejecutable
)

$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Dir

function Info([string]$Texto) { Write-Host "==> $Texto" -ForegroundColor Cyan }
function Aviso([string]$Texto) { Write-Host "Aviso: $Texto" -ForegroundColor Yellow }
function Fallo([string]$Texto) {
    Write-Host "Error: $Texto" -ForegroundColor Red
    exit 1
}

function Buscar-Python {
    # Devuelve el comando (ejecutable y argumentos) de un Python 3.10+ de 64 bits.
    $candidatos = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($version in @("3.13", "3.12", "3.14", "3.11", "3.10")) {
            $candidatos += , @("py", "-$version")
        }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $candidatos += , @("python")
    }
    foreach ($candidato in $candidatos) {
        $exe = $candidato[0]
        $extra = @($candidato | Select-Object -Skip 1)
        try {
            $salida = & $exe @extra -c "import sys; print(sys.version_info >= (3, 10) and sys.maxsize > 2**32)" 2>$null
            if ($LASTEXITCODE -eq 0 -and "$salida" -match "True") {
                return , $candidato
            }
        } catch {
            continue
        }
    }
    return $null
}

if ($Dir.Length -gt 140) {
    Aviso "La carpeta tiene una ruta muy larga ($($Dir.Length) caracteres). Windows limita las rutas a 260 caracteres y algunas bibliotecas (como PortAudio o Qt) podrían no cargar. Si la instalación falla, mueve la carpeta a una ruta corta, por ejemplo C:\Midgard."
}

Info "Buscando Python 3.10 o superior (64 bits)"
$python = Buscar-Python
if ($null -eq $python) {
    Aviso "No se encontró Python 3.10+ de 64 bits."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $respuesta = Read-Host "¿Instalar Python 3.12 con winget ahora? (S/N)"
        if ($respuesta -match "^[sSyY]") {
            winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
            $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
            $python = Buscar-Python
        }
    }
    if ($null -eq $python) {
        Fallo "Instala Python 3.12 desde https://www.python.org/downloads/ (marca 'Add python.exe to PATH') y vuelve a ejecutar el instalador."
    }
}
$pyExe = $python[0]
$pyArgs = @($python | Select-Object -Skip 1)
$version = & $pyExe @pyArgs -c "import sys; print(sys.version.split()[0])"
Info "Usando Python $version"

$venvPython = Join-Path $Dir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Info "Creando el entorno virtual .venv"
    & $pyExe @pyArgs -m venv (Join-Path $Dir ".venv")
    if ($LASTEXITCODE -ne 0) { Fallo "No se pudo crear el entorno virtual." }
}

Info "Instalando dependencias (incluye la interfaz Qt; puede tardar unos minutos)"
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -r (Join-Path $Dir "requirements.txt")
if ($LASTEXITCODE -ne 0) { Fallo "No se pudieron instalar las dependencias." }

Info "Comprobando la instalación"
& $venvPython -c "import cv2, numpy, PIL.Image, sounddevice, mss, cryptography; from PySide6 import QtWidgets; print('Dependencias correctas')"
if ($LASTEXITCODE -ne 0) { Fallo "Alguna dependencia no carga; revisa los mensajes anteriores. Si el error menciona 0xce o 'too long', mueve la carpeta a una ruta más corta (por ejemplo C:\Midgard) y vuelve a instalar." }

if ($Servidor) {
    Info "Fijando el servidor predeterminado: $Servidor"
    $tlsTexto = if ($Tls -or $Huella) { "True" } else { "False" }
    & $venvPython -c "import sys; from midgard.recursos import escribir_servidor; argumentos = sys.argv + ['', '']; print(escribir_servidor(argumentos[1], argumentos[2] == 'True', argumentos[3]))" $Servidor $tlsTexto $Huella
    if ($LASTEXITCODE -ne 0) { Fallo "El servidor indicado no es válido (usa host o host:puerto)." }
}
$archivoServidor = Join-Path $Dir "servidor.json"
if (Test-Path $archivoServidor) {
    Info "Servidor predeterminado: $archivoServidor (los usuarios solo escriben usuario y contraseña)"
} else {
    Aviso "Sin servidor.json: Midgard buscará Bifröst en la red local. Para un servidor en Internet usa -Servidor o copia aquí el servidor.json creado en Bifröst ('main.py cliente')."
}

$icono = Join-Path $Dir "midgard.ico"
& $venvPython -c "import sys; from midgard.recursos import guardar_icono; guardar_icono(sys.argv[1])" $icono 2>$null
if ($LASTEXITCODE -ne 0) { Aviso "No se pudo crear el icono; se usará el de Python." }

$lanzador = Join-Path $Dir "iniciar_midgard.bat"
@"
@echo off
rem Inicia Midgard sin ventana de consola.
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py" %*
"@ | Set-Content -Path $lanzador -Encoding ASCII
Info "Lanzador creado: $lanzador"

if (-not $SinAccesoDirecto) {
    $shell = New-Object -ComObject WScript.Shell
    $pythonw = Join-Path $Dir ".venv\Scripts\pythonw.exe"
    $destinos = @(
        [Environment]::GetFolderPath("Desktop"),
        [Environment]::GetFolderPath("Programs")
    )
    foreach ($carpeta in $destinos) {
        if (-not $carpeta) { continue }
        $acceso = $shell.CreateShortcut((Join-Path $carpeta "Midgard.lnk"))
        $acceso.TargetPath = $pythonw
        $acceso.Arguments = '"' + (Join-Path $Dir "main.py") + '"'
        $acceso.WorkingDirectory = $Dir
        $acceso.IconLocation = if (Test-Path $icono) { "$icono,0" } else { "$pythonw,0" }
        $acceso.Description = "Midgard - cliente del sistema Asgard"
        $acceso.Save()
    }
    Info "Accesos directos creados en el Escritorio y en el menú Inicio."
}

if ($Ejecutable) {
    Info "Construyendo el ejecutable independiente"
    & $venvPython (Join-Path $Dir "construir_ejecutable.py")
    if ($LASTEXITCODE -ne 0) { Fallo "No se pudo construir el ejecutable." }
}

Write-Host ""
Info "Midgard está listo. Ábrelo con el acceso directo o con iniciar_midgard.bat"
