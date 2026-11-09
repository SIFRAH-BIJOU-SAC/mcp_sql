"""
jobs.py
Registro en memoria de consultas que no terminaron dentro de MCP_HARD_TIMEOUT_S
y quedaron corriendo en segundo plano. Permite que el agente "vuelva más
tarde" con get_query_result(job_id) en vez de quedarse esperando una
respuesta síncrona que podría tardar minutos.

Por qué esto y no solo subir el timeout: si el agente espera minutos por una
respuesta síncrona, para el usuario es indistinguible de que el agente esté
colgado. Con este patrón, la consulta pesada sigue corriendo del lado del
servidor (acotada por DB_QUERY_TIMEOUT_S), pero el agente recupera el control
de inmediato y puede seguir la conversación mientras tanto.

Limitación honesta: este registro vive en memoria del proceso. Si el servidor
se reinicia, los jobs en curso (terminados o no) se pierden. No hay
persistencia entre reinicios ni entre múltiples réplicas del servidor.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

JobKind = Literal["preview", "export"]

_jobs: dict[str, "Job"] = {}


@dataclass
class Job:
    id: str
    kind: JobKind
    sql_preview: str
    task: asyncio.Task
    created_at: float = field(default_factory=time.monotonic)
    meta: dict[str, Any] = field(default_factory=dict)


def _truncate_sql(sql: str, length: int = 200) -> str:
    sql = " ".join(sql.split())
    return sql if len(sql) <= length else sql[: length - 1] + "…"


def create_job(kind: JobKind, sql: str, task: asyncio.Task, **meta: Any) -> Job:
    job = Job(id=uuid.uuid4().hex[:12], kind=kind, sql_preview=_truncate_sql(sql), task=task, meta=meta)
    _jobs[job.id] = job
    return job


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def remove_job(job_id: str) -> None:
    _jobs.pop(job_id, None)


def list_jobs() -> list[Job]:
    return list(_jobs.values())


def cleanup_expired(ttl_s: float) -> None:
    """Purga jobs YA TERMINADOS cuya antigüedad supera ttl_s. Los que siguen
    corriendo nunca se purgan por antigüedad (solo al ser recogidos)."""
    now = time.monotonic()
    expired = [jid for jid, j in _jobs.items() if j.task.done() and (now - j.created_at) > ttl_s]
    for jid in expired:
        _jobs.pop(jid, None)
