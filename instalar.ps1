<#
instalar.ps1 - Instala el servidor MCP sifrah-sql-dwh en ESTA PC, para el usuario actual.

Uso (desde la carpeta sifrah_mcp_sql):
    powershell -ExecutionPolicy Bypass -File .\instalar.ps1

Opciones:
    -Python <ruta>        Python 3.11 a usar (por defecto: se busca con 'py -3.11', luego en PATH y rutas típicas).
    -SinClaude            Solo prepara el entorno; no registra nada en Claude.
    -DesktopConfig <ruta> Ruta de claude_desktop_config.json (se detecta sola).

Qué hace:
  1. Localiza Python 3.11 (obligatorio).
  2. Recrea venv\ si no existe, si fue copiado de otra PC o si no es Python 3.11.
  3. Instala dependencias.
  4. Verifica el driver ODBC y el .env (crea una plantilla si no hay).
  5. Crea la carpeta de exports.
  6. Registra el servidor en Claude Desktop (con backup) y en Claude Code (si está instalado).
#>
param(
    [string]$Python = "",
    [switch]$SinClaude,
    [string]$DesktopConfig = ""
)

$ErrorActionPreference = "Stop"
$PyRequerido = "3.11"
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

# --- 1. Python 3.11 -----------------------------------------------------------
Paso "Buscando Python $PyRequerido"
if ($Python) {
    $ver = Get-PyVersion $Python
    if ($ver -ne $PyRequerido) { throw "El Python indicado ($Python) es '$ver'; se requiere $PyRequerido." }
} else {
    # a) Lanzador oficial de Windows: py -3.11
    if (Get-Command py -ErrorAction SilentlyContinue) {
        if ((Get-PyVersion "py" @("-$PyRequerido")) -eq $PyRequerido) {
            $Python = Get-PyExe "py" @("-$PyRequerido")
        }
    }
    # b) python3.11 / python en el PATH
    if (-not $Python) {
        foreach ($n in @("python3.11", "python")) {
            $c = Get-Command $n -ErrorAction SilentlyContinue
            if ($c -and (Get-PyVersion $c.Source) -eq $PyRequerido) { $Python = Get-PyExe $c.Source; break }
        }
    }
    # c) Rutas de instalación típicas
    if (-not $Python) {
        $rutas = @(
            (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
            (Join-Path $env:ProgramFiles "Python311\python.exe"),
            "C:\Python311\python.exe"
        )
        $Python = $rutas | Where-Object { (Test-Path $_) -and ((Get-PyVersion $_) -eq $PyRequerido) } | Select-Object -First 1
    }
    if (-not $Python) {
        throw "No se encontró Python $PyRequerido. Instálalo (https://www.python.org/downloads/release/python-3119/ o 'winget install Python.Python.3.11') o pasa -Python <ruta>."
    }
}
Ok "Python $PyRequerido -> $Python"

# --- 2. venv (recrear si está roto, viene de otra PC o no es 3.11) -----------
Paso "Preparando entorno virtual"
$cfg = Join-Path $Venv "pyvenv.cfg"
if (Test-Path $cfg) {
    $home_ = (Get-Content $cfg | Where-Object { $_ -match '^\s*home\s*=' }) -replace '^\s*home\s*=\s*', ''
    $motivo = $null
    if (-not (Test-Path $VenvPy)) { $motivo = "falta Scripts\python.exe" }
    elseif (-not (Test-Path (Join-Path $home_ "python.exe"))) { $motivo = "apunta a '$home_' (otra PC/usuario o Python desinstalado)" }
    else {
        $venvVer = Get-PyVersion $VenvPy
        if ($venvVer -ne $PyRequerido) { $motivo = "usa Python $venvVer (se requiere $PyRequerido)" }
    }
    if ($motivo) {
        Aviso "venv $motivo. Se recrea."
        Remove-Item -Recurse -Force $Venv
    } else { Ok "venv existente válido (Python $PyRequerido)" }
}
if (-not (Test-Path $VenvPy)) {
    & $Python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "Falló la creación del venv." }
    Ok "venv creado con Python $PyRequerido"
}

Paso "Instalando dependencias"
& $VenvPy -m pip install --disable-pip-version-check -q --upgrade pip
& $VenvPy -m pip install --disable-pip-version-check -q fastmcp python-dotenv pyodbc
if ($LASTEXITCODE -ne 0) { throw "Falló pip install." }
& $VenvPy -c "import fastmcp, pyodbc, dotenv"
if ($LASTEXITCODE -ne 0) { throw "Las dependencias no se importan correctamente." }
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