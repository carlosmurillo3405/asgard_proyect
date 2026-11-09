# =============================================================================
# Midgard uninstaller for Windows 10/11
#
# Usage: double-click uninstall_windows.bat, use Settings > Apps > Midgard >
# Uninstall, or from PowerShell:
#   powershell -ExecutionPolicy Bypass -File uninstall_windows.ps1 [options]
#
# Options:
#   -Purge             also deletes your settings (photos, trusted fingerprints, log)
#   -KeepSettings      keeps your settings without asking
#   -RemoveFolder      also deletes the program folder (never inside a git repository)
#   -Yes               asks nothing (keeps the settings unless -Purge is given)
#   -DryRun            shows what it would do, without changing anything
#   -Language auto|en|es
#
# Works for every way Midgard is installed on Windows:
#   * installed with install_windows.bat (Midgard 1.x and 2.x): removes .venv,
#     the launcher, the icon, the shortcuts and the Apps entry;
#   * standalone executable (dist\Midgard with Midgard.exe): removes the folder.
# =============================================================================
param(
    [switch]$Purge,
    [switch]$KeepSettings,
    [switch]$RemoveFolder,
    [switch]$Yes,
    [switch]$DryRun,
    [switch]$Pause,
    [ValidateSet("auto", "en", "es")]
    [string]$Language = "auto"
)

$ErrorActionPreference = "Stop"
$Dir = (Split-Path -Parent $MyInvocation.MyCommand.Path).TrimEnd("\")
$UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AsgardSystem.Midgard"

# Mensajes en español si Windows está en español (o con -Language es).
$Spanish = if ($Language -eq "auto") { (Get-UICulture).TwoLetterISOLanguageName -eq "es" } else { $Language -eq "es" }
function T([string]$En, [string]$Es) { if ($script:Spanish) { $Es } else { $En } }
function Info([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }
function Warn([string]$Text) { Write-Host "$(T 'Warning' 'Aviso'): $Text" -ForegroundColor Yellow }
function Finish([int]$Code) {
    if ($Pause) {
        try { Read-Host (T "Press Enter to close" "Pulsa Intro para cerrar") | Out-Null } catch { }
    }
    exit $Code
}
function Fail([string]$Text) {
    Write-Host "Error: $Text" -ForegroundColor Red
    Finish 1
}

function Ask([string]$Question, [bool]$Default) {
    # Sin -Yes pregunta en la consola; con -Yes (o sin consola) usa el valor por defecto.
    if ($Yes) { return $Default }
    $hint = if ($Default) { T "[Y/n]" "[S/n]" } else { T "[y/N]" "[s/N]" }
    try {
        $answer = Read-Host "$Question $hint"
    } catch {
        return $Default
    }
    if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
    return $answer -match "^[sSyY]"
}

function Remove-Path([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    if ($DryRun) {
        Write-Host "   [dry-run] $(T 'remove' 'borrar') $Path"
        return
    }
    try {
        Remove-Item -LiteralPath $Path -Recurse -Force
    } catch {
        Warn ((T "Could not remove {0}: {1}" "No se pudo borrar {0}: {1}") -f $Path, $_.Exception.Message)
    }
}

function Get-ConfigDir {
    # La misma carpeta que usa Midgard (settings.py); MIDGARD_AJUSTES es la variable de Midgard 1.x.
    if ($env:MIDGARD_CONFIG_DIR) { return $env:MIDGARD_CONFIG_DIR }
    if ($env:MIDGARD_AJUSTES) { return $env:MIDGARD_AJUSTES }
    $appData = if ($env:APPDATA) { $env:APPDATA } else { Join-Path $HOME "AppData\Roaming" }
    return Join-Path $appData "Midgard"
}

function Get-ShortcutFolders {
    $folders = @(
        [Environment]::GetFolderPath("Desktop"),
        [Environment]::GetFolderPath("Programs"),
        [Environment]::GetFolderPath("Startup")
    )
    if ($env:APPDATA) {
        $folders += Join-Path $env:APPDATA "Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar"
    }
    return $folders | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
}

function Get-ShortcutsTo([string]$Folder, [string[]]$Searched) {
    # Accesos directos (.lnk) que abren esta copia de Midgard: el destino, los argumentos o la
    # carpeta de trabajo apuntan a $Folder. Los de otras copias de Midgard no se tocan.
    $shell = New-Object -ComObject WScript.Shell
    $prefix = $Folder.TrimEnd("\") + "\"
    $found = @()
    foreach ($place in $Searched) {
        foreach ($file in Get-ChildItem -LiteralPath $place -Filter "*.lnk" -File -ErrorAction SilentlyContinue) {
            try {
                $link = $shell.CreateShortcut($file.FullName)
            } catch {
                continue
            }
            # Se agrega "\" al final para reconocer también la carpeta de trabajo sin barra final.
            $texts = @($link.TargetPath, $link.Arguments, $link.WorkingDirectory) | Where-Object { $_ }
            foreach ($text in $texts) {
                if (($text + "\").IndexOf($prefix, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                    $found += $file.FullName
                    break
                }
            }
        }
    }
    return $found | Select-Object -Unique
}

function Get-GitRoot([string]$Folder) {
    $current = Get-Item -LiteralPath $Folder
    while ($null -ne $current) {
        if (Test-Path -LiteralPath (Join-Path $current.FullName ".git")) { return $current.FullName }
        $current = $current.Parent
    }
    return $null
}

function Get-MidgardProcesses([string]$Folder) {
    # Procesos de esta copia de Midgard: Midgard.exe, o Python ejecutando su main.py (el pythonw.exe
    # del .venv lanza el Python real como proceso hijo, por eso se mira también la línea de comandos).
    $prefix = $Folder.TrimEnd("\") + "\"
    $own = @()
    try {
        $processes = Get-CimInstance Win32_Process -ErrorAction Stop
    } catch {
        return $own
    }
    foreach ($process in $processes) {
        if ($process.ProcessId -eq $PID) { continue }
        $text = "$($process.ExecutablePath) $($process.CommandLine)"
        if ($text -match "uninstall_windows") { continue }   # este desinstalador y su ventana
        if ($text.IndexOf($prefix, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            $own += $process
        }
    }
    return $own
}

# Al cargarse con ". .\uninstall_windows.ps1" solo se definen las funciones (para pruebas).
if ($MyInvocation.InvocationName -eq ".") { return }

# -- qué hay instalado ------------------------------------------------------------ #
$SourceInstall = Test-Path -LiteralPath (Join-Path $Dir "main.py")
$Executable = (-not $SourceInstall) -and (Test-Path -LiteralPath (Join-Path $Dir "Midgard.exe"))
if (-not $SourceInstall -and -not $Executable) {
    Fail (T "This folder has neither main.py nor Midgard.exe: run the uninstaller from Midgard's folder." `
            "Esta carpeta no tiene main.py ni Midgard.exe: ejecuta el desinstalador desde la carpeta de Midgard.")
}
$DeleteFolder = $RemoveFolder -or $Executable
if ($DeleteFolder -and $SourceInstall) {
    # La carpeta del código nunca se borra si es parte de un repositorio (copia de desarrollo).
    $GitRoot = Get-GitRoot $Dir
    if ($GitRoot) {
        Warn ((T "{0} is inside a git repository ({1}): the folder is kept and only what the installer created is removed." `
                 "{0} está dentro de un repositorio git ({1}): la carpeta se conserva y solo se quita lo que creó el instalador.") -f $Dir, $GitRoot)
        $DeleteFolder = $false
    }
}

$Items = @()
if ($SourceInstall) {
    # Lo que crean install_windows.ps1 (2.x), instalar_windows.ps1 (1.x) y build_executable.py.
    foreach ($name in @(".venv", "start_midgard.bat", "iniciar_midgard.bat", "midgard.ico", "build", "dist")) {
        $path = Join-Path $Dir $name
        if (Test-Path -LiteralPath $path) { $Items += $path }
    }
    $package = Join-Path $Dir "midgard"
    if (Test-Path -LiteralPath $package) {
        $Items += @(Get-ChildItem -LiteralPath $package -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
            ForEach-Object { $_.FullName })
    }
    $rootCache = Join-Path $Dir "__pycache__"
    if (Test-Path -LiteralPath $rootCache) { $Items += $rootCache }
}
$Shortcuts = @(Get-ShortcutsTo $Dir (Get-ShortcutFolders) | Where-Object { $_ })
$Registered = $false
if (Test-Path -LiteralPath $UninstallKey) {
    $location = (Get-ItemProperty -LiteralPath $UninstallKey -ErrorAction SilentlyContinue).InstallLocation
    $Registered = $location -and ($location.TrimEnd("\") -ieq $Dir)
}
$ConfigDir = Get-ConfigDir
$HasSettings = Test-Path -LiteralPath $ConfigDir

Write-Host ""
Info (T "Midgard found in $Dir" "Midgard encontrado en $Dir")
if ($Executable) { Write-Host "  $(T 'Standalone executable (Midgard.exe)' 'Ejecutable independiente (Midgard.exe)')" }
foreach ($item in $Items) { Write-Host "  $(T 'Remove:' 'Borrar:')    $item" }
foreach ($item in $Shortcuts) { Write-Host "  $(T 'Shortcut:' 'Acceso:')    $item" }
if ($Registered) { Write-Host "  $(T 'Entry in Settings > Apps' 'Entrada en Configuración > Aplicaciones')" }
if ($DeleteFolder) { Write-Host "  $(T 'Program folder:' 'Carpeta del programa:') $Dir" }
if ($HasSettings) { Write-Host "  $(T 'Your settings:' 'Tus ajustes:')  $ConfigDir" }
Write-Host ""
if (-not $Items -and -not $Shortcuts -and -not $Registered -and -not $DeleteFolder -and -not $HasSettings) {
    Info (T "There is nothing of Midgard to remove." "No hay nada de Midgard que quitar.")
    Finish 0
}
if (-not (Ask (T "Uninstall Midgard?" "¿Desinstalar Midgard?") $true)) {
    Info (T "Nothing was changed." "No se cambió nada.")
    Finish 0
}

# -- Midgard abierto: hay que cerrarlo antes de borrar sus archivos ------------- #
$running = @(Get-MidgardProcesses $Dir)
if ($running) {
    if (Ask (T "Midgard is open. Close it now?" "Midgard está abierto. ¿Cerrarlo ahora?") $true) {
        foreach ($process in $running) {
            if ($DryRun) {
                Write-Host "   [dry-run] $(T 'close' 'cerrar') $($process.Name) ($($process.ProcessId))"
            } else {
                Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
            }
        }
        if (-not $DryRun) { Start-Sleep -Seconds 1 }
    } else {
        Fail (T "Close Midgard and run the uninstaller again." "Cierra Midgard y vuelve a ejecutar el desinstalador.")
    }
}

# -- ajustes del usuario --------------------------------------------------------- #
$DeleteSettings = $false
if ($HasSettings) {
    if ($Purge) {
        $DeleteSettings = $true
    } elseif (-not $KeepSettings) {
        $DeleteSettings = Ask (T "Also delete your settings (profile photos, trusted fingerprints, devices, log)?" `
                                 "¿Borrar también tus ajustes (fotos de perfil, huellas de confianza, dispositivos, registro)?") $false
    }
}

# -- desinstalar ---------------------------------------------------------------- #
foreach ($item in $Shortcuts) {
    Info (T "Removing the shortcut $item" "Quitando el acceso directo $item")
    Remove-Path $item
}
if ($Registered) {
    Info (T "Removing the entry in Settings > Apps" "Quitando la entrada de Configuración > Aplicaciones")
    Remove-Path $UninstallKey
}
foreach ($item in $Items) {
    Info (T "Removing $item" "Borrando $item")
    Remove-Path $item
}
if ($DeleteSettings) {
    Info (T "Deleting your settings in $ConfigDir" "Borrando tus ajustes de $ConfigDir")
    Remove-Path $ConfigDir
}

if ($DeleteFolder) {
    Info (T "The folder $Dir will be deleted when this window closes." "La carpeta $Dir se borrará al cerrar esta ventana.")
    if ($DryRun) {
        Write-Host "   [dry-run] $(T 'remove' 'borrar') $Dir"
    } else {
        # El desinstalador está dentro de la carpeta: otro proceso la borra cuando este termina.
        $quoted = $Dir.Replace("'", "''")
        $command = "Wait-Process -Id $PID -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2; " +
                   "Remove-Item -LiteralPath '$quoted' -Recurse -Force -ErrorAction SilentlyContinue"
        Start-Process -FilePath "powershell.exe" -WindowStyle Hidden -WorkingDirectory $env:TEMP `
            -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $command)
    }
}

Write-Host ""
if ($DryRun) {
    Info (T "Dry run: nothing was changed." "Simulación: no se cambió nada.")
} else {
    Info (T "Midgard was uninstalled." "Midgard se desinstaló.")
}
if ($HasSettings -and -not $DeleteSettings) {
    Write-Host "  $(T 'Your settings stay in' 'Tus ajustes quedan en') $ConfigDir"
    Write-Host "  $(T 'To delete them too: uninstall_windows.bat -Purge' 'Para borrarlos también: uninstall_windows.bat -Purge')"
}
if ($SourceInstall -and -not $DeleteFolder) {
    Write-Host "  $(T 'The program folder was kept:' 'La carpeta del programa se conservó:') $Dir"
    $server = Join-Path $Dir "server.json"
    if (Test-Path -LiteralPath $server) {
        Write-Host "  $(T 'It still holds server.json (the default server) for a reinstall.' 'Conserva server.json (el servidor predeterminado) para reinstalar.')"
    }
}
Write-Host "  $(T 'Python was left installed; other programs may use it.' 'Python sigue instalado; otros programas pueden usarlo.')"
Finish 0
