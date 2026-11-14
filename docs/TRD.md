# TRD: Documento de requisitos técnicos

Complementa a `docs/PRD.md`. Todo lo definido aquí es el contrato que sigue el código; cualquier desviación se indica en el informe del paso y en el README.

## 1. Alcance técnico

Aplicación de tres piezas: un ETL que limpia un CSV sucio y lo carga en DuckDB, una API FastAPI que traduce preguntas en español a SQL de solo lectura con un LLM de NVIDIA, y un dashboard React. Todo se empaqueta con Docker Compose.

Entorno: Python 3.14 (venv en `.venv`), Node 24 / npm 11, Docker 29 con compose v5. Rutas con `pathlib`; sin scripts solo de shell en la parte Python.

## 2. Principios de diseño (SOLID y DRY)

- Responsabilidad única por módulo (ver sección 3).
- El proveedor LLM está detrás del `Protocol` `ClienteLLM`, inyectado con `Depends` de FastAPI y sustituible en tests.
- El validador SQL es independiente del LLM y de la base de datos (no importa `duckdb` ni el cliente LLM).
- Configuración central en un único módulo (`core/config.py`, pydantic-settings).
- Constantes compartidas definidas una sola vez en `core/esquema.py`; el resto las importa.
- Frontend: acceso a la API aislado en `src/api/`, DTO tipados espejo de los modelos del backend, componentes presentacionales separados de contenedores.

## 3. Módulos y responsabilidades

### 3.1 Backend

| Módulo | Responsabilidad |
|---|---|
| `core/__init__.py` | Paquete. |
| `core/config.py` | `Settings` (pydantic-settings) y `get_settings()` con caché. Única fuente de configuración. |
| `core/esquema.py` | Constantes únicas: `COLUMNAS_CSV`, `PAISES` (canónicos y mapa de variantes), `ESTADOS`, `ESTADO_EXCLUIDO_VENTAS`, `FECHA_MIN`, `FECHA_MAX`, `FORMATOS_FECHA`, `RELACIONES_PERMITIDAS`, `LIMITE_FILAS_DEFECTO`, `DESCRIPCION_ESQUEMA`, `RUTA_CSV_RAW`, `RUTA_VISTAS`. |
| `scripts/generar_pedidos.py` | Genera `data/pedidos_raw.csv` con semilla fija e imprime los recuentos de cada error deliberado. |
| `etl/__init__.py` | Paquete. |
| `etl/limpieza.py` | `limpiar_filas(filas) -> (filas_limpias, informe)`. Función pura, sin E/S ni DuckDB. |
| `etl/carga.py` | `cargar_duckdb(filas, db_path, ruta_vistas=RUTA_VISTAS)`: reemplaza `pedidos` y ejecuta las vistas. |
| `etl/__main__.py` | CLI `python -m etl [--csv] [--db] [--si-falta]`. |
| `sql/vistas.sql` | Definición de las 2 vistas. |
| `app/__init__.py` | Paquete. |
| `app/validador_sql.py` | `validar_sql(...)` y `SQLNoPermitidoError`. Solo sqlglot. |
| `app/llm.py` | `ClienteLLM` (Protocol), `ClienteNvidia`, `LLMError`, `LLMNoConfiguradoError`. |
| `app/prompt.py` | `construir_mensajes(pregunta)`. |
| `app/db.py` | `abrir_conexion_lectura(path)`. |
| `app/errores.py` | `BaseDatosNoDisponibleError`, `ErrorEjecucionSQL`. |
| `app/servicio.py` | `ServicioConsultas` y `ResultadoConsulta`. Sin FastAPI. |
| `app/repositorio_vistas.py` | `RepositorioVistas`: SQL fijo y parametrizado de las vistas. Sin FastAPI. |
| `app/modelos.py` | Modelos pydantic de petición y respuesta. |
| `app/dependencias.py` | `get_settings`, `get_cliente_llm`, `get_servicio`, `get_repositorio` (sobrescribibles). |
| `app/main.py` | Aplicación FastAPI, rutas, CORS y manejadores de error. |

Otros archivos de la raíz: `requirements.txt`, `pytest.ini` (`pythonpath=.`, `testpaths=tests`), `.env.example`.

### 3.2 Tests

`tests/conftest.py` (propiedad del paso ETL: fixture `db_prueba(tmp_path)` con una base pequeña de filas conocidas, incluida una `cancelado`; los pasos posteriores la reutilizan sin editarla), `test_config.py`, `test_generador.py`, `test_limpieza.py`, `test_carga_vistas.py`, `test_validador_sql.py`, `test_servicio.py`, `test_repositorio_vistas.py`, `test_api.py`.

### 3.3 Frontend (`frontend/`, Vite + React + TypeScript)

| Elemento | Responsabilidad |
|---|---|
| `src/api/` | Cliente único tipado. URL base de `import.meta.env.VITE_API_URL` (por defecto `http://localhost:8000`). DTO espejo del contrato y tipo de error `{error, mensaje, sql?}`. |
| Componentes contenedores | Cargan datos y gestionan estado (dashboard, panel Pregunta). |
| Componentes presentacionales | Gráfico de ventas por mes y país (recharts, filtro/leyenda por país), tabla top 10 clientes, tabla dinámica de resultados, bloque de SQL, mensajes de error por código. |
| Tema | Claro/oscuro con `prefers-color-scheme` e interruptor manual. |
| `frontend/.env.example` | `VITE_API_URL`. |

Accesibilidad: etiquetas, teclado, contraste, `aria-live` en resultados y errores, tabla alternativa al gráfico, `prefers-reduced-motion`. Tests vitest (cliente de API y render de errores, con `fetch` simulado) recomendados.

### 3.4 Docker

| Archivo | Contenido |
|---|---|
| `Dockerfile` (raíz) | Backend sobre `python:3.14-slim`; instala `requirements.txt`; copia código, `data/pedidos_raw.csv` y `sql/`; usuario no root; `CMD` ejecuta `python -m etl --si-falta` y luego `uvicorn app.main:app --host 0.0.0.0 --port 8000`. |
| `.dockerignore` (raíz) | `.env`, `.env.*`, `!.env.example`, `.venv`, `frontend/node_modules`, `data/*.duckdb*`, `.git`, `.goat`, `__pycache__`. |
| `frontend/Dockerfile` | Multi-etapa: build con Node (`ARG VITE_API_URL=/api`) y servidor `nginx:alpine` con `dist`. |
| `frontend/nginx.conf` | Fallback SPA y proxy `/api/` a `http://backend:8000/` quitando el prefijo. |
| `frontend/.dockerignore` | `node_modules`, `dist`, `.env*`. |
| `docker-compose.yml` | `backend` (build `.`, `env_file: .env`, healthcheck en `/health`, volumen con nombre opcional para datos) y `frontend` (build `frontend`, puertos `8080:80`, `depends_on` backend sano). |

`.env` no se copia ni se incorpora a ninguna imagen.

### 3.5 Despliegue en el VPS (Apache)

| Archivo / elemento | Contenido |
|---|---|
| `deploy/apache/test.zenixtech.ai.conf` | vhost de Apache 2.4: el puerto 80 redirige a HTTPS; el 443 con `mod_ssl` hace `ProxyPass / http://127.0.0.1:8080/` con `ProxyPreserveHost On`, `X-Forwarded-Proto https` y `ProxyTimeout 60`. |
| `docker-compose.yml` | En el VPS el puerto del frontend debe publicarse solo en loopback: `127.0.0.1:8080:80`. |
| Módulos de Apache | `proxy`, `proxy_http`, `headers`, `ssl`, `rewrite`. |
| Credenciales | `VPS_PROD_USER`, `VPS_PROD_HOST` y `VPS_PROD_PASSWORD` solo en `.env` local; despliegue por clave SSH. |

Detalle en `docs/DESPLIEGUE.md`.

## 4. Modelo de datos

CSV `data/pedidos_raw.csv`, columnas exactas y en este orden: `fecha,cliente,pais,producto,importe,estado`.

Tabla `pedidos` (se reemplaza en cada carga):

| Columna | Tipo |
|---|---|
| `fecha` | DATE |
| `cliente` | VARCHAR |
| `pais` | VARCHAR |
| `producto` | VARCHAR |
| `importe` | DECIMAL(12,2) |
| `estado` | VARCHAR |

Estados: `completado`, `enviado`, `pendiente`, `cancelado`. Rango de fechas válido: 2024-01-01 a 2025-06-30. No existe identificador de pedido.

## 5. Vistas SQL (`sql/vistas.sql`)

Ambas con `CREATE OR REPLACE VIEW`, excluyendo `estado = 'cancelado'`.

```sql
CREATE OR REPLACE VIEW ventas_por_mes_pais AS
SELECT
    date_trunc('month', fecha)::DATE AS mes,
    pais,
    COUNT(*) AS num_pedidos,
    SUM(importe) AS total_ventas
FROM pedidos
WHERE estado <> 'cancelado'
GROUP BY 1, 2;

CREATE OR REPLACE VIEW top_10_clientes AS
SELECT
    cliente,
    COUNT(*) AS num_pedidos,
    SUM(importe) AS total_comprado
FROM pedidos
WHERE estado <> 'cancelado'
GROUP BY cliente
ORDER BY total_comprado DESC
LIMIT 10;
```

El literal `'cancelado'` corresponde a `ESTADO_EXCLUIDO_VENTAS` de `core/esquema.py`; al ser SQL puro en un archivo, se mantiene sincronizado mediante un test (`test_carga_vistas.py`).

## 6. Reglas de limpieza (`etl.limpieza`)

1. Recortar espacios y normalizar mayúsculas/minúsculas de los textos.
2. Mapear variantes de país al catálogo canónico (`PAISES`); un país no reconocible se descarta.
3. Interpretar la fecha con `FORMATOS_FECHA` (YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, YYYY/MM/DD como mínimo); fechas imposibles (2024-02-30, 31/04/2024, mes 13) o no interpretables se descartan; también las fuera de `FECHA_MIN`..`FECHA_MAX`.
4. `importe` vacío, inválido o negativo se descarta; la coma decimal se acepta. No se imputa ningún valor.
5. Estado fuera del catálogo se descarta.
6. Deduplicar tras normalizar, sobre las 6 columnas (decisión documentada: no hay identificador de pedido, por lo que dos pedidos legítimos idénticos se colapsan).
7. El informe cuenta filas leídas, conservadas, descartadas por motivo y duplicados eliminados; `python -m etl` lo imprime.

## 7. Flujo lenguaje natural a SQL

1. `POST /consulta` valida el cuerpo (`pregunta`, 1 a 500 caracteres).
2. `ServicioConsultas.consultar(pregunta)` pide el SQL a `ClienteLLM.generar_sql(pregunta)`. `ClienteNvidia` usa el SDK `openai` con `base_url`, modelo y timeout de `Settings`, con los mensajes de `construir_mensajes`.
3. El prompt incluye `DESCRIPCION_ESQUEMA`, los valores canónicos de país y estado, el rango de fechas y la regla de mes sin año: se consideran todos los años del rango.
4. El cliente elimina vallas markdown; fallo del SDK o de red, o contenido vacío, lanza `LLMError`; clave ausente lanza `LLMNoConfiguradoError`.
5. `validar_sql(sql)` devuelve el SQL aceptado con `LIMIT` añadido si faltaba, o lanza `SQLNoPermitidoError`.
6. Se abre la conexión de solo lectura (`abrir_conexion_lectura`), se ejecuta, se serializan las filas (fechas ISO, `Decimal` a `float`) y se cierra la conexión.
7. Se devuelve `ResultadoConsulta(pregunta, sql, columnas, filas)`.

## 8. Reglas de validación SQL (`validar_sql`)

Firma: `validar_sql(sql, permitidas=RELACIONES_PERMITIDAS, limite=LIMITE_FILAS_DEFECTO) -> str`. Usa el AST de sqlglot (dialecto `duckdb`), no solo expresiones regulares. Rechaza con `SQLNoPermitidoError(mensaje)`:

- SQL vacío o con error de sintaxis.
- Más de una sentencia (se tolera un `;` final).
- Raíz que no sea SELECT (se admiten UNION, INTERSECT, EXCEPT y WITH).
- Cualquier nodo DML, DDL o de comando en cualquier punto: Insert, Update, Delete, Merge, Create, Drop, Alter, Command, Pragma, Copy, Attach, Detach, Set, Use, Transaction, etc.
- Referencias a tablas que no estén en la lista blanca ni sean CTE de la misma consulta; catálogo o esquema distinto de `main`.
- Funciones de tabla o de archivo: `read_csv*`, `read_parquet`, `read_json*`, `glob`, `read_text`, `read_blob`, `query`, `query_table`, cualquier función como fuente de FROM, `duckdb_*` e `information_schema`.

Si falta, añade `LIMIT` a la consulta más externa. Relaciones permitidas: `pedidos`, `ventas_por_mes_pais`, `top_10_clientes`. El módulo no importa `duckdb` ni el cliente LLM.

## 9. Contrato de API

Sin prefijo de ruta. Errores con formato `{"error": código, "mensaje": texto en español}`.

### 9.1 `GET /health`
200: `{"status": "ok"}`.

### 9.2 `GET /ventas-por-mes-pais?pais=<opcional>`
200: `[{"mes": "YYYY-MM-DD", "pais": str, "num_pedidos": int, "total_ventas": number}]`. Con `pais`, filtra por ese país (consulta parametrizada). Lista vacía si no hay coincidencias.

### 9.3 `GET /top-clientes`
200: `[{"cliente": str, "num_pedidos": int, "total_comprado": number}]` (máximo 10, orden descendente por `total_comprado`).

### 9.4 `POST /consulta`
Cuerpo: `{"pregunta": str}` (1 a 500 caracteres).
200: `{"pregunta": str, "sql": str, "columnas": [str], "filas": [[...]]}`. Fechas en ISO, decimales como número.
Ejemplo:

```json
{
  "pregunta": "¿Cuánto vendimos en España en marzo de 2024?",
  "sql": "SELECT SUM(total_ventas) AS total FROM ventas_por_mes_pais WHERE pais = 'España' AND mes = DATE '2024-03-01' LIMIT 1000",
  "columnas": ["total"],
  "filas": [[12345.67]]
}
```

### 9.5 Tabla de errores

| Situación | HTTP | `error` |
|---|---|---|
| Clave del LLM no configurada | 503 | `llm_no_configurado` |
| Fallo del LLM (red, SDK, respuesta vacía) | 502 | `llm_error` |
| SQL rechazado por el validador (incluye campo `sql`) | 422 | `sql_no_valida` |
| Error al ejecutar el SQL | 422 | `error_ejecucion` |
| Base de datos no disponible | 503 | `base_datos_no_disponible` |
| Cuerpo inválido (validación de Pydantic) | 422 | respuesta por defecto de FastAPI |
| `POST /consulta` con `Content-Type` distinto de `application/json` | 415 | `tipo_contenido_no_soportado` |
| `POST /consulta` con cuerpo mayor de 8192 bytes (por `Content-Length` o contando bytes si es chunked) | 413 | `cuerpo_demasiado_grande` |
| Fallo no controlado | 500 | `error_interno` (mensaje genérico `Error interno del servidor.`) |
| Host no incluido en `TRUSTED_HOSTS` | 400 | respuesta de `TrustedHostMiddleware` (sin cuerpo de la API) |

Origen de cada excepción: `LLMNoConfiguradoError` y `LLMError` en `app.llm`; `SQLNoPermitidoError` en `app.validador_sql`; `BaseDatosNoDisponibleError` y `ErrorEjecucionSQL` en `app.errores`. Los mensajes no incluyen la clave ni trazas.

El 500 genérico lo produce `MiddlewareSeguridad` (`app/seguridad.py`), el middleware más externo: registra la traza solo en el log del servidor y devuelve cabeceras de seguridad también en el error. Los errores 413 y 415 los produce `GuardaCuerpoJSON` (solo para `POST /consulta`), que se ejecuta dentro de CORS para que la respuesta lleve cabeceras CORS.

CORS: `CORSMiddleware` con `settings.cors_origins`, `allow_credentials=False`, métodos `GET`, `POST`, `OPTIONS` y cabeceras `Content-Type` y `Accept`.

Cabeceras de seguridad en todas las respuestas: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, `Permissions-Policy: camera=(), microphone=(), geolocation=()` y `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`. Las rutas `/docs` y `/redoc` usan una CSP propia que permite el CDN de Swagger UI/ReDoc.

Orden de middlewares (de fuera a dentro): seguridad, hosts de confianza, CORS, guarda de `/consulta`.

## 10. Configuración

| Variable | Campo de `Settings` | Defecto | Notas |
|---|---|---|---|
| `API_IA_NVIDIA` | `api_ia_nvidia` | sin valor | `SecretStr`, opcional; nunca se registra ni se devuelve. |
| `NVIDIA_MODEL` | `nvidia_model` | `meta/llama-3.3-70b-instruct` | |
| (sin variable) | `nvidia_base_url` | `https://integrate.api.nvidia.com/v1` | |
| (sin variable) | `llm_timeout` | `30` | segundos |
| `DUCKDB_PATH` | `duckdb_path` | `data/pedidos.duckdb` | |
| `CORS_ORIGINS` | `cors_origins` | `http://localhost:5173` | lista separada por comas o JSON. Cada origen se valida: solo `http(s)://host[:puerto]`; se rechazan `*`, `null`, credenciales, ruta, consulta y fragmento. Se normaliza a minúsculas y se quita una barra final. |
| `TRUSTED_HOSTS` | `trusted_hosts` | `localhost,127.0.0.1` | lista de hosts sin puerto; admite `*.dominio` como comodín inicial, nunca `*` solo. No puede quedar vacía. Controla `TrustedHostMiddleware`. **En producción debe incluir el host público `test.zenixtech.ai`**: Apache (`ProxyPreserveHost On`) y nginx (`proxy_set_header Host $host`) reenvían ese `Host` al backend; si no está en la lista, todas las peticiones proxied devuelven **400**. |
| `API_DOCS` | `api_docs` | `false` | `true` activa `/docs`, `/redoc` y `/openapi.json`. Con `false` esas rutas no existen (404). Desactivado en producción. |

`Settings` lee `.env`. `.env.example` solo contiene marcadores: `API_IA_NVIDIA=`, `NVIDIA_MODEL=`, `DUCKDB_PATH=`, `CORS_ORIGINS=`, `TRUSTED_HOSTS=`, `API_DOCS=`.

Ejemplo de producción (valores ilustrativos, sin secretos):

```
CORS_ORIGINS=https://test.zenixtech.ai
TRUSTED_HOSTS=test.zenixtech.ai,127.0.0.1,localhost
API_DOCS=false
```

Frontend: `VITE_API_URL` solo admite una ruta (`/api`) o una URL `http(s)` sin credenciales. Si se omite: en desarrollo `http://localhost:8000` y en producción `/api` (mismo origen, proxy de nginx). Docker Compose construye la imagen con `VITE_API_URL=/api`. La URL base no lleva secretos en el código.

Frontend, cabeceras y CSP: `frontend/index.html` carga el tema con `<script src="/tema.js">` externo (sin script inline) y el cliente de API no envía credenciales. Se recomienda, para el despliegue de la página, una CSP `script-src 'self'` y `default-src 'self'`, y no usar `unsafe-inline`. La preferencia de tema se lee de `localStorage`; no se guardan tokens en `localStorage`.

## 11. Seguridad

- `.env` ignorado por git; la clave nunca se escribe en código, logs, respuestas ni imágenes.
- Defensa en profundidad para el SQL generado: validador AST, lista blanca de relaciones, conexión `read_only=True` con `enable_external_access=False`, límite de filas y tiempo máximo del LLM.
- El texto del LLM se trata como no confiable (riesgo de inyección de prompt); la validación no depende del prompt.
- Errores sin trazas ni detalles internos; el 500 es genérico (`error_interno`) y la traza solo va al log del servidor.
- Modelo de seguridad de la conexión frontend-backend (defensa en profundidad):
  - CORS restringido a `CORS_ORIGINS` validados, sin credenciales (`allow_credentials=False`).
  - Hosts de confianza con `TrustedHostMiddleware` (`TRUSTED_HOSTS`). **En producción `TRUSTED_HOSTS` debe incluir `test.zenixtech.ai`**, o todas las peticiones proxied responden 400.
  - Documentación de la API desactivada por defecto (`API_DOCS=false`).
  - Cabeceras de seguridad y CSP `default-src 'none'` en todas las respuestas de la API (ver 9.5).
  - `POST /consulta`: exige `application/json` (415) y limita el cuerpo a 8192 bytes (413).
  - Frontend: URL base sin valores fijos en código (`VITE_API_URL` validado), peticiones sin credenciales, comprobación de `Content-Type` JSON antes de parsear, tema cargado desde script externo, sin `innerHTML`/`eval`.
- Contenedor backend con usuario no root; `.dockerignore` excluye secretos.
- Fuera de alcance: autenticación (no hay JWT, login ni cookies de sesión).

## 12. Estrategia de tests

- `python -m pytest -q` desde la raíz con `.venv`; verde tras cada paso de backend; al menos 3 archivos.
- Sin red ni clave real: `Settings(_env_file=None)` o `monkeypatch`; el LLM se sustituye por un cliente falso mediante `dependency_overrides`.
- Unitarios: limpieza (CA2 a CA4), validador (CA7, CA8), config, generador.
- Integración: carga y vistas con la fixture `db_prueba`, servicio, repositorio, API (éxito, fallo LLM, SQL inválido, sin clave, base ausente, error de ejecución, endpoints del dashboard), escritura rechazada por la conexión de solo lectura.
- Frontend: `npm run build` y vitest con `fetch` simulado (cliente de API y render de errores).
- Docker: `docker compose config`, `docker compose build` y humo de extremo a extremo.
