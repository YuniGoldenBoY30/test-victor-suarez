"""Servicio de consultas: LLM -> validar_sql -> ejecución de solo lectura."""
from collections.abc import Callable
from dataclasses import dataclass
import math
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

import duckdb

from app.errores import ErrorEjecucionSQL
from app.llm import ClienteLLM
from app.validador_sql import validar_sql


def a_json(valor: Any) -> Any:
    """Convierte un valor de DuckDB a algo serializable en JSON."""
    if valor is None or isinstance(valor, (bool, int, str)):
        return valor
    if isinstance(valor, (datetime, date, time)):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, float):
        return valor if math.isfinite(valor) else str(valor)
    if isinstance(valor, dict):
        return {str(k): a_json(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple, set, frozenset)):
        return [a_json(v) for v in valor]
    if isinstance(valor, (bytes, bytearray, memoryview)):
        return bytes(valor).hex()
    return str(valor)  # UUID, timedelta, etc.


@dataclass(frozen=True)
class ResultadoConsulta:
    pregunta: str
    sql: str
    columnas: list[str]
    filas: list[list[Any]]


class ServicioConsultas:
    def __init__(
        self,
        cliente_llm: ClienteLLM,
        abrir_conexion: Callable[[], duckdb.DuckDBPyConnection],
    ) -> None:
        self._llm = cliente_llm
        self._abrir = abrir_conexion

    def consultar(self, pregunta: str) -> ResultadoConsulta:
        sql = validar_sql(self._llm.generar_sql(pregunta))
        conexion = self._abrir()
        try:
            try:
                cursor = conexion.execute(sql)
                columnas = [d[0] for d in cursor.description]
                filas = [[a_json(v) for v in fila] for fila in cursor.fetchall()]
            except duckdb.Error as exc:
                raise ErrorEjecucionSQL("No se pudo ejecutar la consulta generada.") from exc
        finally:
            conexion.close()
        return ResultadoConsulta(pregunta=pregunta, sql=sql, columnas=columnas, filas=filas)
