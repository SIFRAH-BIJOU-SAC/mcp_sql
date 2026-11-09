"""
config.py
Carga y valida la configuración del servidor MCP desde variables de entorno (.env).
Ningún dato sensible vive en el código: todo viene de .env (ver .env.example).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Carpeta del proyecto (donde vive este archivo). NO depende del directorio de
# trabajo del proceso: Claude Desktop suele lanzar el servidor desde una
# carpeta sin permisos de escritura (p. ej. C:\Windows\System32).
BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")


def _get_path(name: str, default: str) -> str:
    """Ruta absoluta desde una variable de entorno. Las rutas relativas se
    resuelven contra la carpeta del proyecto, nunca contra el cwd."""
    raw = (os.getenv(name) or "").strip() or default
    path = Path(os.path.expandvars(raw)).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return str(path.resolve())


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"La variable de entorno {name}='{raw}' no es un entero válido.") from exc


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # --- Conexión a SQL Server ---
    db_driver: str = os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server")
    db_server: str = os.getenv("DB_SERVER", "")
    db_port: str = os.getenv("DB_PORT", "1433")
    db_name: str = os.getenv("DB_NAME", "SIFRAH_DWH")
    db_user: str = os.getenv("DB_USER", "")
    db_password: str = os.getenv("DB_PASSWORD", "")
    db_encrypt: bool = _get_bool("DB_ENCRYPT", True)
    db_trust_server_cert: bool = _get_bool("DB_TRUST_SERVER_CERT", False)

    # --- Timeouts (segundos) ---
    # 1) connect_timeout_s: cuánto se espera para abrir la conexión TCP/login.
    # 2) query_timeout_s: timeout de ejecución a nivel de driver ODBC. Este es
    #    el límite REAL de cuánto puede durar una consulta en SQL Server, tanto
    #    en el camino rápido como en un job de segundo plano. Si esperas
    #    reportes de varios minutos, súbelo (ej. 300).
    # 3) hard_timeout_s: no es un límite de la consulta, es el límite de cuánto
    #    espera el AGENTE una respuesta síncrona antes de que la consulta pase
    #    a correr en segundo plano como "job" (ver jobs.py). Puede quedarse
    #    bajo (20-30s) sin problema: no trunca la consulta, solo decide cuándo
    #    dejar de esperar y devolver un job_id en su lugar.
    connect_timeout_s: int = _get_int("DB_CONNECT_TIMEOUT_S", 5)
    query_timeout_s: int = _get_int("DB_QUERY_TIMEOUT_S", 120)
    hard_timeout_s: int = _get_int("MCP_HARD_TIMEOUT_S", 20)

    # --- Jobs en segundo plano (consultas que no terminan a tiempo) ---
    # Cuánto se conserva en memoria el resultado (o el error) de un job ya
    # terminado, para que el agente lo pueda recoger con get_query_result.
    job_result_ttl_s: int = _get_int("MCP_JOB_RESULT_TTL_S", 1800)

    # --- Límites de filas ---
    default_max_rows: int = _get_int("MCP_DEFAULT_MAX_ROWS", 200)
    absolute_max_rows: int = _get_int("MCP_ABSOLUTE_MAX_ROWS", 5000)
    export_max_rows: int = _get_int("MCP_EXPORT_MAX_ROWS", 50000)

    # --- Concurrencia (cuántas consultas simultáneas se permiten contra SQL Server) ---
    max_concurrent_queries: int = _get_int("MCP_MAX_CONCURRENT_QUERIES", 4)

    # --- Seguridad ---
    # Por defecto SOLO se permiten SELECT/WITH. No lo actives salvo necesidad real.
    allow_write_queries: bool = _get_bool("ALLOW_WRITE_QUERIES", False)

    # --- Exportación a CSV ---
    # Siempre absoluta (ver _get_path). Si la pones relativa en .env, se toma
    # relativa a la carpeta del proyecto.
    export_dir: str = _get_path("MCP_EXPORT_DIR", "exports")
    # Los CSV se borran al servirse o al cumplir este TTL (lo que pase primero).
    export_ttl_s: int = _get_int("MCP_EXPORT_TTL_S", 600)
    # Tope de tamaño para devolver un CSV completo en línea con fetch_export_csv.
    export_fetch_max_bytes: int = _get_int("MCP_EXPORT_FETCH_MAX_BYTES", 6_000_000)

    # --- Transporte del servidor MCP ---
    # "stdio" -> Claude Desktop / Claude Code (proceso local, un usuario)
    # "http"  -> servidor de red, varios agentes/usuarios pueden conectarse
    mcp_transport: str = os.getenv("MCP_TRANSPORT", "stdio")
    mcp_host: str = os.getenv("MCP_HOST", "0.0.0.0")
    mcp_port: int = _get_int("MCP_PORT", 8000)

    def validate(self) -> None:
        missing = [
            name
            for name, value in (
                ("DB_SERVER", self.db_server),
                ("DB_USER", self.db_user),
                ("DB_PASSWORD", self.db_password),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Faltan variables de entorno obligatorias en .env: " + ", ".join(missing)
                + ". Copia .env.example a .env y complétalo."
            )


settings = Settings()
