"""Modelos de la API (contrato HTTP; el frontend los replica en src/api/types.ts)."""
from typing import Any

from pydantic import BaseModel, Field


class Salud(BaseModel):
    status: str = "ok"


class ConsultaEntrada(BaseModel):
    pregunta: str = Field(min_length=1, max_length=500)


class ConsultaSalida(BaseModel):
    pregunta: str
    sql: str
    columnas: list[str]
    filas: list[list[Any]]


class VentaMesPais(BaseModel):
    mes: str
    pais: str
    num_pedidos: int
    total_ventas: float


class TopCliente(BaseModel):
    cliente: str
    num_pedidos: int
    total_comprado: float
