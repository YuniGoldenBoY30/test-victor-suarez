"""Tests del validador SQL: aceptación de consultas legítimas y muchos casos de ataque."""
import ast
import logging
from pathlib import Path

import pytest
import sqlglot
from sqlglot import exp

from app.validador_sql import SQLNoPermitidoError, validar_sql
from core.esquema import LIMITE_FILAS_DEFECTO, RELACIONES_PERMITIDAS

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _silenciar_sqlglot():
    """sqlglot avisa por log cuando cae al modo 'Command'; es ruido esperado en estos tests."""
    logger = logging.getLogger("sqlglot")
    nivel = logger.level
    logger.setLevel(logging.CRITICAL)
    yield
    logger.setLevel(nivel)


def _sentencias(sql: str) -> list:
    return [s for s in sqlglot.parse(sql, dialect="duckdb") if s is not None and not isinstance(s, exp.Semicolon)]


# --------------------------------------------------------------------------- aceptadas

ACEPTADAS = [
    "SELECT * FROM pedidos",
    "select * from PEDIDOS",
    "SELECT * FROM pedidos;",
    "SELECT * FROM pedidos; -- nota final",
    "SELECT * FROM main.pedidos",
    "SELECT * FROM ventas_por_mes_pais",
    "SELECT * FROM top_10_clientes",
    'SELECT * FROM "pedidos"',
    "SELECT pais, SUM(importe) AS total FROM pedidos GROUP BY pais ORDER BY total DESC",
    "SELECT pais, SUM(importe) FROM pedidos WHERE estado <> 'cancelado' GROUP BY ALL",
    "SELECT strftime(fecha, '%Y-%m') AS mes, COUNT(*) FROM pedidos GROUP BY 1 ORDER BY 1",
    "SELECT date_trunc('month', fecha) AS mes, round(avg(importe), 2) FROM pedidos GROUP BY 1",
    "SELECT year(fecha), month(fecha), median(importe) FROM pedidos GROUP BY 1, 2",
    "SELECT cliente, rank() OVER (PARTITION BY pais ORDER BY importe DESC) FROM pedidos",
    "SELECT now(), current_date, age(fecha) FROM pedidos",
    "SELECT p.cliente, v.total_ventas FROM pedidos p JOIN ventas_por_mes_pais v ON p.pais = v.pais",
    "SELECT * FROM pedidos WHERE cliente IN (SELECT cliente FROM top_10_clientes)",
    "SELECT * FROM (SELECT pais, SUM(importe) AS t FROM pedidos GROUP BY pais) s WHERE t > 10",
    "SELECT pais FROM pedidos UNION SELECT pais FROM ventas_por_mes_pais",
    "SELECT cliente FROM pedidos INTERSECT SELECT cliente FROM top_10_clientes",
    "SELECT cliente FROM pedidos EXCEPT SELECT cliente FROM top_10_clientes",
    "WITH v AS (SELECT * FROM ventas_por_mes_pais) SELECT * FROM v",
    "WITH a AS (SELECT pais FROM pedidos), b AS (SELECT pais FROM a) SELECT * FROM b",
    "SELECT * FROM pedidos p, LATERAL (SELECT 1 AS x) l",
    "SELECT unnest(list(cliente)) FROM pedidos",
    "WITH pedidos AS (SELECT * FROM pedidos WHERE estado = 'completado') SELECT * FROM pedidos",
    "WITH a AS (SELECT 1 AS x) SELECT x FROM a UNION SELECT 2",
    "(SELECT * FROM pedidos)",
    "SELECT * FROM pedidos TABLESAMPLE 10 PERCENT",
    "SELECT * FROM (VALUES (1), (2)) AS v(x)",
    "SELECT 1",
    "SELECT * FROM pedidos -- ; DROP TABLE pedidos",
    "SELECT * FROM pedidos /* ; DROP TABLE pedidos */",
]


@pytest.mark.parametrize("sql", ACEPTADAS)
def test_acepta_consultas_legitimas(sql):
    salida = validar_sql(sql)
    assert isinstance(salida, str)
    assert len(_sentencias(salida)) == 1
    assert ";" not in salida
    assert "--" not in salida and "/*" not in salida  # los comentarios no sobreviven
    assert "LIMIT" in salida.upper()
    # Idempotente: lo devuelto vuelve a superar la validación sin cambios.
    assert validar_sql(salida) == salida


# --------------------------------------------------------------------------- LIMIT


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM pedidos",
        "SELECT * FROM pedidos ORDER BY fecha",
        "SELECT pais, SUM(importe) FROM pedidos GROUP BY pais",
        "SELECT * FROM pedidos UNION ALL SELECT * FROM pedidos",
        "WITH a AS (SELECT * FROM pedidos) SELECT * FROM a",
        "(SELECT * FROM pedidos)",
    ],
)
def test_anade_limit_si_falta(sql):
    salida = validar_sql(sql)
    assert salida.endswith(f"LIMIT {LIMITE_FILAS_DEFECTO}")
    assert salida.upper().count("LIMIT") == 1


def test_limit_se_anade_solo_a_la_consulta_mas_externa():
    salida = validar_sql("SELECT * FROM (SELECT * FROM pedidos) s")
    assert salida.upper().count("LIMIT") == 1
    assert salida.endswith(f"LIMIT {LIMITE_FILAS_DEFECTO}")


def test_conserva_limit_existente_menor():
    assert validar_sql("SELECT * FROM pedidos LIMIT 5") == "SELECT * FROM pedidos LIMIT 5"
    assert validar_sql("select * from pedidos limit 5 offset 2") == "SELECT * FROM pedidos LIMIT 5 OFFSET 2"
    assert validar_sql("SELECT * FROM pedidos LIMIT 1000").endswith("LIMIT 1000")


def test_limit_de_union_se_conserva():
    salida = validar_sql("SELECT pais FROM pedidos UNION SELECT pais FROM pedidos LIMIT 3")
    assert salida.endswith("LIMIT 3")
    assert salida.upper().count("LIMIT") == 1


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM pedidos LIMIT 5000",
        "SELECT * FROM pedidos LIMIT 1001",
        "SELECT * FROM pedidos LIMIT ALL",
        "SELECT * FROM pedidos LIMIT NULL",
        "SELECT * FROM pedidos LIMIT 10%",
        "SELECT * FROM pedidos LIMIT -1",
        "SELECT * FROM pedidos LIMIT 1 + 5000",
        "SELECT * FROM pedidos FETCH FIRST 5000 ROWS ONLY",
    ],
)
def test_limit_excesivo_o_no_literal_se_acota(sql):
    salida = validar_sql(sql)
    assert salida.endswith(f"LIMIT {LIMITE_FILAS_DEFECTO}")
    assert salida.upper().count("LIMIT") == 1


def test_limite_personalizado():
    assert validar_sql("SELECT * FROM pedidos", limite=10) == "SELECT * FROM pedidos LIMIT 10"
    assert validar_sql("SELECT * FROM pedidos LIMIT 50", limite=10) == "SELECT * FROM pedidos LIMIT 10"


@pytest.mark.parametrize("limite", [0, -3, 1.5, "10", None, True])
def test_limite_invalido_es_error_de_programacion(limite):
    with pytest.raises(ValueError):
        validar_sql("SELECT * FROM pedidos", limite=limite)


# --------------------------------------------------------------------------- rechazadas

VACIAS_O_BASURA = [
    "",
    "   ",
    "\n\t",
    ";",
    "-- solo un comentario",
    "/* solo un comentario */",
    "hola mundo",
    "esto no es sql",
    "SELECT",
    "SELECT * FROM",
    "SELECT * FROM pedidos WHERE",
    "SELECT * FROM pedidos WHERE /* comentario sin cerrar",
    "SELECT 'cadena sin cerrar FROM pedidos",
    "SELECT * FROM pedidos)",
    "((((",
    "\x00",
    "SELECT * FROM pedidos\x00; DROP TABLE pedidos",
]

VARIAS_SENTENCIAS = [
    "SELECT 1; DROP TABLE pedidos",
    "SELECT * FROM pedidos; SELECT * FROM pedidos",
    "SELECT * FROM pedidos;SELECT 1",
    "SELECT * FROM pedidos; -- x\nDROP TABLE pedidos",
    "SELECT * FROM pedidos /* x */; DELETE FROM pedidos",
    "SELECT * FROM pedidos;\n\nINSERT INTO pedidos VALUES (1)",
    "SELECT 'a'; ATTACH 'otra.db'",
    "SELECT 'a\\'; DROP TABLE pedidos; --'",
    "SELECT 1 -- x\n; DROP TABLE pedidos",
    "SELECT 1 /* /* anidado */ */; DROP TABLE pedidos",
]

NO_ES_SELECT = [
    "INSERT INTO pedidos VALUES (DATE '2024-01-01', 'a', 'España', 'p', 1, 'enviado')",
    "INSERT INTO pedidos SELECT * FROM pedidos",
    "UPDATE pedidos SET importe = 0",
    "DELETE FROM pedidos",
    "DELETE FROM pedidos WHERE 1=1",
    "MERGE INTO pedidos USING pedidos AS o ON 1=1 WHEN MATCHED THEN DELETE",
    "DROP TABLE pedidos",
    "DROP VIEW top_10_clientes",
    "CREATE TABLE x AS SELECT * FROM pedidos",
    "CREATE OR REPLACE VIEW top_10_clientes AS SELECT 1",
    "CREATE MACRO m() AS 1",
    "ALTER TABLE pedidos ADD COLUMN x INT",
    "ALTER TABLE pedidos RENAME TO otra",
    "TRUNCATE TABLE pedidos",
    "ATTACH 'otra.db' AS o",
    "ATTACH ':memory:'",
    "DETACH o",
    "COPY pedidos TO 'salida.csv'",
    "COPY (SELECT * FROM pedidos) TO 'salida.csv'",
    "COPY pedidos FROM 'entrada.csv'",
    "EXPORT DATABASE 'directorio'",
    "IMPORT DATABASE 'directorio'",
    "PRAGMA database_list",
    "PRAGMA table_info('pedidos')",
    "PRAGMA enable_external_access = true",
    "SET enable_external_access = true",
    "SET threads = 1",
    "RESET threads",
    "USE otra",
    "INSTALL httpfs",
    "LOAD httpfs",
    "CALL pragma_version()",
    "CALL duckdb_tables()",
    "BEGIN",
    "BEGIN TRANSACTION",
    "COMMIT",
    "ROLLBACK",
    "CHECKPOINT",
    "VACUUM",
    "ANALYZE",
    "EXPLAIN SELECT * FROM pedidos",
    "EXPLAIN ANALYZE SELECT * FROM pedidos",
    "DESCRIBE pedidos",
    "SHOW TABLES",
    "SHOW ALL TABLES",
    "SUMMARIZE pedidos",
    "PIVOT pedidos ON pais USING sum(importe)",
    "UNPIVOT pedidos ON importe INTO NAME k VALUE v",
    "VALUES (1)",
    "PREPARE p AS SELECT * FROM pedidos",
    "EXECUTE p",
    "GRANT ALL ON pedidos TO x",
    "COMMENT ON TABLE pedidos IS 'x'",
    "SELECT * FROM pedidos INTO otra",
]

ESCRITURA_ANIDADA = [
    "WITH x AS (DELETE FROM pedidos RETURNING *) SELECT * FROM x",
    "WITH x AS (INSERT INTO pedidos VALUES (1) RETURNING *) SELECT * FROM x",
    "WITH x AS (UPDATE pedidos SET importe = 0 RETURNING *) SELECT * FROM x",
    "WITH x AS (SELECT 1) DELETE FROM pedidos",
    "WITH x AS (SELECT 1) INSERT INTO pedidos SELECT * FROM pedidos",
    "WITH x AS (SELECT 1) UPDATE pedidos SET importe = 0",
    "WITH x AS (SELECT 1) CREATE TABLE y AS SELECT * FROM x",
    "SELECT * FROM (DELETE FROM pedidos RETURNING *) t",
    "SELECT * FROM pedidos WHERE EXISTS (DELETE FROM pedidos RETURNING 1)",
    "SELECT * FROM pedidos UNION ALL (DROP TABLE pedidos)",
]

FUNCIONES_DE_ARCHIVO_O_TABLA = [
    "SELECT * FROM read_csv('datos.csv')",
    "SELECT * FROM read_csv_auto('datos.csv')",
    "SELECT * FROM READ_CSV('datos.csv')",
    "SELECT * FROM read_parquet('datos.parquet')",
    "SELECT * FROM read_json('datos.json')",
    "SELECT * FROM read_json_auto('datos.json')",
    "SELECT * FROM read_ndjson('datos.json')",
    "SELECT * FROM read_text('.env')",
    "SELECT * FROM read_blob('.env')",
    "SELECT read_text('.env')",
    "SELECT content FROM read_text('.env')",
    "SELECT * FROM glob('*')",
    "SELECT * FROM glob('C:/*')",
    "SELECT * FROM query('SELECT * FROM secreta')",
    "SELECT * FROM query_table('secreta')",
    "SELECT * FROM sniff_csv('datos.csv')",
    "SELECT * FROM parquet_scan('datos.parquet')",
    "SELECT * FROM parquet_metadata('datos.parquet')",
    "SELECT * FROM iceberg_scan('x')",
    "SELECT * FROM range(10)",
    "SELECT * FROM generate_series(1, 10)",
    "SELECT range(100000000000)",
    "SELECT generate_series(1, 100000000000)",
    "SELECT repeat('a', 1000000000)",
    "SELECT * FROM pedidos, read_csv('x')",
    "SELECT * FROM pedidos p, LATERAL read_csv('x')",
    "SELECT * FROM pedidos JOIN read_csv('x') ON 1 = 1",
    "SELECT * FROM (SELECT * FROM read_csv('x')) t",
    "SELECT * FROM pedidos WHERE cliente IN (SELECT column0 FROM read_csv('x'))",
    "WITH a AS (SELECT * FROM read_csv('x')) SELECT * FROM a",
    "SELECT * FROM pedidos UNION ALL SELECT * FROM read_csv('x')",
    "SELECT * FROM main.read_csv('x')",
    "SELECT main.read_text('x')",
    "SELECT pg_catalog.version()",
    "SELECT * FROM my_table_macro()",
    "SELECT * FROM unnest((SELECT list(column0) FROM read_csv('x')))",
]

FUNCIONES_DE_ENTORNO_O_SISTEMA = [
    "SELECT getenv('API_IA_NVIDIA')",
    "SELECT GETENV('API_IA_NVIDIA') FROM pedidos",
    "SELECT current_setting('home_directory')",
    "SELECT getvariable('x')",
    "SELECT version()",
    "SELECT current_database()",
    "SELECT current_schema()",
    "SELECT error('boom')",
    "SELECT * FROM pedidos WHERE importe > (SELECT getenv('X')::INT)",
    "SELECT pais, getenv('X') FROM pedidos GROUP BY ALL",
    "SELECT txid_current()",
]

CATALOGO_Y_ESQUEMAS = [
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM INFORMATION_SCHEMA.columns",
    "SELECT * FROM information_schema.schemata",
    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'",
    "SELECT * FROM duckdb_tables()",
    "SELECT * FROM duckdb_tables",
    "SELECT * FROM duckdb_columns()",
    "SELECT * FROM duckdb_settings()",
    "SELECT * FROM duckdb_extensions()",
    "SELECT * FROM duckdb_views",
    "SELECT * FROM pragma_database_list()",
    "SELECT * FROM pragma_table_info('pedidos')",
    "SELECT * FROM pg_catalog.pg_tables",
    "SELECT * FROM sqlite_master",
    "SELECT * FROM system.main.duckdb_tables",
    "SELECT * FROM temp.pedidos",
    "SELECT * FROM otro.pedidos",
    "SELECT * FROM public.pedidos",
    "SELECT * FROM memory.main.pedidos",
    "SELECT * FROM mi_catalogo.main.pedidos",
    "SELECT * FROM main.otra_tabla",
    "SELECT * FROM main.duckdb_tables",
]

RELACIONES_NO_PERMITIDAS = [
    "SELECT * FROM usuarios",
    "SELECT * FROM secreta",
    "SELECT * FROM pedidos_copia",
    "SELECT * FROM pedidos2",
    'SELECT * FROM "pedidos "',
    'SELECT * FROM "pedidos.csv"',
    "SELECT * FROM 'pedidos.csv'",
    "SELECT * FROM 'datos.parquet'",
    "SELECT * FROM '/etc/passwd'",
    "SELECT * FROM 'C:/datos/x.csv'",
    "SELECT * FROM 'https://example.com/x.csv'",
    "SELECT * FROM pedidos p JOIN secreta s ON p.cliente = s.cliente",
    "SELECT * FROM pedidos, secreta",
    "SELECT * FROM pedidos CROSS JOIN secreta",
    "SELECT * FROM pedidos NATURAL JOIN secreta",
    "SELECT * FROM pedidos UNION SELECT * FROM secreta",
    "SELECT * FROM pedidos UNION ALL SELECT * FROM pedidos UNION ALL SELECT * FROM secreta",
    "SELECT * FROM pedidos INTERSECT SELECT * FROM secreta",
    "SELECT * FROM pedidos EXCEPT SELECT * FROM secreta",
    "SELECT * FROM (SELECT * FROM secreta) t",
    "SELECT * FROM (SELECT * FROM (SELECT * FROM secreta) a) b",
    "SELECT (SELECT COUNT(*) FROM secreta) FROM pedidos",
    "SELECT * FROM pedidos WHERE cliente IN (SELECT cliente FROM secreta)",
    "SELECT * FROM pedidos WHERE EXISTS (SELECT 1 FROM secreta)",
    "SELECT * FROM pedidos WHERE importe > ALL (SELECT importe FROM secreta)",
    "SELECT * FROM pedidos p, LATERAL (SELECT * FROM secreta) s",
    "SELECT * FROM unnest((SELECT list(cliente) FROM secreta))",
    "WITH a AS (SELECT * FROM secreta) SELECT * FROM a",
    "WITH a AS (SELECT * FROM pedidos), b AS (SELECT * FROM secreta) SELECT * FROM a",
    "WITH a AS (SELECT * FROM pedidos) SELECT * FROM a UNION SELECT * FROM secreta",
    "WITH a AS (SELECT 1) SELECT * FROM b",
    "WITH a AS (SELECT * FROM a) SELECT * FROM a",  # un CTE no recursivo no se ve a sí mismo
    "WITH a AS (SELECT * FROM b), b AS (SELECT 1) SELECT * FROM a",  # CTE definido después
    "SELECT * FROM (WITH a AS (SELECT 1) SELECT * FROM a) t, a",  # CTE fuera de su ámbito
    "SELECT * FROM pedidos WHERE cliente IN (WITH a AS (SELECT 1) SELECT * FROM a) AND EXISTS (SELECT 1 FROM a)",
    "WITH a AS (SELECT 1) SELECT * FROM main.a",  # un CTE no admite calificador de esquema
    "WITH a AS (SELECT 1) SELECT * FROM otro.a",
]

# Regresión P1: WITH RECURSIVE se rechaza y un CTE nunca es visible en su propio cuerpo.
CTE_AUTORREFERENTES = [
    "WITH RECURSIVE secreta AS (SELECT * FROM secreta) SELECT * FROM secreta",
    "WITH RECURSIVE sqlite_master AS (SELECT * FROM sqlite_master) SELECT * FROM sqlite_master",
    "WITH RECURSIVE a AS (SELECT * FROM pedidos UNION ALL SELECT * FROM a) SELECT * FROM a",
    "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 5) SELECT * FROM n",
    "WITH recursive a AS (SELECT 1) SELECT * FROM a",
    "SELECT * FROM (WITH RECURSIVE a AS (SELECT 1) SELECT * FROM a) t",
    "SELECT * FROM pedidos WHERE cliente IN (WITH RECURSIVE a AS (SELECT 1) SELECT * FROM a)",
    "WITH secreta AS (SELECT * FROM secreta) SELECT * FROM secreta",
    "WITH sqlite_master AS (SELECT * FROM sqlite_master) SELECT * FROM sqlite_master",
    "WITH information_schema AS (SELECT 1) SELECT * FROM information_schema.tables",
    "WITH duckdb_tables AS (SELECT 1) SELECT * FROM duckdb_tables",
    # CTE que oculta una relación permitida: el cuerpo se sigue validando.
    "WITH pedidos AS (SELECT * FROM secreta) SELECT * FROM pedidos",
    "WITH pedidos AS (SELECT * FROM pedidos), x AS (SELECT * FROM secreta) SELECT * FROM x",
    "WITH top_10_clientes AS (SELECT * FROM sqlite_master) SELECT * FROM top_10_clientes",
    "WITH pedidos AS (SELECT * FROM pedidos UNION SELECT * FROM secreta) SELECT * FROM pedidos",
    # CTE que se refiere a otro definido después (no es visible todavía).
    "WITH a AS (SELECT * FROM b), b AS (SELECT * FROM pedidos) SELECT * FROM a",
    "WITH a AS (SELECT * FROM a2), a2 AS (SELECT 1) SELECT * FROM a",
    # El nombre de un CTE no se propaga fuera de su ámbito.
    "SELECT * FROM (WITH secreta AS (SELECT 1) SELECT * FROM secreta) t, secreta",
]

# Regresión P2: ninguna función puede ser origen de FROM/JOIN (UNNEST incluido).
FUNCIONES_COMO_ORIGEN = [
    "SELECT * FROM UNNEST([1, 2]) t(x)",
    "SELECT * FROM unnest([1, 2])",
    "SELECT * FROM unnest(['a']) AS t",
    "SELECT * FROM pedidos, UNNEST([1, 2]) t(x)",
    "SELECT * FROM pedidos JOIN UNNEST([1, 2]) t(x) ON 1 = 1",
    "SELECT * FROM pedidos CROSS JOIN UNNEST([1, 2]) t(x)",
    "SELECT * FROM pedidos LEFT JOIN UNNEST([1, 2]) t(x) ON TRUE",
    "SELECT * FROM pedidos, LATERAL UNNEST([1, 2]) t(x)",
    "SELECT * FROM pedidos, LATERAL unnest(list(importe))",
    "SELECT * FROM pedidos CROSS JOIN LATERAL UNNEST([1])",
    "SELECT * FROM pedidos, LATERAL read_csv('x')",
    "SELECT * FROM pedidos, LATERAL range(3)",
    "SELECT * FROM (SELECT * FROM UNNEST([1])) t",
    "SELECT * FROM pedidos CROSS JOIN LATERAL (SELECT * FROM unnest([1])) l",
    "SELECT * FROM pedidos WHERE importe IN (SELECT x FROM UNNEST([1]) t(x))",
    "SELECT (SELECT max(x) FROM unnest([1]) t(x)) FROM pedidos",
    "WITH a AS (SELECT * FROM UNNEST([1])) SELECT * FROM a",
    "SELECT * FROM pedidos UNION ALL SELECT * FROM UNNEST([1])",
    "SELECT * FROM pedidos, json_each('x')",
    "SELECT * FROM pedidos, generate_series(1, 2)",
    "SELECT * FROM pedidos p, p.items",
]

SQL_PARAMETRIZADO_PELIGROSO = [
    "SELECT * FROM pedidos WHERE cliente = ?; DROP TABLE pedidos",
    "SELECT * FROM pedidos WHERE importe > 1 UNION SELECT * FROM duckdb_tables()",
    "SELECT * FROM pedidos WHERE 1=1 OR (SELECT getenv('X')) = 'a'",
]


def _rechaza(sql):
    with pytest.raises(SQLNoPermitidoError):
        validar_sql(sql)


@pytest.mark.parametrize("sql", VACIAS_O_BASURA)
def test_rechaza_vacio_basura_o_sintaxis_invalida(sql):
    _rechaza(sql)


@pytest.mark.parametrize("sql", VARIAS_SENTENCIAS)
def test_rechaza_varias_sentencias(sql):
    _rechaza(sql)


@pytest.mark.parametrize("sql", NO_ES_SELECT)
def test_rechaza_lo_que_no_es_un_select(sql):
    _rechaza(sql)


@pytest.mark.parametrize("sql", ESCRITURA_ANIDADA)
def test_rechaza_escritura_dentro_de_cte_o_subconsulta(sql):
    _rechaza(sql)


@pytest.mark.parametrize("sql", FUNCIONES_DE_ARCHIVO_O_TABLA)
def test_rechaza_funciones_de_archivo_y_de_tabla(sql):
    _rechaza(sql)


@pytest.mark.parametrize("sql", FUNCIONES_DE_ENTORNO_O_SISTEMA)
def test_rechaza_funciones_de_entorno_y_sistema(sql):
    _rechaza(sql)


@pytest.mark.parametrize("sql", CATALOGO_Y_ESQUEMAS)
def test_rechaza_catalogo_del_sistema_y_otros_esquemas(sql):
    _rechaza(sql)


@pytest.mark.parametrize("sql", RELACIONES_NO_PERMITIDAS)
def test_rechaza_relaciones_no_permitidas_en_cualquier_posicion(sql):
    _rechaza(sql)


@pytest.mark.parametrize("sql", CTE_AUTORREFERENTES)
def test_rechaza_cte_recursivos_y_autorreferentes(sql):
    _rechaza(sql)


@pytest.mark.parametrize("sql", FUNCIONES_COMO_ORIGEN)
def test_rechaza_funciones_como_origen_de_from(sql):
    _rechaza(sql)


@pytest.mark.parametrize("sql", SQL_PARAMETRIZADO_PELIGROSO)
def test_rechaza_combinaciones_peligrosas(sql):
    _rechaza(sql)


# --------------------------------------------------------------------------- propiedades


def test_error_expone_mensaje_y_codigo():
    with pytest.raises(SQLNoPermitidoError) as info:
        validar_sql("DROP TABLE pedidos")
    assert info.value.mensaje
    assert str(info.value) == info.value.mensaje
    assert info.value.codigo == "sql_no_valida"


@pytest.mark.parametrize("entrada", [None, 123, b"SELECT 1", ["SELECT 1"], object()])
def test_rechaza_entradas_que_no_son_texto(entrada):
    _rechaza(entrada)


def test_rechaza_sql_demasiado_largo():
    _rechaza("SELECT 1 " + "-- " + "x" * 30_000)
    _rechaza("SELECT " + ", ".join(["1"] * 20_000))


def test_rechaza_anidamiento_extremo_sin_romper():
    _rechaza("SELECT " + "(" * 3000 + "1" + ")" * 3000)
    _rechaza("SELECT * FROM " + "(SELECT * FROM " * 1500 + "pedidos" + ") t" * 1500)


def test_relaciones_permitidas_son_parametrizables():
    assert validar_sql("SELECT * FROM otra", permitidas={"otra"}).startswith("SELECT * FROM otra")
    with pytest.raises(SQLNoPermitidoError):
        validar_sql("SELECT * FROM pedidos", permitidas={"otra"})
    # La comparación no distingue mayúsculas (DuckDB tampoco).
    assert validar_sql("SELECT * FROM PEDIDOS", permitidas=["Pedidos"])
    with pytest.raises(SQLNoPermitidoError):
        validar_sql("SELECT * FROM pedidos", permitidas=[])


def test_por_defecto_usa_la_lista_blanca_compartida():
    for relacion in RELACIONES_PERMITIDAS:
        assert validar_sql(f"SELECT * FROM {relacion}")
    assert RELACIONES_PERMITIDAS == {"pedidos", "ventas_por_mes_pais", "top_10_clientes"}


def test_los_comentarios_nunca_llegan_al_resultado():
    salida = validar_sql("SELECT /* a */ * FROM pedidos -- ; DROP TABLE pedidos\n")
    assert salida == f"SELECT * FROM pedidos LIMIT {LIMITE_FILAS_DEFECTO}"
    salida = validar_sql("SELECT 1 /* /* anidado */ ; DROP TABLE pedidos; /* */ */")
    assert "DROP" not in salida.upper()
    assert salida == f"SELECT 1 LIMIT {LIMITE_FILAS_DEFECTO}"


def test_cadena_con_punto_y_coma_o_palabras_peligrosas_es_valida():
    salida = validar_sql("SELECT * FROM pedidos WHERE producto = 'a; DROP TABLE pedidos; --'")
    assert len(_sentencias(salida)) == 1
    assert "'a; DROP TABLE pedidos; --'" in salida


def test_comillas_simples_en_from_no_se_tratan_como_ruta():
    salida = validar_sql("SELECT * FROM 'pedidos'")
    assert salida == f'SELECT * FROM "pedidos" LIMIT {LIMITE_FILAS_DEFECTO}'


def test_cte_visible_en_su_ambito_y_en_los_siguientes():
    validar_sql("WITH a AS (SELECT 1 AS x), b AS (SELECT x FROM a) SELECT * FROM b")
    validar_sql("SELECT * FROM (WITH a AS (SELECT 1 AS x) SELECT * FROM a) t")
    validar_sql("SELECT * FROM pedidos WHERE importe IN (WITH a AS (SELECT 1) SELECT * FROM a)")


@pytest.mark.parametrize("sql", ACEPTADAS)
def test_lo_devuelto_nunca_cambia_las_relaciones_usadas(sql):
    entrada = sqlglot.parse_one(sql, dialect="duckdb")
    salida = sqlglot.parse_one(validar_sql(sql), dialect="duckdb")
    nombres = lambda arbol: sorted(t.name.lower() for t in arbol.find_all(exp.Table))  # noqa: E731
    assert nombres(entrada) == nombres(salida)


# --------------------------------------------------------------------------- independencia


def test_el_modulo_no_importa_duckdb_ni_el_cliente_llm():
    fuente = (RAIZ / "app" / "validador_sql.py").read_text(encoding="utf-8")
    importados = set()
    for nodo in ast.walk(ast.parse(fuente)):
        if isinstance(nodo, ast.Import):
            importados.update(alias.name.split(".")[0] for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom):
            importados.add((nodo.module or "").split(".")[0])
    assert not importados & {"duckdb", "openai", "httpx", "fastapi"}
    assert "app" not in importados  # tampoco depende de app.llm ni de otros módulos de app


# --------------------------------------------------------------------------- ejecución real


def test_cte_recursivo_no_permite_leer_una_tabla_no_permitida_en_duckdb():
    """Prueba de extremo a extremo: la tabla ``secreta`` existe y era legible por el ataque."""
    duckdb = pytest.importorskip("duckdb")
    con = duckdb.connect(":memory:")
    try:
        con.execute("CREATE TABLE pedidos(cliente VARCHAR)")
        con.execute("CREATE TABLE secreta(clave VARCHAR)")
        con.execute("INSERT INTO secreta VALUES ('valor-secreto')")
        ataques = [
            "WITH RECURSIVE secreta AS (SELECT * FROM secreta) SELECT * FROM secreta",
            "WITH secreta AS (SELECT * FROM secreta) SELECT * FROM secreta",
            "WITH pedidos AS (SELECT * FROM secreta) SELECT * FROM pedidos",
        ]
        for ataque in ataques:
            # Sin validador, DuckDB lee la tabla (o la ataca de forma equivalente)...
            try:
                filas = con.execute(ataque).fetchall()
            except duckdb.Error:
                filas = None
            if "RECURSIVE" in ataque or "pedidos AS" in ataque:
                assert filas == [("valor-secreto",)], ataque
            # ...y con el validador nunca llega a ejecutarse.
            with pytest.raises(SQLNoPermitidoError):
                validar_sql(ataque)
        # Un CTE legítimo sobre una relación permitida sigue funcionando.
        sql = validar_sql("WITH pedidos AS (SELECT * FROM pedidos) SELECT * FROM pedidos")
        assert con.execute(sql).fetchall() == []
    finally:
        con.close()


def test_unnest_como_origen_no_se_ejecuta_pero_el_escalar_si():
    duckdb = pytest.importorskip("duckdb")
    con = duckdb.connect(":memory:")
    try:
        con.execute("CREATE TABLE pedidos(cliente VARCHAR)")
        con.execute("INSERT INTO pedidos VALUES ('a'), ('b')")
        assert con.execute("SELECT * FROM UNNEST([1, 2]) t(x)").fetchall() == [(1,), (2,)]
        _rechaza("SELECT * FROM UNNEST([1, 2]) t(x)")
        _rechaza("SELECT * FROM pedidos, LATERAL UNNEST([1, 2]) t(x)")
        sql = validar_sql("SELECT unnest(list(cliente)) FROM pedidos")
        assert sorted(con.execute(sql).fetchall()) == [("a",), ("b",)]
    finally:
        con.close()


def test_el_sql_devuelto_se_ejecuta_en_duckdb_y_respeta_el_limite():
    duckdb = pytest.importorskip("duckdb")
    con = duckdb.connect(":memory:")
    try:
        con.execute(
            "CREATE TABLE pedidos(fecha DATE, cliente VARCHAR, pais VARCHAR, producto VARCHAR, "
            "importe DECIMAL(12,2), estado VARCHAR)"
        )
        con.execute(
            "INSERT INTO pedidos SELECT DATE '2024-01-01' + CAST(i % 300 AS INTEGER), 'c' || (i % 7), "
            "'España', 'p', i, 'completado' FROM range(3000) t(i)"
        )
        con.execute(
            "CREATE VIEW ventas_por_mes_pais AS SELECT date_trunc('month', fecha) AS mes, pais, "
            "COUNT(*) AS num_pedidos, SUM(importe) AS total_ventas FROM pedidos GROUP BY 1, 2"
        )
        con.execute(
            "CREATE VIEW top_10_clientes AS SELECT cliente, COUNT(*) AS num_pedidos, "
            "SUM(importe) AS total_comprado FROM pedidos GROUP BY 1 ORDER BY 3 DESC LIMIT 10"
        )
        for sql in ACEPTADAS:
            # count(*) evita materializar tipos que requieren pytz (now() devuelve timestamptz).
            total = con.execute(f"SELECT count(*) FROM ({validar_sql(sql)}) t").fetchone()[0]
            assert total <= LIMITE_FILAS_DEFECTO
        assert len(con.execute(validar_sql("SELECT * FROM pedidos")).fetchall()) == LIMITE_FILAS_DEFECTO
        assert len(con.execute(validar_sql("SELECT * FROM pedidos LIMIT 5")).fetchall()) == 5
        assert len(con.execute(validar_sql("SELECT * FROM pedidos LIMIT 999999")).fetchall()) == 1000
        assert len(con.execute(validar_sql("SELECT * FROM pedidos LIMIT ALL")).fetchall()) == 1000
        # La consulta con CTE que se llama igual que la tabla también se ejecuta.
        sql_cte = "WITH pedidos AS (SELECT * FROM pedidos WHERE estado = 'completado') SELECT * FROM pedidos"
        assert len(con.execute(validar_sql(sql_cte)).fetchall()) == LIMITE_FILAS_DEFECTO
    finally:
        con.close()
