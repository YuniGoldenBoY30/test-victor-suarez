"""Conexión de DuckDB de solo lectura y sin acceso externo."""
from pathlib import Path

import duckdb

from app.errores import BaseDatosNoDisponibleError


def abrir_conexion_lectura(ruta) -> duckdb.DuckDBPyConnection:
    if not Path(ruta).is_file():
        raise BaseDatosNoDisponibleError("La base de datos no está disponible.")
    try:
        return duckdb.connect(
            str(ruta), read_only=True, config={"enable_external_access": False}
        )
    except duckdb.Error as exc:
        raise BaseDatosNoDisponibleError("La base de datos no está disponible.") from exc
