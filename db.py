"""
db.py
Capa de acceso a datos: conexión a SQL Server y ejecución de consultas con
límites de filas y de tiempo. Estas funciones son SÍNCRONAS a propósito: FastMCP
ejecuta cada tool en un hilo aparte (run_in_thread=True, por defecto) y aplica el
timeout "duro" desde fuera (ver server.py, parámetro `timeout=` de @mcp.tool()).
Así, una consulta lenta nunca bloquea el loop de eventos ni deja al agente
esperando más de lo configurado.
"""
from __future__ import annotations

import csv
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import pyodbc

from config import settings

logger = logging.getLogger("sifrah_mcp.db")

# Limita cuántas conexiones/consultas concurrentes se abren contra SQL Server,
# para no saturar la base ni abrir conexiones sin control.
_query_semaphore = threading.Semaphore(settings.max_concurrent_queries)


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    elapsed_ms: int


def _connection_string() -> str:
    # return (
    #     f"DRIVER={{{settings.db_driver}}};"
    #     f"SERVER={settings.db_server},{settings.db_port};"
    #     f"DATABASE={settings.db_name};"
    #     f"UID={settings.db_user};"
    #     f"PWD={settings.db_password};"
    #     f"Encrypt={'yes' if settings.db_encrypt else 'no'};"
    #     f"TrustServerCertificate={'yes' if settings.db_trust_server_cert else 'no'};"
    #     f"Connection Timeout={settings.connect_timeout_s};"
    # )


    return (
        f"DRIVER={{{settings.db_driver}}};"
        f"SERVER={settings.db_server},{settings.db_port};"
        f"DATABASE={settings.db_name};"
        f"UID={settings.db_user};"
        f"PWD={settings.db_password};"
        f"Encrypt=yes;"
        f"TrustServerCertificate=yes;"
        f"Connection Timeout={settings.connect_timeout_s};"
    )


def _connect() -> pyodbc.Connection:
    conn = pyodbc.connect(_connection_string(), timeout=settings.connect_timeout_s)
    # Timeout de ejecución a nivel de driver ODBC (SQL_ATTR_QUERY_TIMEOUT).
    # Es "best-effort": protege la mayoría de consultas, pero no todos los
    # drivers/escenarios lo respetan al 100%. Por eso también existe el timeout
    # duro a nivel de servidor MCP (ver server.py).
    conn.timeout = settings.query_timeout_s
    return conn


def run_query(sql: str, max_rows: int) -> QueryResult:
    """Ejecuta un SELECT y devuelve hasta max_rows filas. Lanza pyodbc.Error si falla."""
    start = time.monotonic()
    if not _query_semaphore.acquire(timeout=settings.hard_timeout_s):
        raise TimeoutError(
            f"El servidor ya tiene {settings.max_concurrent_queries} consultas en curso; "
            "no se pudo obtener un turno a tiempo. Intenta de nuevo en unos segundos."
        )
    try:
        conn = _connect()
        try:
            cursor = conn.cursor()
            cursor.execute(sql)

            if cursor.description is None:
                return QueryResult(columns=[], rows=[], row_count=0, truncated=False,
                                    elapsed_ms=int((time.monotonic() - start) * 1000))

            columns = [col[0] for col in cursor.description]
            fetched = cursor.fetchmany(max_rows)
            truncated = cursor.fetchone() is not None  # ¿quedaban más filas?

            rows = [dict(zip(columns, row)) for row in fetched]
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return QueryResult(columns=columns, rows=rows, row_count=len(rows),
                                truncated=truncated, elapsed_ms=elapsed_ms)
        finally:
            conn.close()
    finally:
        _query_semaphore.release()


def export_query_to_csv(sql: str, max_rows: int, filepath: str) -> tuple[list[str], int, bool]:
    """Ejecuta un SELECT y escribe el resultado (hasta max_rows filas) como CSV."""
    if not _query_semaphore.acquire(timeout=settings.hard_timeout_s):
        raise TimeoutError(
            f"El servidor ya tiene {settings.max_concurrent_queries} consultas en curso; "
            "no se pudo obtener un turno a tiempo. Intenta de nuevo en unos segundos."
        )
    try:
        conn = _connect()
        try:
            cursor = conn.cursor()
            cursor.execute(sql)
            if cursor.description is None:
                raise RuntimeError("La consulta no devolvió columnas (no es un SELECT válido).")
            columns = [col[0] for col in cursor.description]

            row_count = 0
            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(columns)
                while row_count < max_rows:
                    batch = cursor.fetchmany(min(1000, max_rows - row_count))
                    if not batch:
                        break
                    writer.writerows(batch)
                    row_count += len(batch)
                truncated = row_count >= max_rows and cursor.fetchone() is not None

            return columns, row_count, truncated
        finally:
            conn.close()
    finally:
        _query_semaphore.release()


def ping() -> bool:
    """Chequeo rápido de salud (usado por /health). No lanza excepciones."""
    try:
        result = run_query("SELECT 1 AS ok", max_rows=1)
        return len(result.rows) == 1
    except Exception:  # noqa: BLE001 - un ping nunca debe tumbar el healthcheck
        logger.warning("Healthcheck de base de datos falló.", exc_info=True)
        return False


def pyodbc_error_types():
    """Import perezoso: evita que otros módulos fallen al cargar si pyodbc/el
    driver ODBC aún no están instalados (por ejemplo, al solo revisar el código)."""
    import pyodbc

    return pyodbc.Error
