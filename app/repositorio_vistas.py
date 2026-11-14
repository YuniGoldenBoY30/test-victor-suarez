"""Acceso a las vistas del dashboard con SQL fijo y parametrizado."""
from collections.abc import Callable

import duckdb

from app.errores import ErrorEjecucionSQL
from app.servicio import a_json

_SQL_VENTAS = "SELECT mes, pais, num_pedidos, total_ventas FROM ventas_por_mes_pais"
_SQL_TOP = (
    "SELECT cliente, num_pedidos, total_comprado FROM top_10_clientes "
    "ORDER BY total_comprado DESC"
)


class RepositorioVistas:
    def __init__(self, abrir_conexion: Callable[[], duckdb.DuckDBPyConnection]) -> None:
        self._abrir = abrir_conexion

    def _ejecutar(self, sql: str, parametros: list | None = None) -> list[dict]:
        conexion = self._abrir()
        try:
            try:
                cursor = conexion.execute(sql, parametros or [])
                nombres = [d[0] for d in cursor.description]
                return [
                    {n: a_json(v) for n, v in zip(nombres, fila)}
                    for fila in cursor.fetchall()
                ]
            except duckdb.Error as exc:
                raise ErrorEjecucionSQL("No se pudo leer la vista solicitada.") from exc
        finally:
            conexion.close()

    def ventas_por_mes_pais(self, pais: str | None = None) -> list[dict]:
        if pais is None:
            return self._ejecutar(_SQL_VENTAS + " ORDER BY mes, pais")
        return self._ejecutar(_SQL_VENTAS + " WHERE pais = ? ORDER BY mes, pais", [pais])

    def top_10_clientes(self) -> list[dict]:
        return self._ejecutar(_SQL_TOP)
