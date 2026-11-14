# KICKOFF: Panel de pedidos con consultas en lenguaje natural

## 1. Contexto

La empresa dispone de un export de pedidos en CSV (`data/pedidos_raw.csv`) con datos sucios: fechas en varios formatos o imposibles, países escritos de distintas maneras, importes vacíos y filas duplicadas. Hoy nadie puede responder preguntas de negocio sin limpiar a mano y escribir SQL.

El proyecto construye la cadena completa: CSV sucio, limpieza, carga en DuckDB con dos vistas analíticas, una API FastAPI que traduce preguntas en español a SQL mediante un LLM de NVIDIA, y un panel React (Vite + TypeScript) que muestra los resultados. Todo el texto de cara al usuario (docs, README, mensajes de la API, interfaz y nombres de objetos SQL) va en español.

## 2. Objetivos

1. Generar un CSV sucio reproducible (semilla fija) de al menos 1000 pedidos con columnas `fecha,cliente,pais,producto,importe,estado`.
2. Limpiar los datos con reglas puras y testeables y cargarlos en DuckDB (`data/pedidos.duckdb`).
3. Exponer dos vistas SQL: `ventas_por_mes_pais` y `top_10_clientes`, que excluyen los pedidos `cancelado`.
4. Responder preguntas en lenguaje natural con SQL generado por LLM, validado con sqlglot y ejecutado en modo solo lectura.
5. Mostrar un dashboard React y un panel de preguntas.
6. Empaquetar con Docker (backend, frontend con nginx, docker-compose).
7. Entregar al menos 3 archivos de tests pytest y un README en español.

Medida de éxito: `docker compose up --build` sirve el frontend en http://localhost:8080 hablando con el backend por `/api`; `python -m pytest -q` pasa; ninguna consulta que no sea un SELECT sobre `pedidos` y las dos vistas llega a ejecutarse.

## 3. Stakeholders

| Rol | Interés | Participación |
|---|---|---|
| Responsable de producto | Define alcance y acepta entregables | Aprueba cada hito |
| Analista de negocio | Consultar pedidos sin escribir SQL | Usuario principal del panel |
| Responsable de datos | Calidad de la limpieza y reglas | Revisa reglas de limpieza |
| Seguridad | Que el LLM no modifique datos ni se filtre la clave | Revisa validador y manejo de la clave |
| Equipo de desarrollo (agentes GOAT) | Construir y verificar por pasos | Ejecución |

## 4. Alcance

### Dentro del alcance
- Generador `scripts/generar_pedidos.py` y CSV `data/pedidos_raw.csv` (>= 1000 filas, versionado, semilla fija).
- ETL: limpieza pura, carga en DuckDB y CLI `python -m etl` (`--csv`, `--db`, `--si-falta`).
- Dos vistas SQL en español que excluyen `cancelado`.
- API FastAPI: `GET /health`, `GET /ventas-por-mes-pais?pais=`, `GET /top-clientes`, `POST /consulta`, CORS.
- Validación sqlglot (un único SELECT; relaciones permitidas: `pedidos`, `ventas_por_mes_pais`, `top_10_clientes`) y conexión de solo lectura.
- Frontend React: gráfico de ventas por mes y país, top 10 de clientes, panel de preguntas con ejemplos, responsive, tema claro/oscuro con interruptor, errores por código, regiones `aria-live`.
- Docker y docker-compose; documentación en español (docs/ y README.md); pruebas pytest.

### Fuera del alcance (non-goals)
- Autenticación y usuarios.
- Memoria de conversación con el LLM.
- Consultas de escritura (INSERT, UPDATE, DELETE, DDL).
- Llamadas reales al LLM en los tests.
- Archivos Excel.
- Pipelines de CI.
- Despliegue en nube gestionada (PaaS, Kubernetes). El despliegue de pruebas se hace en un VPS propio con Apache como proxy inverso (`test.zenixtech.ai`, ver `docs/DESPLIEGUE.md`).

## 5. Riesgos

| Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|
| El LLM genera SQL destructivo o accede a relaciones no permitidas | Media | Alto | Validador sqlglot sobre AST, lista blanca, conexión DuckDB de solo lectura sin acceso externo, tests |
| La clave de NVIDIA (`API_IA_NVIDIA`) se sube al repositorio | Baja | Alto | `.env` ignorado, `.env.example` solo con marcadores, `.env` nunca copiado a imágenes Docker |
| Wheels de Python 3.14 o imagen `python:3.14-slim` no disponibles | Baja | Medio | Instalaciones verificadas (duckdb, fastapi, sqlglot, openai, pandas); comprobar la imagen en el paso Docker |
| Los nombres de nodos de sqlglot cambian entre versiones | Media | Medio | Versión fijada con límite inferior y tests del validador |
| Ambigüedad del LLM (mes sin año) | Media | Medio | Regla en el prompt: se consideran todos los años del rango 2024-01-01 a 2025-06-30; documentada |
| Deriva del contrato frontend/backend | Media | Medio | Contrato fijo, tipos DTO espejo, tests con fetch simulado y humo end-to-end en Docker |
| CORS frente al proxy nginx | Baja | Bajo | Compose usa `/api` mismo origen; desarrollo local usa CORS (`CORS_ORIGINS`) |

## 6. Cronograma

Estimación en jornadas; cada fase termina en un commit verificado (ver PLAN.md).

| Fase | Contenido | Pasos | Duración |
|---|---|---|---|
| 1. Diseño | Docs de producto y técnicos | s1, s2 | 1 jornada |
| 2. Datos | Base backend, generador CSV, ETL y vistas | s3, s4, s5 | 2 jornadas |
| 3. Consulta segura | Validador SQL, cliente LLM y servicio, API | s6, s7, s8 | 3 jornadas |
| 4. Interfaz | Frontend React | s9 | 2 jornadas |
| 5. Entrega | Docker y README | s10, s11 | 1 jornada |
