# sifrah-sql-dwh · Servidor MCP de solo lectura para SIFRAH_DWH

Servidor MCP (FastMCP) que expone consultas SQL de **solo lectura** contra el
Data Warehouse `SIFRAH_DWH` (SQL Server), para conectarlo a Claude (Desktop o
Code) o a cualquier otro agente compatible con MCP.

---

## ✦ 1. Arquitectura y archivos

| Archivo | Responsabilidad |
|---|---|
| `config.py` | Carga y valida `.env` (credenciales, timeouts, límites). |
| `sql_guard.py` | Bloquea cualquier sentencia que no sea `SELECT`/`WITH` (defensa en profundidad). |
| `db.py` | Conexión a SQL Server, ejecución de consultas y exportación a CSV. |
| `jobs.py` | Registro en memoria de consultas que quedaron corriendo en segundo plano (ver §7). |
| `engine.py` | Lógica de timeout/job/payloads **compartida** entre `server.py` y `api.py`. |
| `server.py` | **Servidor MCP** (FastMCP): tools, recurso de esquema, healthcheck. |
| `api.py` | Wrapper **opcional** en FastAPI (REST) sobre el mismo motor — ver §10. |
| `schema/glosario_tablas_sifrah.md` | Tu glosario de tablas, servido como *recurso MCP* para que el agente lo lea antes de escribir queries. |

```
Agente (Claude, etc.) ──MCP (stdio/http)──▶ server.py ──▶ db.py ──▶ SQL Server
                                              │
                                              └─▶ sql_guard.py (solo SELECT)
```

---

## ✦ 2. Prerrequisitos

- **Python 3.10+**
- **Driver ODBC de SQL Server** instalado en el sistema operativo (esto es
  aparte de `pip install pyodbc`; pyodbc es solo el cliente, necesita el
  driver nativo de Microsoft):
  - Linux (Debian/Ubuntu): sigue la guía oficial de Microsoft para instalar
    `msodbcsql18` (repositorio `packages.microsoft.com`, no está en PyPI).
  - Windows/Mac: instala "ODBC Driver 18 for SQL Server" desde el sitio de
    Microsoft.
  - Verifica el nombre exacto instalado con `odbcinst -q -d` — debe coincidir
    con `DB_DRIVER` en tu `.env`.
- Un **login de SQL Server dedicado, de solo lectura** (ver §6, Seguridad).

---

## ✦ 3. Instalación

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

##.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

cp .env.example .env
# Edita .env con tu servidor, usuario y contraseña de solo lectura.
```

---

## ✦ 4. Ejecutar

**Modo local (Claude Desktop / Claude Code, un usuario):**

```bash
python server.py
```

Usa `MCP_TRANSPORT=stdio` (valor por defecto en `.env.example`).

**Modo servidor HTTP (varios agentes/usuarios conectándose remotamente):**

```bash
MCP_TRANSPORT=http python server.py
# o cambia MCP_TRANSPORT=http en el .env
```

Esto además expone `GET /health` para monitoreo (ver §8).

---

## ✦ 5. Herramientas (tools) expuestas

| Tool | Qué hace |
|---|---|
| `run_query(sql, max_rows, output_format)` | Ejecuta un `SELECT`/`WITH` y devuelve una vista previa en línea (JSON o Markdown). Si tarda demasiado, ver "Consultas largas" abajo. |
| `export_query_csv(sql, filename, max_rows)` | Ejecuta un `SELECT`/`WITH` grande y lo guarda como `.csv` en el servidor; devuelve la ruta. También puede pasar a segundo plano si tarda. |
| `get_query_result(job_id)` | Recoge el resultado de una consulta que quedó corriendo en segundo plano. |
| `list_jobs()` | Lista las consultas en curso o recién terminadas (por si perdiste el `job_id`). |
| `list_tables(schema)` | Lista tablas/vistas del esquema (`INFORMATION_SCHEMA.TABLES`). |
| `describe_table(table_name)` | Columnas reales de una tabla (`INFORMATION_SCHEMA.COLUMNS`) — para confirmar los tipos que tu glosario marca como "inferidos". |

Además, el **recurso** `schema://sifrah_dwh/glosario` sirve el contenido de
`schema/glosario_tablas_sifrah.md` tal cual, para que el agente lo lea como
contexto antes de construir una consulta (nombres de tablas, llaves,
convenciones como `[Año]`, sufijos `_V2`, `Flag_*`, etc.).

---

## ✦ 6. Seguridad: solo lectura, en dos capas

1. **`sql_guard.py`** rechaza cualquier sentencia que no empiece con
   `SELECT`/`WITH`, múltiples sentencias (`;`), y palabras clave de
   escritura/DDL (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `EXEC`,
   procedimientos `sp_`/`xp_`, etc.).
2. **La capa real de seguridad debe ser el propio SQL Server**: crea un login
   dedicado para este servidor con permisos de **solo `SELECT`** sobre las
   tablas/vistas de `SIFRAH_DWH`, por ejemplo:

   ```sql
   CREATE LOGIN mcp_readonly WITH PASSWORD = '...';
   CREATE USER mcp_readonly FOR LOGIN mcp_readonly;
   GRANT SELECT ON SCHEMA::dbo TO mcp_readonly;
   -- No otorgar INSERT/UPDATE/DELETE/EXECUTE/ALTER.
   ```

   Un filtro por texto (`sql_guard.py`) siempre puede tener puntos ciegos; un
   permiso a nivel de base de datos, no. Usa ambos.

3. `ALLOW_WRITE_QUERIES=false` por defecto en `.env`. Solo cámbialo si de
   verdad necesitas permitir escritura, y aun así se siguen bloqueando `DROP`,
   `TRUNCATE`, `ALTER`, `BACKUP`, `RESTORE`, `SHUTDOWN`.
4. `.env` nunca se sube a git (`.gitignore` ya lo excluye). No pongas
   credenciales directamente en el código.

---

## ✦ 7. ¿Y si la consulta dura minutos?

Hay dos límites de tiempo distintos, y es importante no confundirlos:

| Variable | Qué limita | Súbela si... |
|---|---|---|
| `DB_QUERY_TIMEOUT_S` | Cuánto puede durar la consulta **en SQL Server** (límite real). | Tus reportes pesados legítimamente tardan minutos (ej. `300` para 5 min). |
| `MCP_HARD_TIMEOUT_S` | Cuánto espera el **agente** una respuesta síncrona antes de dejar de esperar. | Casi nunca — déjalo bajo (20-30s) a propósito, ver abajo. |

**¿Por qué no simplemente subir `MCP_HARD_TIMEOUT_S` a 5 minutos?** Porque para
el usuario que está chateando con el agente, un tool call que tarda 5 minutos
en responder es indistinguible de que el agente esté colgado — es exactamente
lo que este proyecto está diseñado para evitar.

**La solución implementada: la consulta pasa a "segundo plano" sola.**

Si `run_query` o `export_query_csv` no terminan dentro de `MCP_HARD_TIMEOUT_S`
(o `3×MCP_HARD_TIMEOUT_S` para exportar), **la consulta NO se cancela ni se
pierde** — sigue corriendo del lado del servidor (acotada por
`DB_QUERY_TIMEOUT_S`), y la tool devuelve de inmediato:

```json
{"ok": true, "status": "running", "job_id": "fdf3b89f9e79", "note": "..."}
```

El agente recupera el control al instante, puede seguir la conversación, y
más tarde llama a `get_query_result(job_id=...)` para recoger el resultado
real — cuantas veces haga falta mientras el estado siga siendo `"running"`.
Esto se probó de punta a punta con una consulta simulada de 8s y
`MCP_HARD_TIMEOUT_S=3`: el agente recibió el `job_id` a los 3s, y el resultado
completo (correcto) al recogerlo después.

**Mecanismo técnico** (`server.py`, función `_run_or_defer`): se lanza la
consulta con `asyncio.create_task(asyncio.to_thread(...))` y se espera con
`asyncio.wait_for(asyncio.shield(task), timeout=...)`. El `shield` es la
pieza clave: hace que, al vencer el timeout, se abandone la ESPERA pero NO se
cancele la tarea — el hilo sigue vivo y se guarda en un registro en memoria
(`jobs.py`) para poder recuperarlo después. Se comprobó empíricamente (no se
asumió) que esto funciona incluso a través del protocolo MCP real.

**Limitaciones honestas:**
- El registro de jobs vive en memoria del proceso: si el servidor se
  reinicia, los jobs en curso o recién terminados se pierden.
- No hay cancelación real de una consulta ya en curso en SQL Server (eso
  requeriría una conexión de administrador enviando `KILL <session_id>`) —
  fuera del alcance de este proyecto, pero es una extensión posible.
- Los jobs terminados se conservan `MCP_JOB_RESULT_TTL_S` segundos (30 min por
  defecto) y luego se purgan para no crecer la memoria indefinidamente.
- `list_tables`/`describe_table` NO usan este mecanismo (siempre deberían ser
  rápidas; si no terminan a tiempo simplemente fallan).

También sigue habiendo un límite de **consultas concurrentes**
(`MCP_MAX_CONCURRENT_QUERIES`) para no saturar SQL Server, y **todas** las
excepciones dentro de cada tool se capturan y se devuelven como
`{"ok": false, "error": "..."}` — nunca se deja que una excepción tumbe el
proceso del servidor.

Para garantizar que el *proceso* del servidor se recupere si llegara a
caerse por otra razón (memoria, un bug no previsto, etc.), corre `server.py`
bajo un supervisor de procesos con reinicio automático: `systemd`
(`Restart=always`), Docker (`restart: unless-stopped`), o `supervisord`.

---

## ✦ 8. ¿Cómo se le entregan los datos al agente? ¿JSON, Markdown o CSV?

Depende del tamaño del resultado — por eso hay dos tools distintas:

- **`run_query` con `output_format="json"` (por defecto):** para vistas
  previas de hasta unos cientos de filas (`MCP_DEFAULT_MAX_ROWS`, tope
  `MCP_ABSOLUTE_MAX_ROWS`). JSON es lo más fácil de "razonar" para un agente:
  llega como estructura (columnas + filas), no como texto que tiene que
  parsear. Es la opción recomendada por defecto.
- **`run_query` con `output_format="markdown"`:** igual de acotado, pero como
  tabla Markdown legible — útil cuando el agente va a **mostrarle** el
  resultado al usuario tal cual, en vez de solo razonar sobre él.
- **`export_query_csv`:** cuando esperas miles de filas. En vez de devolver
  todo el contenido en línea (lo que puede saturar el contexto del agente y
  disparar el consumo de tokens), la consulta se ejecuta completa (hasta
  `MCP_EXPORT_MAX_ROWS`) y se escribe como `.csv` en `MCP_EXPORT_DIR`; la
  tool solo devuelve la ruta, columnas y número de filas. El agente (o tú)
  puede abrir ese CSV con pandas, Excel, u otra herramienta.

En resumen: **CSV no es el formato de entrega por defecto hacia el agente**
— es el formato de **extracción a disco** para volúmenes grandes. Para que el
agente razone sobre los datos dentro de la conversación, JSON acotado en
filas es lo más eficiente.

---

## ✦ 9. Conectar desde Claude Desktop / Claude Code

El patrón general para un servidor MCP local por `stdio` es registrar el
comando de arranque en la configuración de MCP servers del cliente, por
ejemplo:

```json
{
  "mcpServers": {
    "sifrah-sql-dwh": {
      "command": "/ruta/a/sifrah_mcp_sql/venv/bin/python",
      "args": ["/ruta/a/sifrah_mcp_sql/server.py"],
      "env": { "MCP_TRANSPORT": "stdio" }
    }
  }
}
```

En Claude Code también puedes usar el CLI (`claude mcp add ...`). ⚠️ No tengo
acceso a navegar la documentación en vivo desde aquí, y la ubicación exacta
del archivo de configuración / el comando del CLI puede haber cambiado — te
recomiendo confirmar el paso a paso actual en
**https://docs.claude.com/en/docs/claude-code/mcp** antes de registrar el
servidor.

Para conectarlo a **otro agente** (no-Claude) compatible con MCP, corre
`MCP_TRANSPORT=http` y apunta ese agente a `http://tu-servidor:8000` (ajusta
`MCP_HOST`/`MCP_PORT`).

---

## ✦ 10. api.py — FastAPI opcional (REST de respaldo)

`server.py` ya puede correr como servidor HTTP y ya expone `GET /health`.
`api.py` es un wrapper **aparte**, opcional, útil si necesitas:

- Probar consultas con `curl`/Postman sin hablar el protocolo MCP.
- Un `/health` plano para un orquestador externo (Docker healthcheck,
  liveness/readiness probe de Kubernetes, monitor de uptime).
- Integrar este motor de consultas en algo que hable REST en vez de MCP.

```bash
uvicorn api:app --host 0.0.0.0 --port 8080
```

Endpoints: `GET /health`, `POST /query` (mismo contrato que `run_query`),
`POST /export` (mismo contrato que `export_query_csv`), `GET /jobs/{job_id}`
y `GET /jobs` (mismo contrato que `get_query_result`/`list_jobs`). Reutiliza
`db.py`, `jobs.py`, `engine.py` y `sql_guard.py` — las mismas protecciones
(solo lectura, timeouts, límites de filas, y el patrón de "consulta larga →
job en segundo plano" de la sección anterior) aplican igual que en `server.py`.

> **Nota si escribes tests contra `api.py`:** el patrón de jobs usa
> `asyncio.create_task`, que necesita un *event loop persistente* para seguir
> avanzando en segundo plano entre peticiones — exactamente lo que hay bajo
> un `uvicorn` real corriendo como proceso. El `TestClient` de FastAPI/Starlette
> puede reciclar el event loop entre llamadas sueltas y hacer que un job
> "se quede congelado" en las pruebas aunque en producción funcione bien;
> esto se verificó corriendo `uvicorn` real. Si necesitas testear esto,
> hazlo con un servidor real (como en el ejemplo de arriba) en vez de
> `TestClient` para llamadas separadas en el tiempo.

---

## ✦ 11. Próximos pasos sugeridos

- Ejecutar el `SELECT` de `INFORMATION_SCHEMA.COLUMNS` del §11 de tu
  glosario y reemplazar los tipos "inferidos" por los reales (puedes pedirle
  esto al propio agente usando la tool `describe_table`).
- Documentar `DIM_TIENDA`, `DIM_EMPRESA`, `DIM_EMPLEADO` (pendientes según tu
  glosario, §9) y añadirlas a `schema/glosario_tablas_sifrah.md` — el recurso
  MCP se actualiza automáticamente porque lee el archivo en cada llamada.
- Si despliegas esto en GCP (Cloud Run, GKE, una VM), usa Secret Manager para
  `DB_USER`/`DB_PASSWORD` en vez de un `.env` plano, e inyecta esos valores
  como variables de entorno en el contenedor.

 