"""
server.py
Servidor MCP (FastMCP) que expone herramientas de consulta SQL de SOLO LECTURA
contra el Data Warehouse SIFRAH_DWH (SQL Server), para que Claude (o cualquier
otro agente compatible con MCP) pueda consultarlo sin poder modificarlo y sin
quedar nunca colgado esperando una respuesta.

Ejecutar:
    python server.py
        -> usa MCP_TRANSPORT del .env (por defecto "stdio", para Claude
           Desktop / Claude Code).

    MCP_TRANSPORT=http python server.py
        -> levanta un servidor HTTP (útil para que varios agentes/usuarios se
           conecten de forma remota). Expone además GET /health.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

import db
import engine
import exports
import jobs
from config import settings
from sql_guard import UnsafeQueryError, ensure_read_only

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("sifrah_mcp.server")

settings.validate()
exports.start_sweeper()  # borra CSV con más de MCP_EXPORT_TTL_S (revisa cada 60s)

GLOSARIO_PATH = Path(__file__).parent / "schema" / "glosario_tablas_sifrah.md"

mcp = FastMCP(
    name="sifrah-sql-dwh",
    instructions=(
        "Servidor de consultas SQL de SOLO LECTURA contra SIFRAH_DWH (SQL Server). "
        "Antes de escribir una consulta, lee el recurso 'schema://sifrah_dwh/glosario' "
        "para conocer tablas, columnas, llaves y convenciones de nombres (acentos, "
        "sufijos _V2, prefijos Flag_, etc.). Usa 'list_tables' y 'describe_table' "
        "para confirmar nombres exactos de columnas antes de una consulta compleja. "
        "Usa 'run_query' para vistas previas (hasta unos cientos de filas) y "
        "'export_query_csv' cuando esperes miles de filas; los CSV son temporales "
        "(se borran a los MCP_EXPORT_TTL_S segundos o al leerlos con "
        "'fetch_export_csv', que devuelve el contenido y borra el archivo). Si el "
        "CSV supera MCP_EXPORT_FETCH_MAX_BYTES (6 MB), no lo pidas en línea: léelo "
        "desde disco en 'file_path' (pandas/chunks). Si una consulta es "
        "pesada y tarda más de unos segundos, ambas tools devuelven "
        "{status: 'running', job_id: ...} en vez de bloquear: sigue la "
        "conversación con normalidad y usa 'get_query_result(job_id)' más "
        "tarde para recoger el resultado."
    ),
)


# ---------------------------------------------------------------------------
# Recurso: expone el glosario documentado como contexto de esquema para el agente
# ---------------------------------------------------------------------------
@mcp.resource("schema://sifrah_dwh/glosario")
def get_glosario() -> str:
    """Glosario documentado de tablas/columnas de SIFRAH_DWH (SQL Server)."""
    if not GLOSARIO_PATH.exists():
        return "# Glosario no encontrado\nColoca el archivo en schema/glosario_tablas_sifrah.md"
    return GLOSARIO_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@mcp.tool()
async def run_query(sql: str, max_rows: int | None = None, output_format: str = "json") -> dict:
    """
    Ejecuta una consulta SQL de SOLO LECTURA (SELECT, o CTE con WITH) contra
    SIFRAH_DWH y devuelve una vista previa de los resultados.

    Args:
        sql: Una única sentencia SELECT/WITH. No se permiten INSERT/UPDATE/DELETE/
            DDL ni múltiples sentencias separadas por ';'.
        max_rows: Máximo de filas a devolver en línea (por defecto
            MCP_DEFAULT_MAX_ROWS del .env; tope absoluto MCP_ABSOLUTE_MAX_ROWS).
            Para conjuntos grandes usa 'export_query_csv' en vez de subir este número.
        output_format: "json" (por defecto; recomendado para que el agente razone
            sobre los datos como estructura) o "markdown" (tabla legible en texto).

    Returns:
        dict con ok, status ("done" o "running"), columns, rows (o
        data_markdown), row_count, truncated, elapsed_ms. Si la consulta tarda
        más de MCP_HARD_TIMEOUT_S, devuelve status="running" y un job_id en
        vez de bloquear — recoge el resultado después con get_query_result.
        Si algo falla, devuelve {"ok": False, "error": "..."} en vez de lanzar
        una excepción que interrumpa la conversación del agente.
    """
    limit = min(max_rows or settings.default_max_rows, settings.absolute_max_rows)

    try:
        ensure_read_only(sql, allow_write=settings.allow_write_queries)
    except UnsafeQueryError as exc:
        return {"ok": False, "error": str(exc)}

    jobs.cleanup_expired(settings.job_result_ttl_s)

    try:
        status, payload = await engine.run_or_defer(
            "preview", sql, db.run_query, sql, limit,
            timeout_s=settings.hard_timeout_s,
            limit=limit, output_format=output_format,
        )
    except db.pyodbc_error_types() as exc:
        logger.warning("Error de SQL Server en run_query: %s", exc)
        return {"ok": False, "error": f"Error de SQL Server: {exc}"}
    except Exception as exc:  # noqa: BLE001 - última red: nunca tumbar el servidor
        logger.exception("Error inesperado en run_query")
        return {"ok": False, "error": f"Error inesperado: {exc}"}

    if status == "running":
        return engine.running_payload(payload, settings.hard_timeout_s, f"get_query_result(job_id='{payload}')")

    return engine.build_preview_payload(payload, limit, output_format)


@mcp.tool()
async def export_query_csv(sql: str, filename: str | None = None, max_rows: int | None = None) -> dict:
    """
    Ejecuta una consulta SELECT y exporta el resultado completo (hasta un tope de
    seguridad MCP_EXPORT_MAX_ROWS) a un archivo CSV en el servidor, en lugar de
    devolverlo en línea. Úsala cuando esperes miles de filas: evita saturar el
    contexto del agente con una respuesta enorme.

    Args:
        sql: Una única sentencia SELECT/WITH.
        filename: Nombre base opcional para el archivo (sin extensión).
        max_rows: Tope de filas a exportar (por defecto MCP_EXPORT_MAX_ROWS).

    Returns:
        dict con ok, status ("done" o "running"), file_path, columns, row_count,
        truncated. Si tarda más de 3×MCP_HARD_TIMEOUT_S, devuelve
        status="running" y un job_id — recoge el resultado con get_query_result.
    """
    limit = min(max_rows or settings.export_max_rows, settings.export_max_rows)

    try:
        ensure_read_only(sql, allow_write=settings.allow_write_queries)
    except UnsafeQueryError as exc:
        return {"ok": False, "error": str(exc)}

    export_dir = Path(settings.export_dir)
    try:
        export_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error("No se pudo crear la carpeta de exportación %s: %s", export_dir, exc)
        return {
            "ok": False,
            "error": f"No se pudo crear la carpeta de exportación: {exc}. "
                     "Revisa MCP_EXPORT_DIR en .env.",
            "export_dir": str(export_dir),
        }
    base_name = filename or f"query_{int(time.time())}"
    base_name = "".join(c for c in base_name if c.isalnum() or c in ("-", "_")) or "query"
    filepath = export_dir / f"{base_name}.csv"

    jobs.cleanup_expired(settings.job_result_ttl_s)
    exports.sweep_expired()

    try:
        status, payload = await engine.run_or_defer(
            "export", sql, db.export_query_to_csv, sql, limit, str(filepath),
            timeout_s=settings.hard_timeout_s * 3,  # exportar más filas puede tardar más
            filepath=str(filepath),
        )
    except db.pyodbc_error_types() as exc:
        logger.warning("Error de SQL Server en export_query_csv: %s", exc)
        return {"ok": False, "error": f"Error de SQL Server: {exc}"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error inesperado en export_query_csv")
        return {"ok": False, "error": f"Error inesperado: {exc}"}

    if status == "running":
        return engine.running_payload(
            payload, settings.hard_timeout_s * 3, f"get_query_result(job_id='{payload}')"
        )

    columns, row_count, truncated = payload
    return engine.build_export_payload(columns, row_count, truncated, str(filepath))


@mcp.tool()
async def fetch_export_csv(file_name: str) -> dict:
    """
    Devuelve el contenido completo de un CSV generado por export_query_csv y lo
    BORRA del disco (cada export se sirve una sola vez). Si no se recoge, el
    archivo se borra solo a los MCP_EXPORT_TTL_S segundos de creado.

    Args:
        file_name: El "file_name" que devolvió export_query_csv (ej. "ventas_2025.csv").

    Returns:
        {"ok": True, "file_name", "size_bytes", "deleted", "csv": "<contenido>"}.
        Si el archivo supera MCP_EXPORT_FETCH_MAX_BYTES, NO se sirve ni se borra
        y devuelve ok=False con la ruta en disco.
    """
    exports.sweep_expired()
    try:
        return await asyncio.to_thread(
            exports.read_and_delete, file_name, settings.export_fetch_max_bytes
        )
    except (FileNotFoundError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "export_dir": settings.export_dir}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error inesperado en fetch_export_csv")
        return {"ok": False, "error": f"Error inesperado: {exc}"}


@mcp.tool()
async def list_tables(schema: str = "dbo") -> dict:
    """Lista las tablas/vistas disponibles en el esquema indicado (por defecto 'dbo')."""
    if not schema.replace("_", "").isalnum():
        return {"ok": False, "error": "Nombre de esquema inválido."}
    sql = (
        "SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES "
        f"WHERE TABLE_SCHEMA = '{schema}' ORDER BY TABLE_NAME"
    )
    try:
        ensure_read_only(sql)
        result = await engine.call_with_timeout(db.run_query, sql, 500, timeout_s=settings.hard_timeout_s)
    except (UnsafeQueryError, TimeoutError) as exc:
        return {"ok": False, "error": str(exc)}
    except db.pyodbc_error_types() as exc:
        return {"ok": False, "error": f"Error de SQL Server: {exc}"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error inesperado en list_tables")
        return {"ok": False, "error": f"Error inesperado: {exc}"}
    return {"ok": True, "schema": schema, "tables": result.rows}


@mcp.tool()
async def describe_table(table_name: str) -> dict:
    """
    Devuelve las columnas REALES (nombre, tipo, longitud, nullable) de una tabla
    de SIFRAH_DWH, consultando INFORMATION_SCHEMA.COLUMNS en vivo. Úsalo para
    confirmar los tipos que el glosario marca como 'inferidos', o para revisar
    una tabla que aún no está documentada (ej. DIM_TIENDA).
    """
    if not table_name.replace("_", "").isalnum():
        return {"ok": False, "error": "Nombre de tabla inválido."}
    sql = (
        "SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, "
        "NUMERIC_PRECISION, NUMERIC_SCALE, IS_NULLABLE, ORDINAL_POSITION "
        "FROM INFORMATION_SCHEMA.COLUMNS "
        f"WHERE TABLE_NAME = '{table_name}' ORDER BY ORDINAL_POSITION"
    )
    try:
        result = await engine.call_with_timeout(db.run_query, sql, 500, timeout_s=settings.hard_timeout_s)
    except TimeoutError as exc:
        return {"ok": False, "error": str(exc)}
    except db.pyodbc_error_types() as exc:
        return {"ok": False, "error": f"Error de SQL Server: {exc}"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error inesperado en describe_table")
        return {"ok": False, "error": f"Error inesperado: {exc}"}
    if not result.rows:
        return {"ok": False, "error": f"No se encontraron columnas para la tabla '{table_name}'."}
    return {"ok": True, "table": table_name, "columns": result.rows}


@mcp.tool()
async def get_query_result(job_id: str) -> dict:
    """
    Recoge el resultado de una consulta que quedó corriendo en segundo plano
    (run_query o export_query_csv devolvieron status="running" y este job_id).
    Puedes llamarla varias veces mientras el estado siga siendo "running"; no
    hay penalidad por consultar de más.

    Returns:
        Si sigue corriendo: {"ok": True, "status": "running", "elapsed_s": ...}.
        Si terminó bien: el mismo payload que run_query/export_query_csv habrían
        devuelto, con "status": "done".
        Si falló: {"ok": False, "status": "failed", "error": "..."}.
        Si el job no existe (id inválido o ya expiró): {"ok": False, "error": "..."}.
    """
    jobs.cleanup_expired(settings.job_result_ttl_s)
    try:
        payload = engine.job_result_payload(job_id)
    except db.pyodbc_error_types() as exc:
        logger.warning("Error de SQL Server en job %s: %s", job_id, exc)
        return {"ok": False, "status": "failed", "error": f"Error de SQL Server: {exc}"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error inesperado recuperando job %s", job_id)
        return {"ok": False, "status": "failed", "error": f"Error inesperado: {exc}"}

    if payload is None:
        return {
            "ok": False,
            "error": f"No se encontró el job '{job_id}'. Puede no existir, haber "
                     f"expirado (MCP_JOB_RESULT_TTL_S={settings.job_result_ttl_s}s "
                     "tras terminar), o ya haber sido recogido antes.",
        }
    return payload


@mcp.tool()
async def list_jobs() -> dict:
    """Lista las consultas que siguen corriendo en segundo plano o que terminaron
    hace poco y aún no fueron recogidas con get_query_result. Útil si perdiste
    el job_id o quieres ver qué sigue pendiente."""
    jobs.cleanup_expired(settings.job_result_ttl_s)
    items = [
        {
            "job_id": j.id,
            "kind": j.kind,
            "status": "done" if j.task.done() else "running",
            "elapsed_s": round(time.monotonic() - j.created_at, 1),
            "sql_preview": j.sql_preview,
        }
        for j in jobs.list_jobs()
    ]
    return {"ok": True, "jobs": items}


# ---------------------------------------------------------------------------
# Healthcheck (solo aplica cuando el servidor corre como HTTP, no en stdio)
# ---------------------------------------------------------------------------
@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    # Corre en un hilo con timeout corto: un healthcheck nunca debe bloquear
    # el event loop ni tardar tanto como una consulta normal.
    try:
        db_ok = await engine.call_with_timeout(db.ping, timeout_s=min(5, settings.hard_timeout_s))
    except Exception:  # noqa: BLE001
        db_ok = False
    status_code = 200 if db_ok else 503
    return JSONResponse(
        {"status": "ok" if db_ok else "degraded", "db_reachable": db_ok},
        status_code=status_code,
    )


if __name__ == "__main__":
    logger.info("Iniciando servidor MCP 'sifrah-sql-dwh' (transporte=%s)", settings.mcp_transport)
    if settings.mcp_transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport=settings.mcp_transport, host=settings.mcp_host, port=settings.mcp_port)
