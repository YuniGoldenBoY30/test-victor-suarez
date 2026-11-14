"""Carga de pedidos limpios en DuckDB y creación de las vistas."""
from pathlib import Path

import duckdb

from core.esquema import COLUMNAS_CSV, RUTA_VISTAS


def cargar_duckdb(filas, db_path, ruta_vistas=RUTA_VISTAS) -> int:
    """Reemplaza la tabla pedidos y ejecuta el SQL de vistas. Devuelve filas cargadas."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    sql_vistas = Path(ruta_vistas).read_text(encoding="utf-8")
    filas = list(filas)
    con = duckdb.connect(str(db_path))
    try:
        con.execute("DROP VIEW IF EXISTS ventas_por_mes_pais")
        con.execute("DROP VIEW IF EXISTS top_10_clientes")
        con.execute("DROP TABLE IF EXISTS pedidos")
        con.execute(
            "CREATE TABLE pedidos(fecha DATE, cliente VARCHAR, pais VARCHAR, "
            "producto VARCHAR, importe DECIMAL(12,2), estado VARCHAR)"
        )
        if filas:
            con.executemany(
                "INSERT INTO pedidos VALUES (?, ?, ?, ?, ?, ?)",
                [[f[c] for c in COLUMNAS_CSV] for f in filas],
            )
        con.execute(sql_vistas)
    finally:
        con.close()
    return len(filas)
