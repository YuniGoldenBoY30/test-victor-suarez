# Pruebas de seguridad — test.zenixtech.ai (2026-11-15)

Pentest **no destructivo** (caja negra + revisión de código) de la API y la web desplegadas en
`https://test.zenixtech.ai`. Autorizado por el responsable del proyecto. No se intentó DoS,
borrado de datos ni agotar deliberadamente la clave de NVIDIA.

Topología observada: Cloudflare → Apache 2.4 (proxy) → nginx (SPA + proxy `/api/`) → FastAPI → DuckDB.

## Resumen

| # | Hallazgo | Severidad | Estado |
|---|---|---|---|
| H1 | El despliegue en test parece **anterior al endurecimiento de seguridad** (hipótesis que unifica H2–H4 y H6) | Media-Alta | A verificar |
| H2 | `/api/docs`, `/api/redoc`, `/api/openapi.json` **públicos** (esquema de la API expuesto) | Media | Confirmado |
| H3 | **Faltan cabeceras de seguridad** en las respuestas `/api/` (sin X-Frame-Options, CSP, Permissions-Policy, Cache-Control) | Media | Confirmado |
| H4 | **Sin HSTS** (`Strict-Transport-Security`) en ningún nivel | Media | Confirmado |
| H5 | **Sin límite de tasa** (rate limiting): 25 peticiones → 0 respuestas `429`. `/consulta` sin límite = abuso de la clave NVIDIA | Media | Confirmado |
| H6 | Las guardas 413/415 de `/consulta` no están activas (devuelven `422` en vez de `413`/`415`) | Baja | Confirmado |
| H7 | La SPA (`index.html`) se sirve sin `Content-Security-Policy` | Baja | Confirmado |

**Lo que resistió bien** (ver sección final): inyección SQL/prompt, CORS, TrustedHost, validación de
entrada, métodos HTTP, endpoints parametrizados, no fuga de la clave NVIDIA y ausencia de sinks XSS en
el frontend.

---

## Hallazgos

### H1 — El despliegue en test parece anterior al endurecimiento de seguridad · Media-Alta

Tres observaciones independientes apuntan a lo mismo: el contenedor del backend en el VPS **no incluye**
`app/seguridad.py` (middlewares de cabeceras y guarda de cuerpo) ni el valor por defecto `API_DOCS=false`,
que **sí** están en el repositorio (rama `feat/implementacion`, PR #4 ya mergeado):

- H2: `/docs` y `/openapi.json` están activos, cuando el código por defecto los apaga (`api_docs=False`).
- H3: no llegan las cabeceras que fija `MiddlewareSeguridad`.
- H6: la guarda `GuardaCuerpoJSON` (413/415) no se aplica.

Un único hecho —**la imagen desplegada es de un commit anterior a la seguridad**— explica los tres.
No es seguro al 100 % en caja negra; también podría ser una configuración de `.env` distinta en el VPS.

**Recomendación:** verificar en el VPS el commit/imagen en ejecución
(`docker compose images`, `git -C /opt/project-ai-role rev-parse HEAD`) y **reconstruir y redeplegar**
desde la rama actual (`docker compose up -d --build`). Si tras redeplegar persisten H2/H3/H6, el problema
es de configuración y no de versión.

### H2 — Documentación de la API expuesta · Media

```
GET /api/docs         -> 200 (Swagger UI)
GET /api/redoc        -> 200 (ReDoc)
GET /api/openapi.json -> 200 (esquema OpenAPI real)
```

El esquema completo (rutas, modelos, validaciones) queda público. No es un fallo crítico por sí mismo,
pero facilita el reconocimiento a un atacante y no debería estar en un entorno accesible desde Internet.

**Recomendación:** `API_DOCS=false` (valor por defecto del código) en el `.env` del VPS, o redeploy (H1).

### H3 — Faltan cabeceras de seguridad en `/api/` · Media

Respuesta observada de `/api/health` (y del resto de `/api/`):

```
X-Content-Type-Options: nosniff          <- la pone Apache
Referrer-Policy: strict-origin-when-cross-origin  <- la pone Apache (sobrescribe la de la app)
```

No aparecen las que define `MiddlewareSeguridad`: `X-Frame-Options: DENY`,
`Content-Security-Policy`, `Permissions-Policy`, `Cache-Control: no-store`.

**Recomendación:** redeploy (H1). Como refuerzo independiente del backend, añadir en el vhost de Apache
`Header always set X-Frame-Options "DENY"` y una `Content-Security-Policy` para la SPA.

### H4 — Sin HSTS · Media

Ni Cloudflare, ni Apache, ni la app envían `Strict-Transport-Security`. El sitio redirige HTTP→HTTPS
(`301`), pero sin HSTS la primera visita es vulnerable a *SSL-strip* / degradación.

**Recomendación:** activar HSTS en Cloudflare (SSL/TLS → Edge Certificates → HSTS) o en Apache:
`Header always set Strict-Transport-Security "max-age=31536000; includeSubDomains"`. Empezar con un
`max-age` bajo y subirlo.

### H5 — Sin límite de tasa · Media

25 peticiones seguidas a `/api/top-clientes` → **25 × `200`, 0 × `429`**. No hay rate limiting en la app
ni en Cloudflare. `POST /api/consulta` comparte esa falta de protección y **cada llamada consume la clave
de NVIDIA**: un atacante puede generar coste (o agotar cuota) a voluntad. Ya está anotado como punto
abierto en `docs/DESPLIEGUE.md` §7 y `docs/revision-arquitectura.md` §6; sigue vigente en el despliegue.

**Recomendación:** límite de tasa por IP, sobre todo en `/consulta` (p. ej. Cloudflare Rate Limiting, o
`slowapi`/middleware en FastAPI). Valorar un límite global diario de llamadas al LLM.

### H6 — Guardas 413/415 de `/consulta` inactivas · Baja

```
POST /api/consulta  Content-Type: text/plain      -> 422 (se esperaba 415)
POST /api/consulta  cuerpo > 8192 bytes            -> 422 (se esperaba 413)
```

La petición **se rechaza igualmente** (Pydantic: `max_length=500`, tipo inválido), así que el impacto es
bajo; es una desviación respecto al comportamiento documentado. Coherente con H1 (falta `GuardaCuerpoJSON`).

### H7 — SPA sin CSP · Baja

`index.html` (servido por nginx) no lleva `Content-Security-Policy`. El frontend React escapa el contenido
y no usa sinks peligrosos (ver abajo), por lo que el riesgo es bajo, pero una CSP sería defensa en profundidad.

**Recomendación:** añadir una CSP restrictiva a la SPA en `frontend/nginx.conf` o en el vhost de Apache.

---

## Lo que resistió bien

- **Inyección SQL / prompt injection (`/consulta`):** se probaron `DROP TABLE`, sentencias apiladas,
  `read_csv('/etc/passwd')`, `duckdb_settings()`, `sqlite_master`, `UNION` a `information_schema`,
  `getenv('API_IA_NVIDIA')` y overrides de instrucciones. En todos los casos el LLM generó un `SELECT`
  inocuo y la respuesta fue `200` con datos legítimos. Además, la defensa real es en capas: validador AST
  con sqlglot (lista blanca de relaciones y funciones, lista negra de DML/DDL, regeneración del SQL desde
  el AST) + conexión DuckDB **solo lectura** con `enable_external_access=False`. Revisión de
  `app/validador_sql.py` y `app/db.py`: robusta.
- **No fuga de la clave NVIDIA:** el intento de `getenv` devolvió `SELECT 1`; los errores del LLM están
  saneados (solo el nombre del tipo de excepción, nunca el mensaje ni la clave — `app/llm.py`).
- **CORS:** preflight con `Origin: https://evil.example` → `400` **sin** `access-control-allow-origin`
  (no se refleja el origen). `allow_credentials=False`. Lista blanca en `core/config.py`.
- **TrustedHost:** `Host: evil.com` → `403`.
- **Validación de entrada:** pregunta vacía → `422`; > 500 caracteres → `422`.
- **Métodos HTTP:** `PUT`/`DELETE` → `405`.
- **Endpoints parametrizados:** `?pais=España' OR '1'='1` y `?pais='; DROP TABLE pedidos;--` → `[]`
  (consulta parametrizada, sin interpolación).
- **Frontend sin XSS:** el SQL se pinta como `<code>{sql}</code>` (React lo escapa); no hay
  `dangerouslySetInnerHTML`/`innerHTML`/`eval`, y existe un test de guardia estática
  (`frontend/src/seguridad.test.ts`) que falla si se introducen.
- **Transporte:** HTTP → HTTPS `301`.

## Prioridad sugerida

1. **H1** — verificar y redeplegar la versión con seguridad (resuelve H2, H3 y H6 de una vez).
2. **H5** — rate limiting en `/consulta` (protege la clave y el coste).
3. **H4** — activar HSTS.
4. **H7** — CSP en la SPA.

---

*Pruebas realizadas el 2026-11-15 contra `https://test.zenixtech.ai`. Documento no versionado; decide
si lo incorporas al repositorio mediante tu flujo habitual de PR.*
