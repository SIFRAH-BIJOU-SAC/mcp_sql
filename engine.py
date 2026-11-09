"""
engine.py
Lógica de ejecución compartida entre server.py (MCP) y api.py (REST), para que
ambas interfaces se comporten igual ante consultas lentas: en vez de duplicar
el patrón de timeout/job en los dos archivos (y arriesgarse a que diverjan),
viven aquí una sola vez.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import db
import jobs


async def call_with_timeout(fn, *args, timeout_s: float):
    """Para operaciones que SIEMPRE deben ser rápidas (list_tables, describe_table,
    /health). Si no terminan a tiempo, simplemente fallan — no ameritan un job."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout=timeout_s)
    except asyncio.TimeoutError as exc:
        raise TimeoutError(
            f"La operación excedió {timeout_s}s y fue abortada del lado del servidor."
        ) from exc


async def run_or_defer(kind: str, sql: str, fn, *args, timeout_s: float, **meta) -> tuple[str, Any]:
    """
    Corre `fn(*args)` en un hilo. Si termina a tiempo: ("done", resultado).
    Si no, la deja corriendo en segundo plano (asyncio.shield conserva el
    trabajo ya hecho, no lo cancela) y la registra como job: ("running", job_id).
    Ver README, sección "¿Y si la consulta dura minutos?".
    """
    task = asyncio.create_task(asyncio.to_thread(fn, *args))
    try:
        result = await asyncio.wait_for(asyncio.shield(task), timeout=timeout_s)
        return "done", result
    except asyncio.TimeoutError:
        job = jobs.create_job(kind, sql, task, **meta)
        return "running", job.id


def rows_to_markdown(columns: list[str], rows: list[dict]) -> str:
    if not rows:
        return "_(0 filas)_"
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join("" if row.get(c) is None else str(row.get(c)) for c in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, sep, *body])


def build_preview_payload(result: db.QueryResult, limit: int, output_format: str) -> dict:
    payload: dict = {
        "ok": True,
        "status": "done",
        "row_count": result.row_count,
        "truncated": result.truncated,
        "elapsed_ms": result.elapsed_ms,
        "columns": result.columns,
    }
    if output_format == "markdown":
        payload["data_markdown"] = rows_to_markdown(result.columns, result.rows)
    else:
        payload["rows"] = result.rows
    if result.truncated:
        payload["note"] = (
            f"Resultado truncado a {limit} filas. Usa export_query_csv/POST /export "
            "para obtener el conjunto completo, o añade filtros/TOP en el SQL."
        )
    return payload


def build_export_payload(columns: list[str], row_count: int, truncated: bool, filepath: str) -> dict:
    from config import settings

    path = Path(filepath).resolve()
    return {
        "ok": True,
        "status": "done",
        "file_path": str(path),
        "file_name": path.name,
        "columns": columns,
        "row_count": row_count,
        "truncated": truncated,
        "expires_in_s": settings.export_ttl_s,
        "note": (
            f"El archivo es temporal: se borra al servirse con fetch_export_csv("
            f"'{path.name}') o a los {settings.export_ttl_s}s de creado, lo que "
            "ocurra primero."
        ),
    }


def running_payload(job_id: str, timeout_s: float, poll_hint: str) -> dict:
    return {
        "ok": True,
        "status": "running",
        "job_id": job_id,
        "note": (
            f"La consulta no terminó en {timeout_s:.0f}s y sigue corriendo en segundo "
            f"plano (no se perdió ni se canceló). Usa {poll_hint} para recoger el "
            "resultado cuando esté listo; puedes consultarlo varias veces mientras "
            "el estado sea 'running'."
        ),
    }


def job_result_payload(job_id: str) -> dict | None:
    """
    Resuelve el estado/resultado de un job ya creado. Devuelve None si el job
    no existe (el llamador decide cómo reportarlo, MCP y REST difieren un poco
    en el formato del error).
    """
    job = jobs.get_job(job_id)
    if job is None:
        return None
    if not job.task.done():
        import time
        return {
            "ok": True,
            "status": "running",
            "job_id": job_id,
            "elapsed_s": round(time.monotonic() - job.created_at, 1),
            "sql_preview": job.sql_preview,
        }

    try:
        result = job.task.result()
    except Exception as exc:  # noqa: BLE001 - se reempaqueta arriba con el tipo real
        jobs.remove_job(job_id)
        raise exc

    jobs.remove_job(job_id)
    if job.kind == "preview":
        return build_preview_payload(result, job.meta["limit"], job.meta["output_format"])
    columns, row_count, truncated = result
    return build_export_payload(columns, row_count, truncated, job.meta["filepath"])
