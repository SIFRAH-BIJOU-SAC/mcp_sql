<#
instalar.ps1 - Instala el servidor MCP sifrah-sql-dwh en ESTA PC, para el usuario actual.
 
Uso (desde la carpeta sifrah_mcp_sql):
    powershell -ExecutionPolicy Bypass -File .\instalar.ps1
 
Opciones:
    -Python <ruta>        Python 3.11 a usar (por defecto: se busca en rutas típicas, 'py -3.11' y PATH).
    -NoInstalarPython     Si no hay Python 3.11, falla en vez de instalarlo automáticamente.
    -SinClaude            Solo prepara el entorno; no registra nada en Claude.
    -DesktopConfig <ruta> Ruta de claude_desktop_config.json (se detecta sola).
 
Qué hace:
  1. Localiza Python 3.11; si no existe, lo instala para el usuario actual (sin admin).
  2. Recrea venv\ si no existe, si fue copiado de otra PC o si no es Python 3.11.
  3. Instala dependencias.
  4. Verifica el driver ODBC y el .env (crea una plantilla si no hay).
  5. Crea la carpeta de exports.
  6. Registra el servidor en Claude Desktop (con backup) y en Claude Code (si está instalado).
#>
param(
    [string]$Python = "",
    [switch]$SinClaude,
    [switch]$NoInstalarPython,
    [string]$DesktopConfig = ""
)
 
$ErrorActionPreference = "Stop"
$PyRequerido = "3.11"
$PyInstalador = "3.11.9"   # última 3.11 con instalador .exe oficial para Windows
$Root = $PSScriptRoot
$Venv = Join-Path $Root "venv"
$VenvPy = Join-Path $Venv "Scripts\python.exe"
$ServerPy = Join-Path $Root "server.py"
$EnvFile = Join-Path $Root ".env"
$Utf8 = New-Object System.Text.UTF8Encoding($false)
 
function Paso($t) { Write-Host "`n==> $t" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "    OK  $t" -ForegroundColor Green }
function Aviso($t){ Write-Host "    !!  $t" -ForegroundColor Yellow }
 
# Devuelve "X.Y" del intérprete indicado, o $null si no se puede ejecutar.
function Get-PyVersion([string]$exe, [string[]]$preArgs = @()) {
    try {
        $v = & $exe @preArgs -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v) { return ($v | Select-Object -First 1).Trim() }
    } catch { }
    return $null
}
 
# Devuelve la ruta real (sys.executable) del intérprete.
function Get-PyExe([string]$exe, [string[]]$preArgs = @()) {
    try {
        $p = & $exe @preArgs -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $p) { return ($p | Select-Object -First 1).Trim() }
    } catch { }
    return $null
}
 
# Busca un Python 3.11 ya instalado. Devuelve la ruta a python.exe o $null.
function Find-Python311 {
    # a) Rutas de instalación típicas (primero: no dependen del PATH de la sesión)
    $rutas = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311-arm64\python.exe"),
        (Join-Path $env:ProgramFiles "Python311\python.exe"),
        "C:\Python311\python.exe"
    )
    foreach ($r in $rutas) {
        if ((Test-Path $r) -and (Get-PyVersion $r) -eq $PyRequerido) { return $r }
    }
    # b) Lanzador oficial de Windows: py -3.11
    if (Get-Command py -ErrorAction SilentlyContinue) {
        if ((Get-PyVersion "py" @("-$PyRequerido")) -eq $PyRequerido) { return (Get-PyExe "py" @("-$PyRequerido")) }
    }
    # c) python3.11 / python en el PATH (se ignora el alias de Microsoft Store en WindowsApps)
    foreach ($n in @("python3.11", "python")) {
        $c = Get-Command $n -ErrorAction SilentlyContinue
        if ($c -and $c.Source -notlike "*\WindowsApps\*" -and (Get-PyVersion $c.Source) -eq $PyRequerido) {
            return (Get-PyExe $c.Source)
        }
    }
    return $null
}
 
# Instala Python 3.11 para el usuario actual (sin admin).
# 1º descarga directa del instalador oficial de python.org (firma verificada); 2º winget como respaldo.
function Install-Python311 {
    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "amd64" }
    $url  = "https://www.python.org/ftp/python/$PyInstalador/python-$PyInstalador-$arch.exe"
    $exe  = Join-Path $env:TEMP "python-$PyInstalador-$arch.exe"
 
    try {
        Write-Host "    ..  Descargando $url"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $prev = $ProgressPreference; $ProgressPreference = "SilentlyContinue"
        Invoke-WebRequest -Uri $url -OutFile $exe -UseBasicParsing
        $ProgressPreference = $prev
 
        $firma = Get-AuthenticodeSignature $exe
        if ($firma.Status -ne "Valid" -or $firma.SignerCertificate.Subject -notmatch "Python Software Foundation") {
            throw "La firma del instalador no es válida ($($firma.Status))."
        }
 
        Write-Host "    ..  Instalando Python $PyInstalador (silencioso, por usuario)..."
        $instArgs = @(
            "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_launcher=1",
            "InstallLauncherAllUsers=0", "Include_test=0", "Include_doc=0", "Shortcuts=0"
        )
        $p = Start-Process -FilePath $exe -ArgumentList $instArgs -Wait -PassThru
        if ($p.ExitCode -notin @(0, 3010)) { throw "El instalador terminó con código $($p.ExitCode)." }
        Ok "Python $PyInstalador instalado en $env:LOCALAPPDATA\Programs\Python\Python311"
        return
    } catch {
        Aviso "Descarga/instalación directa falló: $($_.Exception.Message)"
    } finally {
        if (Test-Path $exe) { Remove-Item $exe -Force -ErrorAction SilentlyContinue }
    }
 
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "    ..  Intentando con winget..."
& winget install -e --id Python.Python.3.11 --scope user --silent `
            --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -eq 0) { Ok "Python 3.11 instalado con winget"; return }
        Aviso "winget terminó con código $LASTEXITCODE."
    }
 
    throw ("No se pudo instalar Python $PyRequerido automáticamente (¿sin internet o bloqueado por proxy/antivirus?). " +
           "Instálalo manualmente desde https://www.python.org/downloads/release/python-3119/ " +
           "(marca 'Add python.exe to PATH') y vuelve a ejecutar el script.")
}
 
# --- 1. Python 3.11 -----------------------------------------------------------
Paso "Buscando Python $PyRequerido"
if ($Python) {
    $ver = Get-PyVersion $Python
    if ($ver -ne $PyRequerido) { throw "El Python indicado ($Python) es '$ver'; se requiere $PyRequerido." }
} else {
    $Python = Find-Python311
    if (-not $Python) {
        if ($NoInstalarPython) {
            throw "No se encontró Python $PyRequerido y se indicó -NoInstalarPython. Instálalo o pasa -Python <ruta>."
        }
        Aviso "No se encontró Python $PyRequerido. Se instalará automáticamente (solo para este usuario, sin admin)."
        Install-Python311
        $Python = Find-Python311
        if (-not $Python) {
            throw "Python $PyRequerido se instaló pero no se pudo localizar. Cierra y abre PowerShell y vuelve a ejecutar el script."
        }
    }
}
Ok "Python $PyRequerido -> $Python"
 
# --- 2. venv (recrear si está roto, incompleto, viene de otra PC o no es 3.11) -
# Borra venv\ por completo. Antes detiene procesos que lo estén usando
# (p. ej. el server.py lanzado por Claude Desktop), que bloquean python.exe.
function Remove-Venv {
    if (-not (Test-Path $Venv)) { return }
    $enUso = Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path -like "$Venv\*" }
    if ($enUso) {
        Aviso ("Deteniendo procesos que usan el venv: " + (($enUso | ForEach-Object { "$($_.Name)($($_.Id))" }) -join ", "))
        $enUso | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
    Remove-Item -Recurse -Force $Venv -ErrorAction SilentlyContinue
    if (Test-Path $Venv) {
        throw "No se pudo borrar '$Venv' por completo (archivos en uso). Cierra Claude Desktop (también desde la bandeja) y vuelve a ejecutar."
    }
}
 
Paso "Preparando entorno virtual"
$cfg = Join-Path $Venv "pyvenv.cfg"
if (Test-Path $Venv) {
    $motivo = $null
    if (-not (Test-Path $cfg))        { $motivo = "está incompleto (sin pyvenv.cfg; residuo de una instalación/borrado anterior)" }
    elseif (-not (Test-Path $VenvPy)) { $motivo = "está incompleto (falta Scripts\python.exe)" }
    else {
        $home_ = (Get-Content $cfg | Where-Object { $_ -match '^\s*home\s*=' } | Select-Object -First 1) -replace '^\s*home\s*=\s*', ''
        if (-not $home_ -or -not (Test-Path (Join-Path $home_ "python.exe"))) {
            $motivo = "apunta a '$home_' (otra PC/usuario o Python desinstalado)"
        } else {
            $venvVer = Get-PyVersion $VenvPy
            if (-not $venvVer)                 { $motivo = "no arranca" }
            elseif ($venvVer -ne $PyRequerido) { $motivo = "usa Python $venvVer (se requiere $PyRequerido)" }
        }
    }
    if ($motivo) {
        Aviso "venv $motivo. Se elimina y se recrea."
        Remove-Venv
    } else { Ok "venv existente válido (Python $PyRequerido)" }
}
 
$venvNuevo = -not (Test-Path $VenvPy)
try {
    if ($venvNuevo) {
& $Python -m venv $Venv
        if ($LASTEXITCODE -ne 0) { throw "Falló la creación del venv." }
        Ok "venv creado con Python $PyRequerido"
    }
 
    Paso "Instalando dependencias"
    # --no-cache-dir: no deja la caché de pip en %LOCALAPPDATA%\pip\cache
    $pipOpts = @("--disable-pip-version-check", "--no-cache-dir", "-q")
& $VenvPy -m pip install @pipOpts --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "Falló la actualización de pip." }
& $VenvPy -m pip install @pipOpts fastmcp python-dotenv pyodbc
    if ($LASTEXITCODE -ne 0) { throw "Falló pip install." }
& $VenvPy -c "import fastmcp, pyodbc, dotenv"
    if ($LASTEXITCODE -ne 0) { throw "Las dependencias no se importan correctamente." }
} catch {
    # Si el venv se creó en esta ejecución y algo falló, no dejar un venv a medias.
    if ($venvNuevo) {
        Aviso "Limpiando el venv incompleto..."
        try { Remove-Venv } catch { Aviso $_.Exception.Message }
    }
    throw
}
Ok "fastmcp, python-dotenv, pyodbc"
 
# --- 3. Driver ODBC y .env ----------------------------------------------------
Paso "Verificando driver ODBC"
$drivers = Get-OdbcDriver -ErrorAction SilentlyContinue | Where-Object Name -like "ODBC Driver * for SQL Server" | Select-Object -ExpandProperty Name -Unique
if ($drivers) { Ok ($drivers -join ", ") } else { Aviso "No hay 'ODBC Driver 18 for SQL Server'. Descárgalo del sitio de Microsoft e instálalo." }
 
Paso "Verificando .env"
if (-not (Test-Path $EnvFile)) {
    $plantilla = @"
DB_DRIVER="ODBC Driver 18 for SQL Server"
DB_SERVER=172.17.0.141
DB_NAME=SIFRAH_DWH
DB_USER=
DB_PASSWORD=
MCP_TRANSPORT=stdio
 
# Rutas relativas = relativas a esta carpeta (sifrah_mcp_sql), en cualquier PC.
MCP_EXPORT_DIR=../exports
MCP_EXPORT_TTL_S=600
MCP_EXPORT_FETCH_MAX_BYTES=6000000
"@
    [IO.File]::WriteAllText($EnvFile, $plantilla, $Utf8)
    Aviso "Se creó .env de plantilla: completa DB_USER y DB_PASSWORD y vuelve a ejecutar."
} else {
    $faltan = @("DB_SERVER", "DB_USER", "DB_PASSWORD") | Where-Object {
        -not (Select-String -Path $EnvFile -Pattern "^\s*$_\s*=\s*\S" -Quiet)
    }
    if ($faltan) { Aviso ("Faltan valores en .env: " + ($faltan -join ", ")) } else { Ok ".env con credenciales" }
    if (Select-String -Path $EnvFile -Pattern '^\s*MCP_EXPORT_DIR\s*=\s*[A-Za-z]:\\Users\\' -Quiet) {
        Aviso "MCP_EXPORT_DIR tiene una ruta absoluta de usuario; usa MCP_EXPORT_DIR=../exports para que sea portable."
    }
}
 
# --- 4. Carpeta de exports ----------------------------------------------------
Paso "Carpeta de exports"
$exportDir = & $VenvPy -c "import sys; sys.path.insert(0, r'$Root'); from config import settings; print(settings.export_dir)"
New-Item -ItemType Directory -Force $exportDir | Out-Null
Ok $exportDir
 
# --- 5. Registro en Claude ----------------------------------------------------
if ($SinClaude) { Paso "Listo (sin registrar en Claude por -SinClaude)"; exit 0 }
 
Paso "Registrando en Claude Desktop"
if (-not $DesktopConfig) {
    $candidatos = @(Join-Path $env:APPDATA "Claude\claude_desktop_config.json")
    $candidatos += Get-ChildItem (Join-Path $env:LOCALAPPDATA "Packages") -Directory -Filter "Claude_*" -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName "LocalCache\Roaming\Claude\claude_desktop_config.json" }
    $DesktopConfig = $candidatos | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $DesktopConfig -and (Test-Path (Join-Path $env:APPDATA "Claude"))) { $DesktopConfig = $candidatos[0] }
}
if (-not $DesktopConfig) {
    Aviso "No se encontró Claude Desktop instalado; se omite."
} else {
    if (Test-Path $DesktopConfig) {
        $raw = [IO.File]::ReadAllText($DesktopConfig, $Utf8)
        Copy-Item $DesktopConfig "$DesktopConfig.bak" -Force
        $conf = if ($raw.Trim()) { $raw | ConvertFrom-Json } else { New-Object PSObject }
    } else { $conf = New-Object PSObject }
 
    if (-not ($conf.PSObject.Properties.Name -contains "mcpServers")) {
        $conf | Add-Member -NotePropertyName mcpServers -NotePropertyValue (New-Object PSObject)
    }
    $entry = [pscustomobject]@{ command = $VenvPy; args = @($ServerPy) }
    if ($conf.mcpServers.PSObject.Properties.Name -contains "sifrah-sql-dwh") {
        $conf.mcpServers."sifrah-sql-dwh" = $entry
    } else {
        $conf.mcpServers | Add-Member -NotePropertyName "sifrah-sql-dwh" -NotePropertyValue $entry
    }
    [IO.File]::WriteAllText($DesktopConfig, (ConvertTo-Json -InputObject $conf -Depth 100), $Utf8)
    Ok "$DesktopConfig (backup: .bak)"
    Aviso "Cierra Claude Desktop por completo (también desde la bandeja) y ábrelo de nuevo."
}
 
Paso "Registrando en Claude Code"
if (Get-Command claude -ErrorAction SilentlyContinue) {
& claude mcp remove sifrah-sql-dwh --scope user *> $null
& claude mcp add sifrah-sql-dwh --scope user -- $VenvPy $ServerPy
    if ($LASTEXITCODE -eq 0) { Ok "claude mcp add (scope user)" } else { Aviso "Falló 'claude mcp add'." }
} else {
    Aviso "Claude Code no está instalado; se omite."
}
 
Paso "Instalación terminada (Python $PyRequerido)"