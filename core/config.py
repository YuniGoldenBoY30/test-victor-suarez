"""Configuración central de la aplicación (única fuente de ajustes)."""
from functools import lru_cache
from typing import Annotated

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Ajustes leídos del entorno y de `.env`. Las variables vacías se ignoran."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    api_ia_nvidia: SecretStr | None = None
    nvidia_model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    llm_timeout: float = 30
    duckdb_path: str = "data/pedidos.duckdb"
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _separar_origenes(cls, valor):
        """Admite lista separada por comas o JSON."""
        if isinstance(valor, str):
            texto = valor.strip()
            if texto.startswith("["):
                import json

                return json.loads(texto)
            return [parte.strip() for parte in texto.split(",") if parte.strip()]
        return valor


@lru_cache
def get_settings() -> Settings:
    return Settings()
