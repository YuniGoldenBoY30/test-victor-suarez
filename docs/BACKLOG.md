# BACKLOG

Prioridad MoSCoW: **M** (Must), **S** (Should), **C** (Could), **W** (Won't, en esta versión).
Los pasos (s1..s11) remiten a PLAN.md; los requisitos (RF) y criterios (CA), a PRD.md.

## Épica E1. Datos de origen (s4)

### HU-01 Generar el CSV sucio (M)
**Como** responsable de datos, **quiero** un generador determinista de pedidos sucios, **para** disponer de datos de prueba reproducibles.
Criterios de aceptación:
- `scripts/generar_pedidos.py` produce `data/pedidos_raw.csv` con >= 1000 filas y las columnas exactas `fecha,cliente,pais,producto,importe,estado`.
- Con la misma semilla genera el mismo archivo.
- Contiene duplicados exactos; fechas en YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY y YYYY/MM/DD; fechas imposibles (2024-02-30, 31/04/2024, mes 13); `importe` vacío; opcionalmente espacios, mayúsculas y coma decimal.
- Imprime el recuento de cada tipo de error.

## Épica E2. Limpieza y carga (s3, s5)

### HU-02 Normalizar los datos (M)
**Como** responsable de datos, **quiero** `limpiar_filas(filas) -> (filas_limpias, informe)` como función pura, **para** obtener datos consistentes y testeables.
Criterios:
- Recorta espacios, normaliza textos y mapea variantes de país al catálogo canónico.
- Interpreta fechas con `FORMATOS_FECHA`; descarta fechas imposibles o no interpretables.
- Descarta `importe` vacío, inválido o negativo; no imputa valores.
- Deduplica tras normalizar sobre las 6 columnas (sin identificador de pedido; documentado).
- Sin dependencia de DuckDB ni de archivos; el informe cuenta descartes por motivo y duplicados.

### HU-03 Cargar en DuckDB (M)
**Como** responsable de datos, **quiero** `cargar_duckdb(filas, db_path, ruta_vistas)`, **para** consultar los pedidos con SQL.
Criterios:
- Reemplaza la tabla `pedidos(fecha DATE, cliente VARCHAR, pais VARCHAR, producto VARCHAR, importe DECIMAL(12,2), estado VARCHAR)` y ejecuta `sql/vistas.sql`.
- Idempotente; la base (`data/pedidos.duckdb`) no se versiona.

### HU-04 Ejecutar el ETL por CLI (M)
**Como** operador, **quiero** `python -m etl [--csv] [--db] [--si-falta]`, **para** crear la base solo cuando falta (uso en Docker).
Criterios:
- Sin `--si-falta` recarga siempre; con ella no hace nada si el archivo de base existe.
- Muestra un resumen en español.

### HU-05 Vistas analíticas (M)
**Como** analista, **quiero** `ventas_por_mes_pais` y `top_10_clientes`, **para** responder preguntas frecuentes.
Criterios:
- `ventas_por_mes_pais(mes, pais, num_pedidos, total_ventas)` con `mes` = primer día del mes.
- `top_10_clientes(cliente, num_pedidos, total_comprado)` ordenada por `total_comprado` descendente, `LIMIT 10`.
- Ambas se crean con `CREATE OR REPLACE VIEW` y excluyen `estado = 'cancelado'`.

### HU-06 Configuración y esquema centralizados (M)
**Como** desarrollador, **quiero** configuración y constantes en un único lugar, **para** no repetir nombres ni rutas (DRY).
Criterios:
- `core/config.py` (pydantic-settings): `API_IA_NVIDIA` (SecretStr, opcional), `NVIDIA_MODEL`, `nvidia_base_url`, `llm_timeout`, `DUCKDB_PATH`, `CORS_ORIGINS`; `get_settings()` en caché.
- `core/esquema.py`: columnas, países y variantes, estados, `ESTADO_EXCLUIDO_VENTAS`, rango de fechas, `FORMATOS_FECHA`, `RELACIONES_PERMITIDAS`, `LIMITE_FILAS_DEFECTO`, rutas y `DESCRIPCION_ESQUEMA`.
- `.env.example` solo con marcadores.

## Épica E3. Consulta segura en lenguaje natural (s6, s7, s8)

### HU-07 Validar el SQL generado (M)
**Como** responsable de seguridad, **quiero** `validar_sql` sobre el AST de sqlglot, **para** que solo se ejecute un SELECT permitido.
Criterios:
- Rechaza vacío, error de sintaxis, varias sentencias (se tolera un `;` final) y raíz que no sea SELECT (UNION/INTERSECT/EXCEPT y WITH sí se aceptan).
- Rechaza DML, DDL y comandos en cualquier nodo (Insert, Update, Delete, Merge, Create, Drop, Alter, Command, Pragma, Copy, Attach/Detach, Set, Use, Transaction).
- Solo `pedidos`, `ventas_por_mes_pais`, `top_10_clientes` o CTE de la misma consulta; ningún catálogo o esquema distinto de `main`.
- Rechaza funciones de tabla o archivo (`read_csv*`, `read_parquet`, `read_json*`, `glob`, `read_text`, `read_blob`, `query`, `query_table`, `duckdb_*`, `information_schema`).
- Añade `LIMIT` a la consulta externa si falta. No importa duckdb ni LLM.

### HU-08 Ejecutar en solo lectura (M)
**Como** responsable de seguridad, **quiero** una conexión de solo lectura, **para** tener una segunda barrera.
Criterios:
- `duckdb.connect(path, read_only=True, config={'enable_external_access': False})`.
- Archivo ausente: `BaseDatosNoDisponibleError` (`base_datos_no_disponible`).
- Error de ejecución: `ErrorEjecucionSQL` (`error_ejecucion`).

### HU-09 Traducir preguntas a SQL con LLM (M)
**Como** analista, **quiero** preguntar en español, **para** obtener datos sin saber SQL.
Criterios:
- `ClienteLLM` (Protocol) con `generar_sql(pregunta)`; `ClienteNvidia` usa el SDK openai con base URL, modelo y timeout de Settings; quita las vallas markdown.
- Error de red/SDK o contenido vacío: `LLMError`; sin clave: `LLMNoConfiguradoError`. La clave nunca se registra ni se devuelve.
- El prompt incluye esquema, valores canónicos, rango de fechas y regla de mes sin año.

### HU-10 Servicio y repositorio de vistas (M)
**Como** desarrollador, **quiero** `ServicioConsultas` y `RepositorioVistas` sin dependencias de FastAPI, **para** reutilizarlos y testearlos.
Criterios:
- Flujo LLM, `validar_sql`, ejecución de solo lectura, cierre; resultado con fechas ISO y Decimal como float.
- El repositorio usa SQL fijo y parametrizado; `ventas_por_mes_pais(pais=None)` y `top_10_clientes()`.

### HU-11 Endpoint POST /consulta (M)
**Como** analista, **quiero** enviar una pregunta y recibir SQL y resultados, **para** verificar y usar la respuesta.
Criterios:
- Cuerpo `{"pregunta": str 1..500}`; 200 con `{pregunta, sql, columnas, filas}`.
- Errores `{"error", "mensaje"}`: 503 `llm_no_configurado`; 502 `llm_error`; 422 `sql_no_valida` (con `sql`); 422 `error_ejecucion`; 503 `base_datos_no_disponible`; cuerpo inválido, 422 por defecto de FastAPI.

### HU-12 Endpoints del dashboard (M)
**Como** analista, **quiero** `GET /health`, `GET /ventas-por-mes-pais?pais=` y `GET /top-clientes`, **para** alimentar el dashboard.
Criterios:
- `/health` devuelve `{"status":"ok"}`.
- `/ventas-por-mes-pais` devuelve `[{mes, pais, num_pedidos, total_ventas}]` con `mes` en `YYYY-MM-DD`; `pais` filtra.
- `/top-clientes` devuelve `[{cliente, num_pedidos, total_comprado}]`.

### HU-13 CORS, dependencias y errores (S)
**Como** desarrollador, **quiero** CORS configurable y dependencias sustituibles, **para** integrar el frontend y testear sin red.
Criterios:
- `CORSMiddleware` con `settings.cors_origins` (por defecto http://localhost:5173).
- `get_settings`, `get_cliente_llm`, `get_servicio` y `get_repositorio` se pueden sobrescribir en tests.

## Épica E4. Frontend (s9)

### HU-14 Cliente de API tipado (M)
**Como** desarrollador frontend, **quiero** un único cliente en `src/api/`, **para** aislar el acceso al backend.
Criterios:
- URL base de `VITE_API_URL` (por defecto http://localhost:8000); DTO tipados espejo del contrato; error con `{error, mensaje, sql?}`; `frontend/.env.example`.

### HU-15 Dashboard de ventas (M)
**Como** analista, **quiero** un gráfico de ventas por mes y país con filtro o leyenda por país, **para** ver la evolución del negocio.
Criterios:
- Estados de carga, vacío y error; alternativa en tabla.

### HU-16 Top 10 de clientes (M)
**Como** analista, **quiero** una tabla de los 10 mejores clientes, **para** identificar cuentas clave.
Criterios:
- Ordenada por `total_comprado`, con cabeceras accesibles.

### HU-17 Panel de preguntas (M)
**Como** analista, **quiero** escribir una pregunta o pulsar un ejemplo y ver SQL y resultados, **para** explorar los datos.
Criterios:
- Campo con etiqueta, envío por botón o teclado, ejemplos pulsables (p. ej. "¿Cuánto vendimos en España en marzo de 2024?"), estado de carga.
- Muestra el SQL generado y una tabla dinámica de resultados.
- Mensajes de error claros por código (`llm_no_configurado`, `llm_error`, `sql_no_valida`, `error_ejecucion`, `base_datos_no_disponible`), anunciados en una región `aria-live`.

### HU-18 Diseño responsive y tema claro/oscuro (S)
**Como** usuario, **quiero** una interfaz adaptable y con tema claro/oscuro, **para** usarla en cualquier dispositivo y preferencia.
Criterios:
- Responsive; tema según `prefers-color-scheme` más interruptor manual; contraste suficiente en ambos; navegación por teclado y foco visible; `prefers-reduced-motion` respetado.

### HU-19 Tests del frontend (S)
**Como** equipo, **quiero** tests vitest del cliente y de la presentación de errores con fetch simulado, **para** evitar deriva del contrato.
Criterios:
- `npm run build` pasa; `npm test` pasa si vitest está presente.

## Épica E5. Empaquetado y documentación (s1, s2, s10, s11)

### HU-20 Docker (M)
**Como** operador, **quiero** `docker compose up --build`, **para** levantar todo con un comando.
Criterios:
- `Dockerfile` backend (python:3.14-slim, usuario no root, `python -m etl --si-falta` y uvicorn en 8000) y `.dockerignore`.
- `frontend/Dockerfile` multi-etapa con nginx, `ARG VITE_API_URL=/api`, fallback SPA y proxy `/api/` a `http://backend:8000/` sin prefijo; `frontend/.dockerignore`.
- `docker-compose.yml`: backend con `env_file: .env` y healthcheck; frontend en 8080:80 con `depends_on` sano.
- `.env` no se copia ni se incorpora a ninguna imagen.

### HU-21 Documentación de producto y técnica (M)
**Como** equipo, **quiero** KICKOFF, PRD, BACKLOG, PLAN, TRD, arquitectura y revisión de arquitectura, **para** guiar la construcción.
Criterios:
- Todo en español y alineado con el contrato; arquitectura con C4 en mermaid; ADRs, riesgos y lista SOLID/DRY.

### HU-22 README en español (M)
**Como** nuevo desarrollador, **quiero** un README claro, **para** instalar, ejecutar y testear el proyecto.
Criterios:
- Ejecución local y Docker, decisiones, SOLID/DRY, lista de "más tiempo", cómo se usó la IA (proceso real y espacio marcado para notas del autor) y desviaciones respecto a la documentación.
- Explica que `.env` nunca se sube.

## Épica E6. Calidad y seguridad transversal

### HU-23 Tests automatizados (M)
**Como** equipo, **quiero** al menos 3 archivos de tests pytest, **para** detectar regresiones.
Criterios:
- `tests/conftest.py` con la fixture `db_prueba(tmp_path)` (incluye un pedido `cancelado`); tests de config, generador, limpieza, carga y vistas, validador, servicio, repositorio y API (éxito, fallo del LLM, SQL inválido).
- Sin red, con `API_IA_NVIDIA` sin definir y sin leer el `.env` real.

### HU-24 Protección de secretos (M)
**Como** responsable de seguridad, **quiero** que la clave nunca llegue al repositorio ni a las imágenes, **para** evitar fugas.
Criterios:
- `.env` y `.env.*` ignorados; `.env.example` versionado sin valores; compose pasa la clave solo por `env_file`.

## Fuera de esta versión (W)

- Autenticación y usuarios.
- Memoria de conversación.
- Consultas de escritura.
- Llamadas reales al LLM en tests.
- Archivos Excel.
- Pipelines de CI.
- Despliegue en la nube.
