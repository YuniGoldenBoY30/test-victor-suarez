# Consultas de pedidos en lenguaje natural

Proyecto de ejemplo que limpia un CSV de pedidos con errores, lo carga en DuckDB y permite hacer preguntas en español sobre las ventas. Un LLM de NVIDIA traduce la pregunta a SQL, un validador lo comprueba y la consulta se ejecuta en modo solo lectura. Incluye un dashboard React con ventas por mes y país y el top 10 de clientes.

## Índice

1. [Qué es](#1-qué-es)
2. [Cómo ejecutarlo](#2-cómo-ejecutarlo)
3. [Ejemplo de API](#3-ejemplo-de-api)
4. [Decisiones tomadas](#4-decisiones-tomadas)
5. [SOLID y DRY en el proyecto](#5-solid-y-dry-en-el-proyecto)
6. [Limpieza de datos](#6-limpieza-de-datos)
7. [Con más tiempo haría](#7-con-más-tiempo-haría)
8. [Cómo se ha usado la IA](#8-cómo-se-ha-usado-la-ia)
9. [Documentación](#9-documentación)

## 1. Qué es

El flujo completo es: `scripts/generar_pedidos.py` genera `data/pedidos_raw.csv` (1050 filas con errores a propósito) → `etl/` limpia los datos con funciones puras y carga la tabla `pedidos` y las vistas `ventas_por_mes_pais` y `top_10_clientes` en DuckDB → `app/` expone una API FastAPI (dashboard y `POST /consulta`) → `frontend/` consume la API con React + Vite + TypeScript.

El diagrama de contenedores, componentes y secuencias está en [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).

## 2. Cómo ejecutarlo

### Requisitos

- Windows (probado en Windows 11), Python 3.14 y Node 24.
- Docker Desktop, solo para la ejecución con contenedores.
- Una clave de la API de NVIDIA (`API_IA_NVIDIA`). Sin ella la API responde `llm_no_configurado`, pero el resto del dashboard funciona.

### Configuración

Copia la plantilla y rellena los valores. El archivo `.env` nunca se sube al repositorio.

```powershell
copy .env.example .env
```

| Variable | Obligatoria | Por defecto | Descripción |
|---|---|---|---|
| `API_IA_NVIDIA` | Sí, para consultas | — | Clave de la API de NVIDIA. No se registra ni se devuelve en ninguna respuesta. |
| `NVIDIA_MODEL` | No | `nvidia/nemotron-3-ultra-550b-a55b` | Modelo usado para generar el SQL. Ver [decisiones](#4-decisiones-tomadas). |
| `DUCKDB_PATH` | No | `data/pedidos.duckdb` | Ruta del archivo DuckDB. |
| `CORS_ORIGINS` | No | `http://localhost:5173` | Orígenes permitidos, separados por comas. |

La configuración completa está en [core/config.py](core/config.py).

### En local

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts/generar_pedidos.py
python -m etl
uvicorn app.main:app --reload
```

La API queda en `http://127.0.0.1:8000` (documentación interactiva en `/docs`). Para el frontend, en otra terminal:

```powershell
cd frontend
copy .env.example .env
npm install
npm run dev
```

El dashboard queda en `http://localhost:5173`. `frontend/.env.example` define `VITE_API_URL=http://localhost:8000`.

`python -m etl` acepta `--csv`, `--db` y `--si-falta` (solo construye la base si no existe).

### Tests

```powershell
python -m pytest -q
cd frontend
npm test
```

Los tests no llaman a la red ni leen el `.env` real.

### Con Docker

```powershell
docker compose up --build
```

La aplicación queda en `http://127.0.0.1:8080`. El frontend sirve la interfaz y envía las peticiones a la API a través de `/api` (proxy de nginx, mismo origen). El backend no publica puertos: solo es accesible desde el frontend.

Notas para Docker Desktop en Windows:

- Si el build pide "additional privileges", ejecuta antes en PowerShell `$env:BUILDX_BAKE_ENTITLEMENTS_FS=0` y vuelve a lanzar el comando.
- La base de datos vive en un volumen. Para regenerarla, ejecuta `docker compose down -v` y después `docker compose up --build`.
- Hosts permitidos: el backend solo acepta las cabeceras `Host` de `TRUSTED_HOSTS` (por defecto `localhost,127.0.0.1,test.zenixtech.ai`). Otro host responde 400. Para cambiarlo, define `TRUSTED_HOSTS` en el entorno del shell antes de `docker compose up` (o en el `.env` de la raíz, que usa Compose para interpolar); no hace falta editar `docker-compose.yml`.

### Despliegue en el VPS

Ver [docs/DESPLIEGUE.md](docs/DESPLIEGUE.md).

## 3. Ejemplo de API

Endpoints principales:

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/health` | Estado del servicio. |
| GET | `/ventas-por-mes-pais?pais=` | Ventas por mes y país (filtro `pais` opcional). |
| GET | `/top-clientes` | Top 10 clientes por importe comprado. |
| POST | `/consulta` | Pregunta en lenguaje natural (1 a 500 caracteres). |

Ejemplo real, con la pregunta "¿Cuánto vendimos en España en marzo de 2024?":

```bash
curl -X POST http://127.0.0.1:8000/consulta \
  -H "Content-Type: application/json" \
  -d '{"pregunta": "¿Cuánto vendimos en España en marzo de 2024?"}'
```

En PowerShell:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/consulta `
  -ContentType "application/json" `
  -Body '{"pregunta": "¿Cuánto vendimos en España en marzo de 2024?"}'
```

Respuesta obtenida:

```json
{
  "pregunta": "¿Cuánto vendimos en España en marzo de 2024?",
  "sql": "SELECT total_ventas FROM ventas_por_mes_pais WHERE mes = CAST('2024-03-01' AS DATE) AND pais = 'España' LIMIT 1000",
  "columnas": ["total_ventas"],
  "filas": [[8748.85]]
}
```

### Errores

Los errores de la aplicación tienen la forma `{"error": "<código>", "mensaje": "<texto en español>"}`. En `sql_no_valida` se añade el campo `sql` con la consulta rechazada.

| HTTP | `error` | Cuándo ocurre |
|---|---|---|
| 503 | `llm_no_configurado` | Falta `API_IA_NVIDIA`. |
| 502 | `llm_error` | El LLM no responde, devuelve error o no genera SQL. |
| 422 | `sql_no_valida` | El SQL generado no supera el validador (no es un SELECT único, usa tablas no permitidas, funciones prohibidas, etc.). |
| 422 | `error_ejecucion` | DuckDB rechaza la consulta al ejecutarla. |
| 503 | `base_datos_no_disponible` | No existe el archivo de la base de datos (ejecuta `python -m etl`). |
| 422 | (validación de FastAPI) | El cuerpo de `/consulta` no cumple el esquema, por ejemplo una pregunta vacía. |

## 4. Decisiones tomadas

Las decisiones de arquitectura (con alternativas y riesgos) están en [docs/revision-arquitectura.md](docs/revision-arquitectura.md). Resumen:

- **DuckDB** como motor analítico embebido: sin servidor adicional, ideal para un conjunto de datos pequeño y para consultas agregadas. Postgres queda para producción (ver [más tiempo](#7-con-más-tiempo-haría)).
- **Validación de SQL con AST de sqlglot** y no con expresiones regulares: el validador recorre el árbol y comprueba que la consulta es un único `SELECT`, que las tablas están en la lista permitida (`pedidos`, `ventas_por_mes_pais`, `top_10_clientes`) y que no hay funciones de lectura de ficheros ni comandos DDL/DML.
- **`WITH RECURSIVE` rechazado**: la revisión cruzada encontró que permitía leer tablas prohibidas con una CTE autorreferencial. Se bloquea por completo y tiene test de regresión.
- **Conexión de solo lectura con `enable_external_access=False`** como segunda barrera: aunque el validador fallara, DuckDB no podría leer ficheros ni salir a la red.
- **`LIMIT` siempre acotado**: si la consulta no tiene `LIMIT`, o tiene uno mayor de 1000, se fija `LIMIT 1000`; ningún resultado se devuelve sin límite.
- **Deduplicación sin identificador de pedido**: el CSV no trae un id, así que se consideran duplicados los registros idénticos en las seis columnas tras normalizarlas.
- **Descartar en lugar de imputar**: fechas imposibles o no parseables, importes vacíos, no válidos o negativos se descartan y se cuentan en el informe. No se inventan valores.
- **Cancelados fuera de las vistas**: `ventas_por_mes_pais` y `top_10_clientes` excluyen `estado = 'cancelado'`.
- **Mes sin año = todos los años del rango**: si la pregunta dice "marzo" sin año, el prompt indica al LLM que considere todos los años de 2024-01-01 a 2025-06-30. Está documentado como regla y es una de las ambigüedades que se verían mejor con una pregunta de aclaración.
- **Proxy nginx en `/api`** (mismo origen): el navegador habla solo con el frontend, así que el backend no necesita publicarse ni abrir CORS en producción. En local se usa CORS.
- **Modelo por defecto `nvidia/nemotron-3-ultra-550b-a55b`**: `meta/llama-3.3-70b-instruct` devolvió `410 Gone`. Se sondearon 42 modelos y respondieron 6; este fue el elegido. Es configurable con `NVIDIA_MODEL`.

## 5. SOLID y DRY en el proyecto

- **Inversión de dependencias (DIP)**: el LLM está detrás del `Protocol` `ClienteLLM` ([app/llm.py](app/llm.py)) y se inyecta con `Depends` ([app/dependencias.py](app/dependencias.py)). Los tests de la API usan un LLM falso y no llaman a NVIDIA.
- **Responsabilidad única (SRP)**: el validador ([app/validador_sql.py](app/validador_sql.py)) no importa ni el LLM ni DuckDB; solo decide si un SQL es aceptable. La limpieza ([etl/limpieza.py](etl/limpieza.py)) es una función pura sin acceso a disco ni a la base.
- **Fábrica sin efectos secundarios**: [app/fabrica.py](app/fabrica.py) construye la aplicación sin conectar a la base ni leer el `.env` al importarse; por eso `app.main` se puede importar en los tests.
- **Constantes definidas una vez**: esquema, países canónicos, estados, formatos de fecha y relaciones permitidas viven en [core/esquema.py](core/esquema.py) y los usan el ETL, el validador y el prompt.
- **Configuración centralizada**: [core/config.py](core/config.py) es la única fuente de ajustes.
- **Frontend**: el acceso a la API está aislado en `frontend/src/api/` y los tipos (DTO) reflejan el contrato del backend.

## 6. Limpieza de datos

Informe real del ETL sobre `data/pedidos_raw.csv`:

| Concepto | Filas |
|---|---|
| Filas de entrada | 1050 |
| Descartadas por fecha | 32 |
| Descartadas por importe | 18 |
| Duplicados eliminados | 48 |
| **Filas cargadas** | **952** |

Los errores que el generador introduce a propósito son: duplicados exactos, formatos de fecha mezclados (`YYYY-MM-DD`, `DD/MM/YYYY`, `DD-MM-YYYY`, `YYYY/MM/DD`), fechas imposibles (`2024-02-30`, `31/04/2024`, mes 13), importes vacíos y decimales con coma. Las reglas están en [docs/TRD.md](docs/TRD.md).

## 7. Con más tiempo haría

- Autenticación de usuarios: el VPS es público y la API no tiene login. (La limitación de peticiones por cliente y el tope diario ya están implementados; ver docs/TRD.md, sección 11.)
- Registro de auditoría de preguntas y SQL generado.
- Pregunta de aclaración cuando el mes no trae año.
- Caché de respuestas del LLM.
- Evaluación del LLM con un conjunto de preguntas con respuesta conocida.
- CI (lint, tests y build) en cada cambio.
- Postgres en producción en lugar de un fichero DuckDB.
- Observabilidad (logs estructurados, métricas, trazas).
- Un modelo de respaldo si el principal falla.

## 8. Cómo se ha usado la IA

El proyecto se construyó con Claude Code, con Opus como coordinador, dentro de un proceso multiagente (GOAT):

- Un **planificador** (Opus) escribió la especificación y el plan dividido en pasos, con un nivel de complejidad por paso.
- Los **trabajadores** (Haiku y Sonnet) implementaron cada paso: documentación, código, tests y revisiones adversariales.
- Cada paso lo revisó un **modelo distinto** del que lo hizo (GPT mediante Codex, o Opus/Sonnet según el caso) antes de confirmarse. Hubo un commit por paso verificado.

Errores reales que corrigió la revisión cruzada:

- El validador dejaba leer una tabla prohibida con `WITH RECURSIVE x AS (SELECT * FROM x)`. Ahora se bloquea con test de regresión.
- UNNEST y funciones de tabla en `FROM` no estaban controlados.
- La clave de API podía filtrarse a través de `__context__` de una excepción encadenada. Se escaló a un trabajador de nivel superior.
- Fechas fuera de rango e importes como `1e100` rompían la carga.
- Valores JSON anidados (`list(fecha)`) rompían la limpieza.
- Importar `app.main` leía el `.env` real en los tests.
- Una subclase usada como parche para el SQL rechazado se sustituyó por un error que lleva el SQL.
- Los primeros documentos de producto inventaron nombres de endpoints porque el agente recibió la especificación truncada. Se corrigió guardando la especificación completa.

Qué se aceptó del resultado: el diseño general, la estructura de ficheros y el frontend.

Qué se hizo a mano o lo decidió la persona: el stack, las reglas de trabajo (commits por paso, PRs, no subir `.env` nunca) y la aceptación del despliegue en el VPS.

> **Notas del autor:** _Yuniel Silva_

## 9. Documentación

- [docs/KICKOFF.md](docs/KICKOFF.md): arranque del proyecto y riesgos.
- [docs/PRD.md](docs/PRD.md): requisitos de producto.
- [docs/BACKLOG.md](docs/BACKLOG.md): historias de usuario.
- [docs/PLAN.md](docs/PLAN.md): plan de entregas.
- [docs/TRD.md](docs/TRD.md): requisitos técnicos.
- [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md): diagramas C4 y de secuencia.
- [docs/revision-arquitectura.md](docs/revision-arquitectura.md): ADRs, riesgos y checklist SOLID/DRY.
- [docs/DESPLIEGUE.md](docs/DESPLIEGUE.md): despliegue en el VPS.
