import csv
import re

from core.esquema import COLUMNAS_CSV
from scripts.generar_pedidos import FECHAS_IMPOSIBLES, generar_filas, main

PATRONES_FECHA = {
    r"^\d{4}-\d{2}-\d{2}$",
    r"^\d{2}/\d{2}/\d{4}$",
    r"^\d{2}-\d{2}-\d{4}$",
    r"^\d{4}/\d{2}/\d{2}$",
}


def test_genera_al_menos_mil_filas_con_columnas_exactas():
    filas = generar_filas(1000, 42)
    assert len(filas) >= 1000
    assert all(list(f.keys()) == COLUMNAS_CSV for f in filas)


def test_es_determinista_con_la_misma_semilla():
    assert generar_filas(1000, 7) == generar_filas(1000, 7)


def test_contiene_duplicados_exactos():
    filas = generar_filas(1000, 42)
    claves = [tuple(f.values()) for f in filas]
    assert len(claves) > len(set(claves))


def test_contiene_al_menos_cuatro_formatos_de_fecha():
    filas = generar_filas(1000, 42)
    formatos_vistos = {
        patron
        for f in filas
        for patron in PATRONES_FECHA
        if re.match(patron, f["fecha"])
    }
    assert len(formatos_vistos) >= 4


def test_contiene_fechas_imposibles():
    fechas = {f["fecha"] for f in generar_filas(1000, 42)}
    for fecha in FECHAS_IMPOSIBLES:
        assert fecha in fechas


def test_contiene_importe_vacio():
    assert any(f["importe"] == "" for f in generar_filas(1000, 42))


def test_main_escribe_csv_solo_en_la_ruta_indicada(tmp_path):
    destino = tmp_path / "pedidos.csv"
    main(destino)
    with destino.open(encoding="utf-8", newline="") as f:
        lector = csv.reader(f)
        cabecera = next(lector)
        filas = list(lector)
    assert cabecera == COLUMNAS_CSV
    assert len(filas) >= 1000
