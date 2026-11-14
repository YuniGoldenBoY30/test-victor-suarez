"""Fixtures compartidas. db_prueba construye un DuckDB pequeño con filas conocidas."""
from datetime import date
from decimal import Decimal

import pytest

from core.esquema import RUTA_VISTAS
from etl.carga import cargar_duckdb

FILAS_PRUEBA = [
    {"fecha": date(2024, 1, 5), "cliente": "Ana", "pais": "España", "producto": "Teclado", "importe": Decimal("100.00"), "estado": "completado"},
    {"fecha": date(2024, 1, 20), "cliente": "Ana", "pais": "España", "producto": "Ratón", "importe": Decimal("50.50"), "estado": "enviado"},
    {"fecha": date(2024, 1, 21), "cliente": "Luis", "pais": "España", "producto": "Monitor", "importe": Decimal("999.00"), "estado": "cancelado"},
    {"fecha": date(2024, 2, 3), "cliente": "Marie", "pais": "Francia", "producto": "Teclado", "importe": Decimal("75.00"), "estado": "pendiente"},
    {"fecha": date(2024, 3, 9), "cliente": "Luis", "pais": "España", "producto": "Ratón", "importe": Decimal("20.00"), "estado": "completado"},
]


@pytest.fixture
def db_prueba(tmp_path):
    ruta = tmp_path / "prueba.duckdb"
    cargar_duckdb(FILAS_PRUEBA, ruta, RUTA_VISTAS)
    return ruta
