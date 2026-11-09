"""
exports.py
Ciclo de vida de los CSV exportados: se borran automáticamente cuando
  1) se sirven (fetch_export_csv en MCP / GET /exports/{nombre} en REST), o
  2) pasan MCP_EXPORT_TTL_S segundos desde su creación (por defecto 600 = 10 min),
lo que ocurra primero.

Solo se tocan archivos *.csv directamente dentro de MCP_EXPORT_DIR: nunca
subcarpetas ni otros tipos de archivo.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from config import settings

logger = logging.getLogger("sifrah_mcp.exports")

_sweeper_started = False
_sweeper_lock = threading.Lock()


def export_dir() -> Path:
    return Path(settings.export_dir)


def sweep_expired(ttl_s: int | None = None) -> int:
    """Borra los CSV con más de ttl_s segundos de antigüedad. Devuelve cuántos borró.
    Nunca lanza excepciones: un fallo de limpieza no debe romper una consulta."""
    ttl = settings.export_ttl_s if ttl_s is None else ttl_s
    folder = export_dir()
    if not folder.is_dir():
        return 0
    now = time.time()
    removed = 0
    for f in folder.glob("*.csv"):
        try:
            if f.is_file() and now - f.stat().st_mtime > ttl:
                f.unlink()
                removed += 1
        except OSError as exc:  # archivo abierto en Excel, etc.: se reintenta en la próxima pasada
            logger.warning("No se pudo borrar export expirado %s: %s", f, exc)
    if removed:
        logger.info("Limpieza de exports: %d archivo(s) expirado(s) borrado(s)", removed)
    return removed


def start_sweeper(interval_s: int = 60) -> None:
    """Hilo daemon que barre los exports expirados cada interval_s segundos.
    Idempotente: llamarlo varias veces solo arranca un hilo."""
    global _sweeper_started
    with _sweeper_lock:
        if _sweeper_started:
            return
        _sweeper_started = True

    def _loop() -> None:
        while True:
            sweep_expired()
            time.sleep(interval_s)

    threading.Thread(target=_loop, name="export-sweeper", daemon=True).start()


def resolve_export(name: str) -> Path:
    """Valida que `name` sea un CSV directamente dentro de la carpeta de exports
    (sin rutas, sin '..') y devuelve su ruta. Lanza FileNotFoundError/ValueError."""
    base = Path(name).name  # descarta cualquier ruta que venga incluida
    if not base.lower().endswith(".csv"):
        base += ".csv"
    path = (export_dir() / base).resolve()
    if path.parent != export_dir().resolve():
        raise ValueError("Nombre de archivo inválido.")
    if not path.is_file():
        raise FileNotFoundError(
            f"No existe '{base}' en {export_dir()}. Puede que ya se haya servido "
            f"o que haya expirado (MCP_EXPORT_TTL_S={settings.export_ttl_s}s)."
        )
    return path


def delete_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("No se pudo borrar export servido %s: %s (lo borrará el TTL)", path, exc)


def read_and_delete(name: str, max_bytes: int) -> dict:
    """Lee el CSV completo y lo borra. Si supera max_bytes NO lo lee ni lo borra
    (para no inundar el contexto del agente) y devuelve un error explicativo."""
    path = resolve_export(name)
    size = path.stat().st_size
    if size > max_bytes:
        return {
            "ok": False,
            "read_from_disk": True,
            "error": (
                f"El archivo pesa {size:,} bytes y supera MCP_EXPORT_FETCH_MAX_BYTES="
                f"{max_bytes:,}: no cabe en la conversación, así que no se sirvió ni se "
                "borró. Léelo DIRECTAMENTE DESDE DISCO en file_path (p. ej. pandas "
                "read_csv con encoding='utf-8-sig', o por partes/chunks). Se borrará "
                f"solo a los {settings.export_ttl_s}s de creado."
            ),
            "file_path": str(path),
            "size_bytes": size,
        }
    content = path.read_text(encoding="utf-8-sig")
    delete_quietly(path)
    return {
        "ok": True,
        "file_name": path.name,
        "size_bytes": size,
        "deleted": not path.exists(),
        "csv": content,
    }
