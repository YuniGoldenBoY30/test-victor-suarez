from decimal import Decimal

import duckdb

from core.esquema import RUTA_VISTAS
from etl.__main__ import main
from etl.carga import cargar_duckdb
from tests.conftest import FILAS_PRUEBA


def consulta(ruta, sql):
    con = duckdb.connect(str(ruta), read_only=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_tipos_de_columnas(db_prueba):
    filas = consulta(db_prueba, "SELECT column_name, data_type FROM information_schema.columns "
                                "WHERE table_name = 'pedidos' ORDER BY ordinal_position")
    assert filas == [("fecha", "DATE"), ("cliente", "VARCHAR"), ("pais", "VARCHAR"),
                     ("producto", "VARCHAR"), ("importe", "DECIMAL(12,2)"), ("estado", "VARCHAR")]


def test_cli_si_falta_crea_y_no_toca(tmp_path):
    csv_ruta = tmp_path / "p.csv"
    csv_ruta.write_text("fecha,cliente,pais,producto,importe,estado\n"
                        "2024-01-05,Ana,España,Teclado,10.5,completado\n", encoding="utf-8")
    db = tmp_path / "x.duckdb"
    assert main(["--csv", str(csv_ruta), "--db", str(db), "--si-falta"]) == 0
    assert consulta(db, "SELECT count(*) FROM pedidos") == [(1,)]
    mtime = db.stat().st_mtime_ns
    # CSV con otra fila: si la base existe, no se reconstruye.
    csv_ruta.write_text(csv_ruta.read_text(encoding="utf-8") + "2024-01-06,Luis,España,Ratón,5,enviado\n",
                        encoding="utf-8")
    assert main(["--csv", str(csv_ruta), "--db", str(db), "--si-falta"]) == 0
    assert db.stat().st_mtime_ns == mtime
    assert consulta(db, "SELECT count(*) FROM pedidos") == [(1,)]
    # Sin --si-falta sí se reconstruye.
    assert main(["--csv", str(csv_ruta), "--db", str(db)]) == 0
    assert consulta(db, "SELECT count(*) FROM pedidos") == [(2,)]


def test_tabla_pedidos_cargada(db_prueba):
    assert consulta(db_prueba, "SELECT count(*) FROM pedidos") == [(5,)]


def test_vista_ventas_excluye_cancelado(db_prueba):
    filas = consulta(db_prueba, "SELECT mes, pais, num_pedidos, total_ventas FROM ventas_por_mes_pais ORDER BY mes, pais")
    assert [(str(m), p, n, t) for m, p, n, t in filas] == [
        ("2024-01-01", "España", 2, Decimal("150.50")),
        ("2024-02-01", "Francia", 1, Decimal("75.00")),
        ("2024-03-01", "España", 1, Decimal("20.00")),
    ]


def test_top_clientes_excluye_cancelado_y_ordena(db_prueba):
    filas = consulta(db_prueba, "SELECT cliente, num_pedidos, total_comprado FROM top_10_clientes")
    assert filas == [("Ana", 2, Decimal("150.50")), ("Marie", 1, Decimal("75.00")), ("Luis", 1, Decimal("20.00"))]


def test_top_10_limita_a_diez(tmp_path):
    filas = [dict(FILAS_PRUEBA[0], cliente=f"C{i}", importe=Decimal(i + 1)) for i in range(15)]
    ruta = tmp_path / "x.duckdb"
    cargar_duckdb(filas, ruta, RUTA_VISTAS)
    assert len(consulta(ruta, "SELECT * FROM top_10_clientes")) == 10


def test_recarga_reemplaza(tmp_path):
    ruta = tmp_path / "x.duckdb"
    cargar_duckdb(FILAS_PRUEBA, ruta, RUTA_VISTAS)
    cargar_duckdb(FILAS_PRUEBA[:1], ruta, RUTA_VISTAS)
    assert consulta(ruta, "SELECT count(*) FROM pedidos") == [(1,)]
