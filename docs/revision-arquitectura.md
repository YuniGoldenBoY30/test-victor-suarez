# Revisión de arquitectura

Decisiones (ADR), trade-offs, riesgos y listas de comprobación. Complementa a `docs/TRD.md` y `docs/ARQUITECTURA.md`.

## 1. Registro de decisiones (ADR)

### ADR-1. DuckDB como base de datos
- **Contexto:** pocos miles de pedidos, análisis agregado, solo lectura desde la API, sin servicio de base de datos que mantener.
- **Decisión:** DuckDB en archivo (`data/pedidos.duckdb`), recreado por el ETL.
- **Consecuencias:** despliegue trivial y SQL analítico potente; un solo escritor a la vez, por lo que la API abre conexiones de solo lectura por consulta y el ETL se ejecuta antes de arrancar.
- **Alternativas:** SQLite (menos funciones analíticas), PostgreSQL (infraestructura innecesaria).

### ADR-2. sqlglot para validar el SQL
- **Contexto:** el SQL viene de un LLM y no es confiable.
- **Decisión:** analizar con el AST de sqlglot (dialecto duckdb) y aplicar reglas explícitas (una sentencia, raíz SELECT, sin DML/DDL/comandos, lista blanca de relaciones, sin funciones de tabla ni archivo, `LIMIT`).
- **Consecuencias:** más robusto que las regex; los nombres de nodo varían entre versiones de sqlglot, por lo que los tests cubren los casos y la versión se fija con límite inferior.
- **Alternativas:** regex o lista de palabras (eludibles), solo permisos de la base de datos (insuficiente por sí solo).

### ADR-3. `ClienteLLM` como Protocol inyectado
- **Decisión:** `ClienteLLM.generar_sql(pregunta)` es un `Protocol`; `ClienteNvidia` es la implementación; FastAPI lo inyecta con `Depends` (`get_cliente_llm`).
- **Consecuencias:** los tests usan un cliente falso sin red (principios de inversión de dependencias y sustitución de Liskov); cambiar de proveedor no toca servicio ni validador.

### ADR-4. Conexión `read_only=True` con `enable_external_access=False`
- **Decisión:** `duckdb.connect(path, read_only=True, config={'enable_external_access': False})`.
- **Consecuencias:** segunda barrera tras el validador: aunque este fallara, no se puede escribir ni leer archivos o URL. Una conexión por consulta, cerrada al terminar.

### ADR-5. Proxy nginx frente a CORS
- **Decisión:** en Docker, nginx sirve la SPA y hace proxy de `/api/` al backend (mismo origen, imagen con `VITE_API_URL=/api`). En desarrollo local, CORS con `CORS_ORIGINS`.
- **Consecuencias:** sin CORS en producción ni puertos del backend expuestos al navegador; el backend mantiene CORS para el desarrollo con Vite.
- **Alternativa:** exponer el backend y depender solo de CORS (más superficie y configuración).

### ADR-6. pydantic-settings para la configuración
- **Decisión:** un único módulo `core/config.py` con `Settings` y `get_settings()` con caché; la clave como `SecretStr` opcional.
- **Consecuencias:** configuración tipada y validada, un solo punto de lectura del entorno, fácil de sustituir en tests (`Settings(_env_file=None)`). Sin clave la API arranca y responde 503 `llm_no_configurado` solo al consultar.

### ADR-7. Constantes únicas en `core/esquema.py`
- **Decisión:** países, estados, fechas, relaciones permitidas, descripción del esquema y rutas se definen una vez y las importan generador, limpieza, prompt y validador.
- **Consecuencias:** DRY. Excepción conocida: `sql/vistas.sql` repite `'cancelado'`; un test lo mantiene sincronizado.

### ADR-8. Deduplicación sobre las 6 columnas
- **Decisión:** no hay identificador de pedido; se deduplica tras normalizar.
- **Consecuencia:** dos pedidos legítimos idénticos se colapsan; se acepta y se documenta.

### ADR-9. Apache como proxy inverso en el VPS
- **Decisión:** en el VPS de pruebas (`test.zenixtech.ai`) se reutiliza el Apache 2.4 que ya existe como proxy inverso de entrada (TLS y vhost), delante del nginx del contenedor frontend publicado en `127.0.0.1:8080`.
- **Consecuencias:** las imágenes son las mismas en local y en el VPS; Apache convive con otros vhost del servidor sin ceder los puertos 80/443 a Docker. Hay un salto de proxy más (Apache → nginx), con un coste despreciable.
- **Alternativa:** sustituir Apache por nginx o Traefik en el host (rompería los sitios que ya sirve Apache), o publicar el contenedor directamente en 80/443.

## 2. Trade-offs

| Decisión | Se gana | Se pierde |
|---|---|---|
| Descartar filas inválidas sin imputar | Datos fiables | Pérdida de volumen; el informe de limpieza lo cuantifica |
| Mes sin año = todos los años del rango | Regla simple y documentada | Respuesta que puede agregar varios años |
| Una conexión de solo lectura por consulta | Aislamiento y simplicidad | Coste de apertura (despreciable en DuckDB) |
| `LIMIT` 1000 por defecto | Respuestas acotadas | Resultados truncados en consultas amplias |
| Sin autenticación ni memoria de conversación | Alcance acotado | No apto para exposición pública tal cual |
| Base reconstruida con `--si-falta` | Arranque Docker autónomo | Cambios del CSV exigen borrar el volumen o relanzar el ETL |

## 3. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Inyección SQL o instrucciones peligrosas generadas por el LLM | Validador AST, lista blanca, solo SELECT, conexión de solo lectura, `LIMIT` |
| Inyección de prompt en la pregunta del usuario | El resultado del LLM no es confiable: se valida siempre; límite de 500 caracteres; el prompt no otorga permisos |
| Exfiltración de archivos (`read_csv`, `glob`, `read_text`, `information_schema`) | Rechazo de funciones de tabla y archivo en el validador y `enable_external_access=False` |
| Fuga de la clave `API_IA_NVIDIA` | `SecretStr`, no se registra ni se devuelve, `.env` ignorado y fuera de las imágenes, `env_file` solo en ejecución |
| Ambigüedad del LLM (mes sin año, país con variantes) | Prompt con valores canónicos, rango de fechas y regla de mes sin año |
| Nombres de nodo de sqlglot distintos entre versiones | Versión con límite inferior y tests de cada categoría rechazada |
| Disponibilidad de ruedas para Python 3.14 y de la imagen base | Instalaciones verificadas; en Docker se comprueba `python:3.14-slim` |
| Deriva del contrato frontend/backend | Contrato fijo en el TRD, DTO tipados, tests de cliente con `fetch` simulado, humo de extremo a extremo |
| CORS frente a proxy | Compose usa `/api` del mismo origen; desarrollo usa CORS |
| Indisponibilidad o lentitud del LLM | Timeout de `llm_timeout` y error 502 claro |

## 4. Lista de comprobación SOLID

- **S:** cada módulo del TRD tiene una sola responsabilidad (limpieza pura, carga, validación, LLM, servicio, repositorio, rutas).
- **O:** nuevos proveedores LLM se añaden implementando `ClienteLLM` sin modificar el servicio.
- **L:** cualquier `ClienteLLM` (real o falso) es intercambiable.
- **I:** interfaces pequeñas (`generar_sql`, `abrir_conexion`); el servicio y el repositorio no conocen FastAPI.
- **D:** el servicio depende de abstracciones (`ClienteLLM`, `abrir_conexion`) inyectadas con `Depends`.

## 5. Lista de comprobación DRY

- [ ] Constantes solo en `core/esquema.py`.
- [ ] Configuración solo en `core/config.py`.
- [ ] El validador, el prompt y el generador comparten países, estados y relaciones.
- [ ] La conexión a DuckDB se crea solo en `app/db.py` (lectura) y `etl/carga.py` (escritura).
- [ ] El frontend accede a la API solo desde `src/api/`.
- [ ] Los DTO del frontend reflejan los modelos de `app/modelos.py`.

## 6. Puntos abiertos

- Autenticación y límite de tasa si el servicio se expusiera. Es urgente en `test.zenixtech.ai`, que es público (ver `docs/DESPLIEGUE.md`).
- `test.zenixtech.ai` ya sirve otra aplicación: hay que decidir si se sustituye o se usa otro subdominio.
- Registro de auditoría de las preguntas y el SQL generado (sin la clave).
- Mejora de la regla de mes sin año con aclaración al usuario.
