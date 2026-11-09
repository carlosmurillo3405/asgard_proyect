# =============================================================================
# Midgard installer for Windows 10/11
#
# Usage: double-click install_windows.bat, or from PowerShell:
#   powershell -ExecutionPolicy Bypass -File install_windows.ps1 [options]
#
# Options:
#   -Server host[:port]       default server (creates server.json; users type nothing)
#   -Tls                      the server uses TLS (public mode)
#   -Fingerprint AB:CD:...    fingerprint of Bifröst's self-signed certificate
#   -NoShortcut               does not create shortcuts
#   -Executable               also builds dist\Midgard\Midgard.exe
#   -Language auto|en|es      language of the installer's messages
#
# Creates the .venv virtual environment next to the program, installs the
# dependencies, checks that everything loads and creates shortcuts on the
# Desktop and in the Start menu. When a server.json (created in Bifröst with
# 'main.py client') sits next to the installer, Midgard connects to that
# server by itself.
# =============================================================================
param(
    [string]$Server = "",
    [switch]$Tls,
    [string]$Fingerprint = "",
    [switch]$NoShortcut,
    [switch]$Executable,
    [ValidateSet("auto", "en", "es")]
    [string]$Language = "auto"
)

$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Dir

# Mensajes en español si Windows está en español (o con -Language es).
$Spanish = if ($Language -eq "auto") { (Get-UICulture).TwoLetterISOLanguageName -eq "es" } else { $Language -eq "es" }
function T([string]$En, [string]$Es) { if ($script:Spanish) { $Es } else { $En } }
function Info([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }
function Warn([string]$Text) { Write-Host "$(T 'Warning' 'Aviso'): $Text" -ForegroundColor Yellow }
function Fail([string]$Text) {
    Write-Host "Error: $Text" -ForegroundColor Red
    exit 1
}

function Find-Python {
    # Devuelve el comando (ejecutable y argumentos) de un Python 3.10+ de 64 bits.
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($version in @("3.13", "3.12", "3.14", "3.11", "3.10")) {
            $candidates += , @("py", "-$version")
        }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $candidates += , @("python")
    }
    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        $extra = @($candidate | Select-Object -Skip 1)
        try {
            $output = & $exe @extra -c "import sys; print(sys.version_info >= (3, 10) and sys.maxsize > 2**32)" 2>$null
            if ($LASTEXITCODE -eq 0 -and "$output" -match "True") {
                return , $candidate
            }
        } catch {
            continue
        }
    }
    return $null
}

if ($Dir.Length -gt 140) {
    Warn (T "The folder has a very long path ($($Dir.Length) characters). Windows limits paths to 260 characters and some libraries (such as PortAudio or Qt) might not load. If the installation fails, move the folder to a short path, for example C:\Midgard." `
            "La carpeta tiene una ruta muy larga ($($Dir.Length) caracteres). Windows limita las rutas a 260 caracteres y algunas bibliotecas (como PortAudio o Qt) podrían no cargar. Si la instalación falla, mueve la carpeta a una ruta corta, por ejemplo C:\Midgard.")
}

Info (T "Looking for Python 3.10 or newer (64-bit)" "Buscando Python 3.10 o superior (64 bits)")
$python = Find-Python
if ($null -eq $python) {
    Warn (T "No 64-bit Python 3.10+ was found." "No se encontró Python 3.10+ de 64 bits.")
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $answer = Read-Host (T "Install Python 3.12 with winget now? (Y/N)" "¿Instalar Python 3.12 con winget ahora? (S/N)")
        if ($answer -match "^[sSyY]") {
            winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
            $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
            $python = Find-Python
        }
    }
    if ($null -eq $python) {
        Fail (T "Install Python 3.12 from https://www.python.org/downloads/ (tick 'Add python.exe to PATH') and run the installer again." `
                "Instala Python 3.12 desde https://www.python.org/downloads/ (marca 'Add python.exe to PATH') y vuelve a ejecutar el instalador.")
    }
}
$pyExe = $python[0]
$pyArgs = @($python | Select-Object -Skip 1)
$version = & $pyExe @pyArgs -c "import sys; print(sys.version.split()[0])"
Info (T "Using Python $version" "Usando Python $version")

$venvPython = Join-Path $Dir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Info (T "Creating the .venv virtual environment" "Creando el entorno virtual .venv")
    & $pyExe @pyArgs -m venv (Join-Path $Dir ".venv")
    if ($LASTEXITCODE -ne 0) { Fail (T "The virtual environment could not be created." "No se pudo crear el entorno virtual.") }
}

Info (T "Installing dependencies (includes the Qt interface; it may take a few minutes)" "Instalando dependencias (incluye la interfaz Qt; puede tardar unos minutos)")
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -r (Join-Path $Dir "requirements.txt")
if ($LASTEXITCODE -ne 0) { Fail (T "The dependencies could not be installed." "No se pudieron instalar las dependencias.") }

Info (T "Checking the installation" "Comprobando la instalación")
& $venvPython -c "import cv2, numpy, PIL.Image, sounddevice, mss, cryptography; from PySide6 import QtWidgets; print('OK')"
if ($LASTEXITCODE -ne 0) {
    Fail (T "Some dependency does not load; check the messages above. If the error mentions 0xce or 'too long', move the folder to a shorter path (for example C:\Midgard) and install again." `
            "Alguna dependencia no carga; revisa los mensajes anteriores. Si el error menciona 0xce o 'too long', mueve la carpeta a una ruta más corta (por ejemplo C:\Midgard) y vuelve a instalar.")
}

if ($Server) {
    Info (T "Setting the default server: $Server" "Fijando el servidor predeterminado: $Server")
    $tlsText = if ($Tls -or $Fingerprint) { "True" } else { "False" }
    & $venvPython -c "import sys; from midgard.resources import write_server; a = sys.argv + ['', '']; print(write_server(a[1], a[2] == 'True', a[3]))" $Server $tlsText $Fingerprint
    if ($LASTEXITCODE -ne 0) { Fail (T "The given server is not valid (use host or host:port)." "El servidor indicado no es válido (usa host o host:puerto).") }
}
$serverFile = Join-Path $Dir "server.json"
if (Test-Path $serverFile) {
    Info (T "Default server: $serverFile (users only type their username and password)" "Servidor predeterminado: $serverFile (los usuarios solo escriben usuario y contraseña)")
} else {
    Warn (T "No server.json: Midgard will look for Bifröst on the local network. For a server on the Internet use -Server or copy here the server.json created in Bifröst ('main.py client')." `
            "Sin server.json: Midgard buscará Bifröst en la red local. Para un servidor en Internet usa -Server o copia aquí el server.json creado en Bifröst ('main.py client').")
}

$icon = Join-Path $Dir "midgard.ico"
& $venvPython -c "import sys; from midgard.resources import save_icon; save_icon(sys.argv[1])" $icon 2>$null
if ($LASTEXITCODE -ne 0) { Warn (T "The icon could not be created; Python's will be used." "No se pudo crear el icono; se usará el de Python.") }

$launcher = Join-Path $Dir "start_midgard.bat"
@"
@echo off
rem Starts Midgard without a console window.
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py" %*
"@ | Set-Content -Path $launcher -Encoding ASCII
Info (T "Launcher created: $launcher" "Lanzador creado: $launcher")

if (-not $NoShortcut) {
    $shell = New-Object -ComObject WScript.Shell
    $pythonw = Join-Path $Dir ".venv\Scripts\pythonw.exe"
    $folders = @(
        [Environment]::GetFolderPath("Desktop"),
        [Environment]::GetFolderPath("Programs")
    )
    foreach ($folder in $folders) {
        if (-not $folder) { continue }
        $shortcut = $shell.CreateShortcut((Join-Path $folder "Midgard.lnk"))
        $shortcut.TargetPath = $pythonw
        $shortcut.Arguments = '"' + (Join-Path $Dir "main.py") + '"'
        $shortcut.WorkingDirectory = $Dir
        $shortcut.IconLocation = if (Test-Path $icon) { "$icon,0" } else { "$pythonw,0" }
        $shortcut.Description = T "Midgard - Asgard system client" "Midgard - cliente del sistema Asgard"
        $shortcut.Save()
    }
    Info (T "Shortcuts created on the Desktop and in the Start menu." "Accesos directos creados en el Escritorio y en el menú Inicio.")
}

# Entrada en Configuración > Aplicaciones: desde ahí también se puede desinstalar.
$uninstaller = Join-Path $Dir "uninstall_windows.ps1"
if (Test-Path $uninstaller) {
    $key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AsgardSystem.Midgard"
    $versionFile = Join-Path $Dir "midgard\__init__.py"
    $match = Select-String -Path $versionFile -Pattern '__version__ = "([^"]+)"' -ErrorAction SilentlyContinue
    $appVersion = if ($match) { $match.Matches[0].Groups[1].Value } else { "" }
    $command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$uninstaller`""
    New-Item -Path $key -Force | Out-Null
    Set-ItemProperty -Path $key -Name "DisplayName" -Value "Midgard"
    Set-ItemProperty -Path $key -Name "DisplayVersion" -Value $appVersion
    Set-ItemProperty -Path $key -Name "Publisher" -Value "Asgard System"
    Set-ItemProperty -Path $key -Name "InstallLocation" -Value $Dir
    Set-ItemProperty -Path $key -Name "InstallDate" -Value (Get-Date -Format "yyyyMMdd")
    Set-ItemProperty -Path $key -Name "UninstallString" -Value "$command -Pause"
    Set-ItemProperty -Path $key -Name "QuietUninstallString" -Value "$command -Yes"
    if (Test-Path $icon) { Set-ItemProperty -Path $key -Name "DisplayIcon" -Value "$icon,0" }
    New-ItemProperty -Path $key -Name "NoModify" -Value 1 -PropertyType DWord -Force | Out-Null
    New-ItemProperty -Path $key -Name "NoRepair" -Value 1 -PropertyType DWord -Force | Out-Null
    Info (T "Registered in Settings > Apps (Midgard can be uninstalled from there)." "Registrado en Configuración > Aplicaciones (desde ahí se puede desinstalar Midgard).")
}

if ($Executable) {
    Info (T "Building the standalone executable" "Construyendo el ejecutable independiente")
    & $venvPython (Join-Path $Dir "build_executable.py")
    if ($LASTEXITCODE -ne 0) { Fail (T "The executable could not be built." "No se pudo construir el ejecutable.") }
}

Write-Host ""
Info (T "Midgard is ready. Open it with the shortcut or with start_midgard.bat" "Midgard está listo. Ábrelo con el acceso directo o con start_midgard.bat")
Write-Host "    $(T 'To uninstall it: uninstall_windows.bat, or Settings > Apps > Midgard' 'Para desinstalarlo: uninstall_windows.bat, o Configuración > Aplicaciones > Midgard')"
