"""
sql_guard.py
Valida que las consultas SQL entrantes sean de solo lectura (SELECT / CTE con WITH)
antes de ejecutarlas.

IMPORTANTE: esto es una barrera de defensa EN PROFUNDIDAD, no la barrera principal.
La barrera principal debe ser un login de SQL Server con permisos de SOLO LECTURA
(GRANT SELECT) sobre las tablas/vistas de SIFRAH_DWH — ver README.md, sección
"Seguridad". Un filtro por texto siempre puede tener puntos ciegos; un permiso a
nivel de base de datos no.
"""
from __future__ import annotations

import re

# Palabras clave que implican escritura/DDL/control, bloqueadas en modo solo-lectura.
_WRITE_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "MERGE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "GRANT", "REVOKE", "DENY", "EXEC", "EXECUTE",
    "BACKUP", "RESTORE", "SHUTDOWN",
)

# Bloqueadas incluso si ALLOW_WRITE_QUERIES=true (demasiado destructivas para un
# agente automatizado).
_ALWAYS_BLOCKED_KEYWORDS = ("DROP", "TRUNCATE", "ALTER", "SHUTDOWN", "BACKUP", "RESTORE")

_COMMENT_RE = re.compile(r"--.*?$|/\*.*?\*/", re.MULTILINE | re.DOTALL)
_PROC_PREFIX_RE = re.compile(r"(?<![A-Z0-9_])(sp_|xp_)[A-Z0-9_]+", re.IGNORECASE)


class UnsafeQueryError(ValueError):
    """La consulta fue rechazada por sql_guard antes de tocar la base de datos."""


def _strip_comments(sql: str) -> str:
    return _COMMENT_RE.sub(" ", sql)


def _contains_keyword(text_upper: str, keyword: str) -> bool:
    pattern = r"(?<![A-Z0-9_])" + re.escape(keyword) + r"(?![A-Z0-9_])"
    return re.search(pattern, text_upper) is not None


def ensure_read_only(sql: str, allow_write: bool = False) -> None:
    """Lanza UnsafeQueryError si la consulta no cumple la política de solo lectura."""
    if not sql or not sql.strip():
        raise UnsafeQueryError("La consulta está vacía.")

    cleaned = _strip_comments(sql).strip()
    if not cleaned:
        raise UnsafeQueryError("La consulta solo contiene comentarios.")

    # Tolerar un único ';' final, pero no múltiples sentencias encadenadas.
    body = cleaned[:-1] if cleaned.endswith(";") else cleaned
    if ";" in body:
        raise UnsafeQueryError(
            "Solo se permite UNA sentencia SQL por llamada (se detectó ';' adicional)."
        )

    if _PROC_PREFIX_RE.search(body):
        raise UnsafeQueryError("No se permite invocar procedimientos (sp_/xp_).")

    first_token = body.strip().split(None, 1)[0].upper() if body.strip() else ""
    upper_body = body.upper()

    if allow_write:
        blocked = _ALWAYS_BLOCKED_KEYWORDS
    else:
        if first_token not in ("SELECT", "WITH"):
            raise UnsafeQueryError(
                f"Solo se permiten consultas SELECT (o CTE con WITH). Se recibió: '{first_token}'."
            )
        blocked = _WRITE_KEYWORDS

    for kw in blocked:
        if _contains_keyword(upper_body, kw):
            raise UnsafeQueryError(f"La consulta contiene una palabra clave no permitida: '{kw}'.")
