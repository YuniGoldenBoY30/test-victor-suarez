# PLAN

Plan de construcción por fases e hitos. Cada hito corresponde a un paso (s1..s11) y termina en un único commit verificado (versionado atómico). Los documentos van antes que el código; el código sigue a los documentos y las desviaciones se declaran en el informe del paso y en el README.

## Resumen

| Fase | Hito | Paso | Entregable | Depende de | Commit |
|---|---|---|---|---|---|
| 1. Diseño | H1 | s1 | Docs de producto: KICKOFF, PRD, BACKLOG, PLAN | ninguno | docs de producto |
| 1. Diseño | H2 | s2 | Docs técnicos: TRD, ARQUITECTURA (C4 mermaid), revision-arquitectura (ADRs, riesgos, SOLID/DRY) | s1 | docs técnicos |
| 2. Datos | H3 | s3 | Base backend: `requirements.txt`, `pytest.ini`, `.env.example`, `core/config.py`, `core/esquema.py` y test | s2 | base backend |
| 2. Datos | H4 | s4 | `scripts/generar_pedidos.py`, `data/pedidos_raw.csv` (>= 1000 filas, semilla fija) y test | s3 | generador CSV |
| 2. Datos | H5 | s5 | ETL: `etl/limpieza.py`, `etl/carga.py`, `etl/__main__.py` (`--si-falta`), `sql/vistas.sql`, tests y fixture `db_prueba` | s3 | ETL y vistas |
| 3. Consulta segura | H6 | s6 | `app/validador_sql.py` (sqlglot) y tests | s3 | validador SQL |
| 3. Consulta segura | H7 | s7 | `app/llm.py` (Protocol + NVIDIA), `app/prompt.py`, `app/db.py`, `app/errores.py`, `app/servicio.py`, `app/repositorio_vistas.py` y tests | s5, s6 | servicio NL a SQL |
| 3. Consulta segura | H8 | s8 | `app/modelos.py`, `app/dependencias.py`, `app/main.py`: `/health`, `/ventas-por-mes-pais`, `/top-clientes`, `POST /consulta`, CORS, manejadores de error y tests | s7 | API |
| 4. Interfaz | H9 | s9 | `frontend/` (Vite + React + TS): dashboard, panel de preguntas, responsive, tema claro/oscuro, errores por código, `aria-live` | s2 | frontend |
| 5. Entrega | H10 | s10 | `Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf`, `docker-compose.yml`, `.dockerignore` | s8, s9 | docker |
| 5. Entrega | H11 | s11 | `README.md` en español | s1 a s10 | README |

## Detalle por fase

### Fase 1. Diseño (s1, s2)
- s1 fija el qué: objetivos, requisitos, historias y plan.
- s2 fija el cómo: TRD, C4 en mermaid, ADRs, riesgos y lista SOLID/DRY.

### Fase 2. Datos (s3, s4, s5)
- s3 deja la base común: configuración y constantes en `core/esquema.py`.
- s4 y s5 dependen de s3 y pueden ir en paralelo (archivos distintos). s5 es dueño de `tests/conftest.py`; los pasos posteriores lo reutilizan sin editarlo.
- Salida: `python -m etl` crea `data/pedidos.duckdb` con `pedidos` y las 2 vistas.

### Fase 3. Consulta segura (s6, s7, s8)
- s6 depende solo de s3 y avanza en paralelo con s4 y s5.
- s7 une validador, cliente LLM, conexión de solo lectura, servicio y repositorio.
- s8 expone todo por FastAPI con el contrato de errores del PRD.

### Fase 4. Interfaz (s9)
- Depende de los documentos (contrato de API), así que puede ir en paralelo con las fases 2 y 3. `npm run build` debe pasar; vitest recomendado.

### Fase 5. Entrega (s10, s11)
- s10 empaqueta con Docker y hace una prueba de humo end-to-end en http://localhost:8080 (`/api`).
- s11 escribe el README al final.

## Orden de ejecución y paralelismo

```
s1 -> s2 -> s3 -> { s4, s5, s6 } -> s7 -> s8 -> s10 -> s11
          s2 -> s9 ---------------------------^
```

Los pasos listos se ejecutan en paralelo (máximo 4) solo si sus archivos no se solapan.

## Reglas de verificación

1. Cada paso lo revisa un modelo distinto del que lo implementó.
2. Un paso rechazado una vez se repite en el mismo nivel; rechazado dos veces, sube de nivel.
3. Solo se hace commit de un paso verificado y con comprobación verde.
4. Comprobaciones: backend `python -m pytest -q` (con `.venv`) tras cada paso de backend; frontend `npm run build` (y `npm test` si hay vitest); Docker `docker compose config` y `docker compose build`.
5. Cierre: todos los pasos verificados y confirmados, y la última comprobación en verde.

## Definición de terminado

- Se cumplen los criterios CA1 a CA17 del PRD.
- `python -m pytest -q` pasa con al menos 3 archivos de tests.
- `docker compose up --build` sirve el frontend en http://localhost:8080.
- La clave del LLM no está en el repositorio ni en las imágenes.
