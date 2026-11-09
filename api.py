"""
api.py
Wrapper OPCIONAL en FastAPI sobre el mismo motor de consultas (db.py, jobs.py,
engine.py, sql_guard.py) que usa server.py (MCP). Mismo comportamiento ante
consultas lentas: si no terminan a tiempo, pasan a segundo plano como job en
vez de fallar o bloquear la petición HTTP — ver README, sección "¿Y si la
consulta dura minutos?".

¿Cuándo usar esto en vez de (o además de) server.py?
  - Para probar consultas con curl/Postman sin hablar el protocolo MCP.
  - Para exponer un /health independiente que un orquestador externo (Docker
    healthcheck, Kubernetes liveness/readiness probe, uptime monitor) pueda
    golpear con HTTP plano.
  - Como respaldo si en el futuro algún sistema necesita hablar REST en vez
    de MCP contra este mismo DWH, sin duplicar la lógica de conexión/guardas.

server.py YA puede correr como servidor HTTP (MCP_TRANSPORT=http) y expone su
propio GET /health. Usa api.py solo si necesitas de verdad una API REST aparte.

Ejecutar:
    uvicorn api:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

import db
import engine
import exports
import jobs
from config import settings
from sql_guard import UnsafeQueryError, ensure_read_only

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("sifrah_mcp.api")

settings.validate()
exports.start_sweeper()  # borra CSV con más de MCP_EXPORT_TTL_S (revisa cada 60s)

app = FastAPI(
    title="Sifrah SQL DWH · API de respaldo",
    description="Interfaz REST opcional sobre el motor de consultas de solo lectura de SIFRAH_DWH.",
    version="1.0.0",
)


class QueryRequest(BaseModel):
    sql: str
    max_rows: int | None = Field(default=None, ge=1)
    output_format: Literal["json", "markdown"] = "json"


class ExportRequest(BaseModel):
    sql: str
    filename: str | None = None
    max_rows: int | None = Field(default=None, ge=1)


@app.get("/health")
async def health():
    try:
        db_ok = await engine.call_with_timeout(db.ping, timeout_s=min(5, settings.hard_timeout_s))
    except Exception:  # noqa: BLE001
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "db_reachable": db_ok}


@app.post("/query")
async def query(req: QueryRequest):
    """Igual que la tool MCP run_query. Si la consulta no termina a tiempo,
    devuelve {"status": "running", "job_id": ...} — recógelo con GET /jobs/{job_id}."""
    limit = min(req.max_rows or settings.default_max_rows, settings.absolute_max_rows)
    try:
        ensure_read_only(req.sql, allow_write=settings.allow_write_queries)
    except UnsafeQueryError as exc:
        return {"ok": False, "error": str(exc)}

    jobs.cleanup_expired(settings.job_result_ttl_s)

    try:
        status, payload = await engine.run_or_defer(
            "preview", req.sql, db.run_query, req.sql, limit,
            timeout_s=settings.hard_timeout_s,
            limit=limit, output_format=req.output_format,
        )
    except db.pyodbc_error_types() as exc:
        logger.warning("Error de SQL Server en /query: %s", exc)
        return {"ok": False, "error": f"Error de SQL Server: {exc}"}
    except Exception as exc:  # noqa: BLE001 - nunca tumbar el proceso por una query
        logger.exception("Error inesperado en /query")
        return {"ok": False, "error": f"Error inesperado: {exc}"}

    if status == "running":
        return engine.running_payload(payload, settings.hard_timeout_s, f"GET /jobs/{payload}")
    return engine.build_preview_payload(payload, limit, req.output_format)


@app.post("/export")
async def export(req: ExportRequest):
    """Igual que la tool MCP export_query_csv. Si no termina a tiempo, devuelve
    {"status": "running", "job_id": ...} — recógelo con GET /jobs/{job_id}."""
    limit = min(req.max_rows or settings.export_max_rows, settings.export_max_rows)
    try:
        ensure_read_only(req.sql, allow_write=settings.allow_write_queries)
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
    base_name = req.filename or f"query_{int(time.time())}"
    base_name = "".join(c for c in base_name if c.isalnum() or c in ("-", "_")) or "query"
    filepath = export_dir / f"{base_name}.csv"

    jobs.cleanup_expired(settings.job_result_ttl_s)
    exports.sweep_expired()

    try:
        status, payload = await engine.run_or_defer(
            "export", req.sql, db.export_query_to_csv, req.sql, limit, str(filepath),
            timeout_s=settings.hard_timeout_s * 3,
            filepath=str(filepath),
        )
    except db.pyodbc_error_types() as exc:
        logger.warning("Error de SQL Server en /export: %s", exc)
        return {"ok": False, "error": f"Error de SQL Server: {exc}"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error inesperado en /export")
        return {"ok": False, "error": f"Error inesperado: {exc}"}

    if status == "running":
        return engine.running_payload(payload, settings.hard_timeout_s * 3, f"GET /jobs/{payload}")

    columns, row_count, truncated = payload
    return engine.build_export_payload(columns, row_count, truncated, str(filepath))


@app.get("/exports/{file_name}")
async def download_export(file_name: str):
    """Descarga un CSV exportado y lo BORRA una vez enviado (se sirve una sola vez).
    Si no se descarga, se borra solo a los MCP_EXPORT_TTL_S segundos de creado."""
    exports.sweep_expired()
    try:
        path = exports.resolve_export(file_name)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type="text/csv",
        filename=path.name,
        background=BackgroundTask(exports.delete_quietly, path),
    )


@app.get("/jobs/{job_id}")
async def get_job_result(job_id: str):
    """Equivalente REST de la tool MCP get_query_result."""
    jobs.cleanup_expired(settings.job_result_ttl_s)
    try:
        payload = engine.job_result_payload(job_id)
    except db.pyodbc_error_types() as exc:
        return {"ok": False, "status": "failed", "error": f"Error de SQL Server: {exc}"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error inesperado recuperando job %s", job_id)
        return {"ok": False, "status": "failed", "error": f"Error inesperado: {exc}"}

    if payload is None:
        return {"ok": False, "error": f"No se encontró el job '{job_id}' (puede no existir o haber expirado)."}
    return payload


@app.get("/jobs")
async def get_jobs():
    """Equivalente REST de la tool MCP list_jobs."""
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
