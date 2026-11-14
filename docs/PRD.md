# PRD: Panel de pedidos con consultas en lenguaje natural

## 1. Objetivo

Permitir que una persona de negocio explore los pedidos sin escribir SQL: ve un dashboard con indicadores clave y hace preguntas en español que se traducen a SQL de solo lectura sobre la tabla `pedidos` y dos vistas aprobadas.

## 2. Usuarios y personas

**Laura, analista de negocio.** No sabe SQL. Quiere ver ventas por mes y país y preguntar "¿Cuánto vendimos en España en marzo de 2024?". Necesita ver el SQL ejecutado para confiar en el resultado.

**Marcos, responsable de datos.** Mantiene el CSV y las reglas de limpieza. Quiere repetir la carga de forma idempotente y saber cuántas filas se descartaron y por qué.

**Sara, responsable de seguridad.** Necesita garantía de que ninguna pregunta modifica datos ni lee fuera de las relaciones permitidas, y que la clave del LLM no se expone.

## 3. Requisitos funcionales

### RF1. CSV sucio
- RF1.1 `scripts/generar_pedidos.py` (semilla fija) produce `data/pedidos_raw.csv`, versionado, con al menos 1000 filas.
- RF1.2 Columnas exactas, en este orden: `fecha,cliente,pais,producto,importe,estado`.
- RF1.3 Errores deliberados, todos presentes y con sus recuentos impresos por el generador: duplicados exactos; formatos de fecha mixtos (como mínimo YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, YYYY/MM/DD); fechas imposibles (2024-02-30, 31/04/2024, mes 13); `importe` vacío.
- RF1.4 Ruido opcional: espacios, mayúsculas/minúsculas y coma decimal.

### RF2. Limpieza
- RF2.1 `etl.limpieza.limpiar_filas(filas)` es pura y devuelve `(filas_limpias, informe)`; sin DuckDB ni E/S.
- RF2.2 Se recortan espacios y se normalizan textos; las variantes de país se mapean al catálogo canónico (`PAISES`).
- RF2.3 Las fechas se interpretan con `FORMATOS_FECHA`; las fechas imposibles o no interpretables se descartan.
- RF2.4 Un `importe` vacío, inválido o negativo se descarta; no se imputa ningún valor.
- RF2.5 La deduplicación se hace tras normalizar, sobre las 6 columnas (no existe identificador de pedido); queda documentado.
- RF2.6 El informe cuenta filas leídas, descartadas (con motivo) y duplicadas eliminadas.
- RF2.7 Estados válidos: `completado`, `enviado`, `pendiente`, `cancelado`. Rango de fechas válido: 2024-01-01 a 2025-06-30.

### RF3. Carga y vistas
- RF3.1 `etl.carga.cargar_duckdb(filas, db_path, ruta_vistas)` reemplaza la tabla `pedidos(fecha DATE, cliente VARCHAR, pais VARCHAR, producto VARCHAR, importe DECIMAL(12,2), estado VARCHAR)` y ejecuta `sql/vistas.sql`; es idempotente.
- RF3.2 `python -m etl [--csv] [--db] [--si-falta]`; `--si-falta` solo construye la base si el archivo no existe (lo usa Docker). Base por defecto: `data/pedidos.duckdb`.
- RF3.3 Vista `ventas_por_mes_pais(mes, pais, num_pedidos, total_ventas)`: `mes` es el primer día del mes (DATE); excluye `estado = 'cancelado'`.
- RF3.4 Vista `top_10_clientes(cliente, num_pedidos, total_comprado)`: excluye `cancelado`, ordenada por `total_comprado` descendente, `LIMIT 10`.

### RF4. API de consulta en lenguaje natural
- RF4.1 `POST /consulta` con cuerpo `{"pregunta": str}` (1 a 500 caracteres) devuelve 200 con `{pregunta, sql, columnas, filas}`; fechas en ISO y decimales como número.
- RF4.2 El SQL lo genera un LLM de NVIDIA a través del `Protocol` `ClienteLLM`; la clave se lee de `API_IA_NVIDIA` (SecretStr, opcional) y nunca se registra ni se devuelve.
- RF4.3 El prompt incluye el esquema, los valores canónicos, el rango de fechas y la regla para meses sin año (se consideran todos los años del rango).
- RF4.4 Las consultas pueden usar la tabla `pedidos` y las vistas `ventas_por_mes_pais` y `top_10_clientes`.
- RF4.5 El validador (AST sqlglot, dialecto duckdb) rechaza: SQL vacío o con error de sintaxis; más de una sentencia (se tolera un `;` final); raíz que no sea SELECT (se admiten UNION/INTERSECT/EXCEPT y WITH); cualquier DML/DDL/comando en cualquier punto; relaciones fuera de la lista blanca, catálogos o esquemas distintos de `main`; funciones de tabla o de archivo (`read_csv*`, `read_parquet`, `read_json*`, `glob`, `read_text`, `read_blob`, `query`, `query_table`, `duckdb_*`, `information_schema`). Añade `LIMIT` (por defecto 1000) a la consulta externa si falta.
- RF4.6 La ejecución usa `duckdb.connect(path, read_only=True, config={'enable_external_access': False})`.
- RF4.7 Códigos de error, formato JSON `{"error": código, "mensaje": texto en español}`:

| Situación | HTTP | `error` |
|---|---|---|
| Clave del LLM no configurada | 503 | `llm_no_configurado` |
| Fallo del LLM (red, SDK, respuesta vacía) | 502 | `llm_error` |
| SQL rechazado por el validador (incluye campo `sql`) | 422 | `sql_no_valida` |
| Error al ejecutar el SQL | 422 | `error_ejecucion` |
| Base de datos no disponible | 503 | `base_datos_no_disponible` |
| Cuerpo inválido | 422 | respuesta por defecto de FastAPI |

### RF5. Endpoints del dashboard
- RF5.1 `GET /health` devuelve `{"status":"ok"}`.
- RF5.2 `GET /ventas-por-mes-pais?pais=` (filtro opcional) devuelve `[{mes:"YYYY-MM-DD", pais, num_pedidos, total_ventas}]`.
- RF5.3 `GET /top-clientes` devuelve `[{cliente, num_pedidos, total_comprado}]`.
- RF5.4 Sin prefijo de ruta. CORS con `CORS_ORIGINS` (por defecto http://localhost:5173).
- RF5.5 Los endpoints de vistas usan SQL fijo y parametrizado, sin LLM.

### RF6. Frontend React (Vite + TypeScript)
- RF6.1 Cliente de API único en `src/api/` (URL base `VITE_API_URL`, por defecto http://localhost:8000), con DTO tipados espejo del contrato y un tipo de error `{error, mensaje, sql?}`.
- RF6.2 Dashboard: gráfico de ventas por mes y país (filtro/leyenda por país) y tabla del top 10 de clientes.
- RF6.3 Panel "Pregunta": campo de texto, preguntas de ejemplo pulsables (p. ej. "¿Cuánto vendimos en España en marzo de 2024?"), estado de carga, SQL generado y tabla dinámica de resultados.
- RF6.4 Estados de error claros según el código recibido.
- RF6.5 Diseño responsive; tema claro/oscuro (`prefers-color-scheme` más interruptor manual).
- RF6.6 `frontend/.env.example` con `VITE_API_URL`; `npm run build` debe pasar; tests vitest con fetch simulado recomendados.

### RF7. Docker
- RF7.1 `Dockerfile` raíz (backend, `python:3.14-slim`, usuario no root) que copia código, `data/pedidos_raw.csv` y `sql/`, y ejecuta `python -m etl --si-falta` y luego `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
- RF7.2 `frontend/Dockerfile` multi-etapa (`ARG VITE_API_URL=/api`, nginx:alpine) y `frontend/nginx.conf` con fallback SPA y proxy `/api/` a `http://backend:8000/` sin el prefijo.
- RF7.3 `docker-compose.yml`: `backend` (`env_file: .env`, healthcheck en `/health`, volumen opcional de datos) y `frontend` (puerto 8080:80, `depends_on` backend sano).
- RF7.4 `.dockerignore` raíz y del frontend; `.env` nunca se copia ni se incorpora a una imagen.

## 4. Requisitos no funcionales

- **Seguridad:** `.env` nunca se versiona; `.env.example` solo con marcadores (`API_IA_NVIDIA=`, `NVIDIA_MODEL=`, `DUCKDB_PATH=`, `CORS_ORIGINS=`); validador, lista blanca, conexión de solo lectura sin acceso externo y límite de filas; los errores no revelan la clave ni trazas.
- **Accesibilidad:** HTML semántico, etiquetas en los campos, navegación por teclado, contraste suficiente en ambos temas, `aria-live` para resultados y errores, alternativa en tabla al gráfico, respeto de `prefers-reduced-motion`.
- **Calidad:** SOLID y DRY; constantes definidas una vez en `core/esquema.py`; configuración central con pydantic-settings; `ClienteLLM` inyectado con `Depends` y sustituible en tests.
- **Idioma:** documentación, mensajes de API, interfaz y nombres de objetos SQL en español.
- **Tests:** nunca acceden a la red, pasan con `API_IA_NVIDIA` sin definir y sin leer el `.env` real.
- **Reproducibilidad:** generador con semilla fija; dependencias con límites inferiores en requirements.txt.

## 5. Criterios de aceptación (testables)

| ID | Criterio | Verificación |
|---|---|---|
| CA1 | `python scripts/generar_pedidos.py` produce >= 1000 filas con las columnas exactas y todos los tipos de error, e imprime los recuentos | test del generador |
| CA2 | La limpieza lleva "2024-03-01", "01/03/2024", "01-03-2024" y "2024/03/01" a la misma fecha | test unitario |
| CA3 | Fechas imposibles e importes vacíos, inválidos o negativos se descartan; no hay imputación | test unitario |
| CA4 | Tras normalizar no quedan duplicados sobre las 6 columnas ni países fuera del catálogo | test unitario |
| CA5 | `python -m etl` crea `data/pedidos.duckdb` con `pedidos` y las 2 vistas; ejecutarlo dos veces deja el mismo resultado; `--si-falta` no reconstruye | test de integración |
| CA6 | Las vistas excluyen `cancelado`; `top_10_clientes` devuelve <= 10 filas ordenadas por `total_comprado` descendente | test de integración |
| CA7 | El validador rechaza INSERT/UPDATE/DELETE/DDL, varias sentencias, vacío, relaciones fuera de lista, funciones de archivo y esquemas distintos de `main` | tests del validador |
| CA8 | El validador acepta SELECT, UNION y WITH sobre relaciones permitidas y añade `LIMIT` si falta | tests del validador |
| CA9 | `POST /consulta` con cliente LLM falso devuelve 200 con `pregunta`, `sql`, `columnas`, `filas` | test de endpoint |
| CA10 | SQL inválido devuelve 422 `sql_no_valida` con `sql`; fallo del LLM 502 `llm_error`; sin clave 503 `llm_no_configurado`; base ausente 503 `base_datos_no_disponible`; error de ejecución 422 `error_ejecucion` | tests de endpoint |
| CA11 | `GET /health`, `GET /ventas-por-mes-pais?pais=` y `GET /top-clientes` devuelven 200 con el contrato indicado | test de endpoint |
| CA12 | La conexión de lectura rechaza escrituras | test |
| CA13 | `.env` está ignorado por git y no aparece ninguna clave en el repositorio | revisión y escaneo |
| CA14 | `npm run build` pasa; el dashboard y el panel de preguntas funcionan contra el backend; hay tema claro/oscuro con interruptor, vista responsive y errores por código en `aria-live` | build, vitest y revisión manual |
| CA15 | `docker compose up --build` sirve el frontend en http://localhost:8080 hablando con el backend por `/api` | humo manual |
| CA16 | `python -m pytest -q` pasa con al menos 3 archivos de tests | pytest |
| CA17 | README en español con ejecución local y Docker, decisiones, SOLID/DRY, lista de "más tiempo" y cómo se usó la IA | revisión |

## 6. Fuera de alcance

- Autenticación.
- Memoria de conversación.
- Consultas de escritura.
- Llamadas reales al LLM en los tests.
- Archivos Excel.
- Pipelines de CI.
- Despliegue en la nube.
