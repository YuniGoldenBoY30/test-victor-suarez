# Arquitectura

Vistas C4 (contexto, contenedores, componentes), secuencia de una consulta y topología de Docker Compose. Complementa a `docs/TRD.md`.

## 1. Contexto (C4 nivel 1)

```mermaid
C4Context
    title Contexto del sistema: panel de pedidos
    Person(analista, "Analista de negocio", "Explora pedidos y pregunta en español")
    System(panel, "Panel de pedidos", "Dashboard y consultas en lenguaje natural sobre pedidos")
    System_Ext(nvidia, "API de NVIDIA", "LLM compatible con OpenAI que genera SQL")
    Rel(analista, panel, "Usa", "HTTPS")
    Rel(panel, nvidia, "Pide SQL", "HTTPS, clave API_IA_NVIDIA")
```

## 2. Contenedores (C4 nivel 2)

```mermaid
C4Container
    title Contenedores
    Person(analista, "Analista de negocio")
    System_Ext(nvidia, "API de NVIDIA", "LLM")
    System_Boundary(panel, "Panel de pedidos") {
        Container(nginx, "Frontend", "nginx + React/TypeScript (Vite)", "Sirve la SPA y hace proxy de /api/")
        Container(api, "Backend", "Python 3.14, FastAPI", "Dashboard y POST /consulta")
        ContainerDb(db, "Base de datos", "DuckDB (archivo)", "Tabla pedidos y 2 vistas")
        Container(etl, "ETL", "Python, python -m etl", "Limpia el CSV y carga DuckDB")
    }
    Rel(analista, nginx, "Navega", "HTTP :8080")
    Rel(nginx, api, "Proxy /api/", "HTTP :8000")
    Rel(api, db, "Lee", "solo lectura, sin acceso externo")
    Rel(api, nvidia, "Genera SQL", "HTTPS")
    Rel(etl, db, "Reemplaza pedidos y vistas", "escritura")
```

El ETL se ejecuta en el arranque del contenedor backend (`python -m etl --si-falta`) y a mano en desarrollo.

## 3. Componentes del backend (C4 nivel 3)

```mermaid
C4Component
    title Componentes del backend
    Container_Boundary(api, "Backend FastAPI") {
        Component(main, "app.main", "FastAPI", "Rutas, CORS y manejadores de error")
        Component(dep, "app.dependencias", "Depends", "Inyecta settings, cliente LLM, servicio y repositorio")
        Component(serv, "app.servicio", "ServicioConsultas", "Orquesta LLM, validación y ejecución")
        Component(repo, "app.repositorio_vistas", "RepositorioVistas", "SQL fijo y parametrizado de las vistas")
        Component(llm, "app.llm + app.prompt", "ClienteLLM / ClienteNvidia", "Genera SQL con el LLM")
        Component(val, "app.validador_sql", "sqlglot", "Valida el SQL, independiente de LLM y BD")
        Component(db, "app.db", "duckdb", "Conexión de solo lectura")
        Component(cfg, "core.config + core.esquema", "pydantic-settings", "Configuración y constantes únicas")
    }
    ContainerDb(duck, "DuckDB", "archivo")
    System_Ext(nvidia, "API de NVIDIA")
    Rel(main, dep, "Usa")
    Rel(dep, serv, "Construye")
    Rel(dep, repo, "Construye")
    Rel(serv, llm, "generar_sql")
    Rel(serv, val, "validar_sql")
    Rel(serv, db, "abrir_conexion")
    Rel(repo, db, "abrir_conexion")
    Rel(llm, nvidia, "HTTPS")
    Rel(db, duck, "read_only")
    Rel(dep, cfg, "Lee")
    Rel(val, cfg, "RELACIONES_PERMITIDAS")
    Rel(llm, cfg, "Settings y prompt")
```

## 4. Secuencia de una consulta

```mermaid
sequenceDiagram
    autonumber
    actor U as Analista
    participant F as React (src/api)
    participant A as FastAPI (main)
    participant S as ServicioConsultas
    participant L as ClienteNvidia
    participant N as API de NVIDIA
    participant V as validar_sql
    participant D as DuckDB (solo lectura)

    U->>F: Escribe la pregunta
    F->>A: POST /consulta {pregunta}
    A->>S: consultar(pregunta)
    S->>L: generar_sql(pregunta)
    L->>N: mensajes (esquema, valores, fechas)
    N-->>L: SQL generado
    L-->>S: SQL sin vallas markdown
    S->>V: validar_sql(sql)
    alt SQL no permitido
        V-->>A: SQLNoPermitidoError
        A-->>F: 422 sql_no_valida + sql
    else SQL válido (con LIMIT)
        S->>D: ejecutar y cerrar
        D-->>S: columnas y filas
        S-->>A: ResultadoConsulta
        A-->>F: 200 {pregunta, sql, columnas, filas}
    end
    F-->>U: SQL generado y tabla (aria-live)
```

Los fallos del LLM (502 `llm_error`, 503 `llm_no_configurado`) y de base de datos (503 `base_datos_no_disponible`, 422 `error_ejecucion`) se traducen en `app.main` a `{"error", "mensaje"}`.

Los endpoints del dashboard (`GET /ventas-por-mes-pais`, `GET /top-clientes`) no usan el LLM: `main` llama a `RepositorioVistas`, que abre la conexión de solo lectura y ejecuta SQL fijo.

## 5. Topología de Docker Compose

```mermaid
flowchart LR
    U[Navegador] -->|http://localhost:8080| FE
    subgraph compose[docker compose]
        FE["frontend<br/>nginx:alpine<br/>puerto 80"]
        BE["backend<br/>FastAPI + uvicorn<br/>puerto 8000"]
        VOL[("volumen de datos<br/>pedidos.duckdb")]
        FE -->|"/api/ proxy, sin prefijo"| BE
        BE --- VOL
    end
    ENV[".env (env_file)"] -.->|solo en ejecución| BE
    BE -->|HTTPS| NV[API de NVIDIA]
```

- El navegador solo habla con `frontend` (8080:80). La imagen se construye con `VITE_API_URL=/api`, así que las llamadas son del mismo origen y no necesitan CORS.
- nginx sirve `dist` con fallback a `index.html` y reenvía `/api/` a `http://backend:8000/` quitando el prefijo.
- `backend` ejecuta `python -m etl --si-falta` y luego uvicorn; su healthcheck consulta `/health`; `frontend` espera a que esté sano (`depends_on`).
- `.env` entra solo como `env_file` en tiempo de ejecución; no se copia a ninguna imagen.
- En desarrollo local no hay nginx: Vite en `:5173` llama a `http://localhost:8000` y se usa CORS (`CORS_ORIGINS`).
