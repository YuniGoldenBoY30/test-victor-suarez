"""Dependencias de FastAPI (todas sobrescribibles con dependency_overrides)."""
from fastapi import Depends

from app.db import abrir_conexion_lectura
from app.llm import ClienteLLM, ClienteNvidia
from app.repositorio_vistas import RepositorioVistas
from app.servicio import ServicioConsultas
from core.config import Settings, get_settings

__all__ = ["get_settings", "get_cliente_llm", "get_servicio", "get_repositorio"]


def _abridor(settings: Settings):
    return lambda: abrir_conexion_lectura(settings.duckdb_path)


def get_cliente_llm(settings: Settings = Depends(get_settings)) -> ClienteLLM:
    return ClienteNvidia(settings)


def get_servicio(
    cliente: ClienteLLM = Depends(get_cliente_llm),
    settings: Settings = Depends(get_settings),
) -> ServicioConsultas:
    return ServicioConsultas(cliente, _abridor(settings))


def get_repositorio(settings: Settings = Depends(get_settings)) -> RepositorioVistas:
    return RepositorioVistas(_abridor(settings))
