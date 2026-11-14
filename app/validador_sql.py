"""Validador de SQL generado por el LLM (solo lectura, lista blanca de relaciones).

Principios de diseño (módulo crítico para la seguridad):

* Se analiza con el AST de sqlglot (dialecto ``duckdb``); no se confía en expresiones
  regulares ni en búsquedas de subcadenas.
* Enfoque de lista blanca donde es posible: la raíz debe ser una consulta, toda relación
  debe estar permitida o ser un CTE visible en su ámbito, y toda función "anónima"
  (desconocida para sqlglot) debe figurar en ``FUNCIONES_ANONIMAS_PERMITIDAS``.
* Lista negra para lo demás: cualquier nodo DML, DDL o de comando en cualquier punto del
  árbol (por ejemplo, un ``DELETE`` dentro de un CTE) y las funciones de tabla, de archivo
  o de entorno.
* Lo que se devuelve (y por tanto lo que se ejecuta) es el SQL regenerado desde el AST ya
  validado, sin comentarios, y no el texto original. Así se descartan las diferencias de
  interpretación entre sqlglot y DuckDB (comentarios, cadenas con escapes, etc.). Además, el
  resultado se vuelve a analizar y a validar antes de devolverlo.
* Independiente del LLM y de la base de datos: no importa ``duckdb`` ni ``openai``.

El validador es una capa más. La conexión de ejecución sigue siendo de solo lectura y sin
acceso externo (``app.db``), de modo que ninguna capa es la única barrera.

Decisiones documentadas:

* Se toleran sentencias vacías sobrantes (``SELECT 1;`` o ``SELECT 1; -- nota``), pero
  nunca dos sentencias reales.
* Un ``LIMIT`` existente se conserva si es un entero literal menor o igual que ``limite``.
  Si es mayor, ``NULL``/``ALL``, un porcentaje o una expresión, se sustituye por ``limite``
  para que el tope de filas sea siempre efectivo.
* ``WITH RECURSIVE`` se rechaza por completo: un CTE recursivo puede referirse a sí mismo y
  es difícil garantizar que el ancla solo use relaciones permitidas; estas preguntas no lo
  necesitan. Sin él, un CTE solo es visible tras su definición, nunca en su propio cuerpo.
* Ninguna función es un origen de datos: ``FROM``/``JOIN`` solo admiten relaciones,
  subconsultas, ``VALUES`` y ``LATERAL (subconsulta)``; ``UNNEST``, ``range``, ``read_csv``,
  etc. se rechazan en cualquier posición (también dentro de joins y subconsultas).
* Una cadena entre comillas simples en ``FROM`` (``FROM 'pedidos'``) es indistinguible para
  sqlglot de un identificador entrecomillado: se trata como nombre de relación y solo se
  acepta si coincide con una relación permitida (nunca se interpreta como ruta de archivo).
"""
from __future__ import annotations

from collections.abc import Iterable

import sqlglot
from sqlglot import exp

from core.esquema import LIMITE_FILAS_DEFECTO, RELACIONES_PERMITIDAS

DIALECTO = "duckdb"
ESQUEMA_PERMITIDO = "main"
LONGITUD_MAXIMA_SQL = 20_000


class SQLNoPermitidoError(Exception):
    """El SQL no es una consulta de solo lectura sobre las relaciones permitidas."""

    codigo = "sql_no_valida"

    def __init__(self, mensaje: str) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje


def _clases(*nombres: str) -> tuple[type, ...]:
    """Clases de ``sqlglot.exp`` que existan en la versión instalada (tolerante a versiones)."""
    return tuple(getattr(exp, n) for n in nombres if isinstance(getattr(exp, n, None), type))


# Raíces admitidas (tras quitar paréntesis): SELECT y operaciones de conjuntos.
_TIPOS_CONSULTA = _clases("Select", "Union", "Intersect", "Except")

# Nodos prohibidos en cualquier punto del árbol: escritura, DDL, comandos y administración.
_NODOS_PROHIBIDOS = _clases(
    "DML", "DDL", "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter",
    "AlterColumn", "AlterRename", "AlterSet", "RenameColumn", "AddConstraint", "DropPartition",
    "TruncateTable", "Command", "Pragma", "Copy", "Attach", "Detach", "Set", "SetItem", "Use",
    "Transaction", "Commit", "Rollback", "Install", "Describe", "Show", "Summarize", "Analyze",
    "Grant", "Revoke", "LoadData", "Export", "Refresh", "Cache", "Uncache", "Comment", "Kill",
    "Declare", "Execute", "ExecuteSql", "Into", "Returning", "Directory", "Put", "Get",
    "LockingStatement", "Whens",
)

# Funciones tipadas por sqlglot que no deben ejecutarse: lectura de archivos, generadores de
# series (consumo de memoria), repetición masiva, tablas JSON/XML, información del sistema.
_FUNCIONES_TIPADAS_PROHIBIDAS = _clases(
    "ReadCSV", "ReadParquet", "ToFile", "JSONTable", "XMLTable", "SplitToTable",
    "StrtokSplitToTable", "GenerateTable", "GenerateSeries", "ExplodingGenerateSeries",
    "GenerateDateArray", "GenerateTimestampArray", "GenerateBool", "GenerateDouble",
    "GenerateInt", "GenerateText", "Repeat", "AIGenerate", "GenerateEmbedding", "Host",
    "CurrentVersion", "CurrentDatabase", "CurrentCatalog", "CurrentSchema", "CurrentSchemas",
    "CurrentUser", "SessionUser", "CurrentAccount", "CurrentAccountName", "CurrentClient",
    "CurrentSession", "CurrentStatement", "CurrentTransaction", "CurrentUserId",
    "CurrentIpAddress", "CurrentRegion", "CurrentWarehouse", "CurrentRole",
)

# Funciones que sqlglot no conoce (nodo ``Anonymous``) y se aceptan por ser puras y acotadas.
# Cualquier otra función desconocida se rechaza (getenv, current_setting, read_*, glob,
# query, duckdb_*, pragma_*, range, etc.).
FUNCIONES_ANONIMAS_PERMITIDAS = frozenset({
    "age", "arbitrary", "century", "date_part", "datepart", "date_sub", "datesub", "decade",
    "entropy", "era", "fdiv", "format_bytes", "fsum", "histogram", "iff", "isnull", "isoyear",
    "list_aggr", "list_avg", "list_sum", "list_unique", "millennium", "now", "product",
    "reservoir_quantile", "round_even", "strip_accents", "strlen", "to_months",
    "try_strptime", "weekofyear", "yearweek",
})

# Lo único admitido como origen de FROM/JOIN: relaciones (ya comprobadas una a una),
# subconsultas, VALUES y LATERAL (que además debe contener una subconsulta). Cualquier
# función (UNNEST, range, read_csv...) como origen se rechaza.
_FUENTES_PERMITIDAS = _clases("Table", "Subquery", "Values", "Lateral")

_ESQUEMAS_SISTEMA = frozenset({"information_schema", "pg_catalog"})


def _rechazar(mensaje: str) -> SQLNoPermitidoError:
    return SQLNoPermitidoError(mensaje)


def _parsear(sql: object) -> exp.Expression:
    """Devuelve el AST de la única sentencia; falla cerrado ante cualquier anomalía."""
    if not isinstance(sql, str) or not sql.strip():
        raise _rechazar("El SQL está vacío.")
    if len(sql) > LONGITUD_MAXIMA_SQL:
        raise _rechazar("El SQL es demasiado largo.")
    try:
        sentencias = sqlglot.parse(sql, dialect=DIALECTO)
    except Exception as error:  # noqa: BLE001 - fallar cerrado ante cualquier error del parser
        raise _rechazar("El SQL no se pudo interpretar (error de sintaxis).") from error
    reales = [s for s in sentencias if s is not None and not isinstance(s, exp.Semicolon)]
    if not reales:
        raise _rechazar("El SQL está vacío.")
    if len(reales) > 1:
        raise _rechazar("Solo se permite una sentencia SQL.")
    return reales[0]


def _hijos(nodo: exp.Expression) -> Iterable[exp.Expression]:
    return nodo.iter_expressions()


def _comprobar_raiz(arbol: exp.Expression) -> None:
    interior = arbol
    while isinstance(interior, exp.Subquery):
        interior = interior.this
    if not isinstance(interior, _TIPOS_CONSULTA):
        raise _rechazar("Solo se permiten consultas SELECT.")


def _comprobar_nodos(arbol: exp.Expression) -> None:
    """Rechaza nodos de escritura/comando y funciones no permitidas en todo el árbol."""
    pila = [arbol]
    while pila:
        nodo = pila.pop()
        if isinstance(nodo, _NODOS_PROHIBIDOS):
            raise _rechazar(
                f"Operación no permitida ({type(nodo).__name__}): solo se permiten consultas de lectura."
            )
        if isinstance(nodo, exp.With) and nodo.args.get("recursive"):
            raise _rechazar("No se permite WITH RECURSIVE.")
        if isinstance(nodo, exp.Unnest):
            raise _rechazar("No se permiten funciones como origen de datos (UNNEST).")
        if isinstance(nodo, (exp.From, exp.Join)) and not isinstance(nodo.this, _FUENTES_PERMITIDAS):
            raise _rechazar("No se permiten funciones ni expresiones como origen de datos.")
        if isinstance(nodo, exp.Lateral) and not isinstance(nodo.this, exp.Subquery):
            raise _rechazar("LATERAL solo se admite con una subconsulta.")
        if isinstance(nodo, exp.Dot) and isinstance(nodo.expression, exp.Func):
            raise _rechazar("No se permiten funciones con nombre calificado.")
        if isinstance(nodo, exp.Anonymous):
            nombre = nodo.name.lower()
            if nombre not in FUNCIONES_ANONIMAS_PERMITIDAS:
                raise _rechazar(f"Función no permitida: {nodo.name}.")
        elif isinstance(nodo, _FUNCIONES_TIPADAS_PROHIBIDAS):
            raise _rechazar(f"Función no permitida: {nodo.sql_name().lower()}.")
        pila.extend(_hijos(nodo))


def _comprobar_tabla(tabla: exp.Table, permitidas: frozenset[str], visibles: frozenset[str]) -> None:
    if not isinstance(tabla.this, exp.Identifier):
        raise _rechazar("No se permiten funciones de tabla ni archivos como origen de datos.")
    nombre = tabla.name.lower()
    catalogo = tabla.args.get("catalog")
    esquema = tabla.args.get("db")
    if catalogo is not None:
        raise _rechazar("No se permite indicar un catálogo en las relaciones.")
    if esquema is not None:
        esquema_nombre = esquema.name.lower()
        if esquema_nombre in _ESQUEMAS_SISTEMA:
            raise _rechazar("No se permite consultar el catálogo del sistema.")
        if esquema_nombre != ESQUEMA_PERMITIDO:
            raise _rechazar(f"Esquema no permitido: {esquema.name}.")
        if nombre not in permitidas:
            raise _rechazar(f"Relación no permitida: {tabla.name}.")
        return
    if nombre.startswith("duckdb_") or nombre.startswith("pragma_"):
        raise _rechazar("No se permite consultar el catálogo del sistema.")
    if nombre not in permitidas and nombre not in visibles:
        raise _rechazar(f"Relación no permitida: {tabla.name}.")


def _comprobar_relaciones(
    nodo: exp.Expression, permitidas: frozenset[str], visibles: frozenset[str]
) -> None:
    """Recorre el árbol comprobando cada relación con el ámbito de CTE correcto."""
    clausula_with = nodo.args.get("with_") or nodo.args.get("with")
    if isinstance(clausula_with, exp.With):
        # WITH RECURSIVE está prohibido (ver _comprobar_nodos), así que un CTE nunca es
        # visible en su propio cuerpo: solo lo es para los CTE siguientes y para la
        # consulta a la que se asocia. Un nombre igual a una relación permitida solo la
        # "oculta" tras su definición; su cuerpo se valida con el ámbito anterior.
        actuales = visibles
        for cte in clausula_with.expressions:
            _comprobar_relaciones(cte.this, permitidas, actuales)
            actuales = actuales | {cte.alias.lower()}
        visibles = actuales
    if isinstance(nodo, exp.Table):
        _comprobar_tabla(nodo, permitidas, visibles)
    for hijo in _hijos(nodo):
        if hijo is clausula_with:
            continue
        _comprobar_relaciones(hijo, permitidas, visibles)


def _comprobar_arbol(arbol: exp.Expression, permitidas: frozenset[str]) -> None:
    try:
        _comprobar_raiz(arbol)
        _comprobar_nodos(arbol)
        _comprobar_relaciones(arbol, permitidas, frozenset())
    except RecursionError as error:
        raise _rechazar("El SQL es demasiado complejo.") from error


def _limite_valido(limite: exp.Expression | None, maximo: int) -> bool:
    """True si ya hay un LIMIT que es un entero literal no superior a ``maximo``."""
    if not isinstance(limite, exp.Limit):
        return False  # ausente o FETCH (se normaliza a LIMIT)
    opciones = limite.args.get("limit_options")
    if opciones is not None and (opciones.args.get("percent") or opciones.args.get("with_ties")):
        return False
    cuenta = limite.args.get("expression")
    if not isinstance(cuenta, exp.Literal) or cuenta.is_string:
        return False
    try:
        valor = int(cuenta.name)
    except ValueError:
        return False
    return 0 <= valor <= maximo


def _aplicar_limite(arbol: exp.Expression, maximo: int) -> None:
    """Garantiza un LIMIT efectivo en la consulta más externa."""
    if not _limite_valido(arbol.args.get("limit"), maximo):
        arbol.set("limit", exp.Limit(expression=exp.Literal.number(maximo)))


def validar_sql(
    sql: str,
    permitidas: Iterable[str] = RELACIONES_PERMITIDAS,
    limite: int = LIMITE_FILAS_DEFECTO,
) -> str:
    """Valida ``sql`` y devuelve la consulta segura a ejecutar (con ``LIMIT``).

    Lanza ``SQLNoPermitidoError`` si no es una única consulta de lectura sobre las
    relaciones ``permitidas`` (o CTE definidos en la propia consulta).
    """
    if isinstance(limite, bool) or not isinstance(limite, int) or limite < 1:
        raise ValueError("limite debe ser un entero positivo")
    relaciones = frozenset(nombre.lower() for nombre in permitidas)

    arbol = _parsear(sql)
    _comprobar_arbol(arbol, relaciones)
    _aplicar_limite(arbol, limite)
    salida = arbol.sql(dialect=DIALECTO, comments=False)

    # Defensa en profundidad: lo que se devuelve debe superar de nuevo la validación.
    _comprobar_arbol(_parsear(salida), relaciones)
    return salida
