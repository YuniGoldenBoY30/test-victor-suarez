"""Configuración central de la aplicación (única fuente de ajustes)."""
import json
from functools import lru_cache
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _separar_lista(valor):
    """Admite lista separada por comas o JSON; cualquier otro valor pasa intacto."""
    if isinstance(valor, str):
        texto = valor.strip()
        if texto.startswith("["):
            return json.loads(texto)
        return [parte.strip() for parte in texto.split(",") if parte.strip()]
    return valor


def _normalizar_origen(origen) -> str:
    """Valida un origen CORS (`esquema://host[:puerto]`) y lo devuelve normalizado.

    Rechaza comodines, `null`, credenciales, rutas, consultas y fragmentos: un origen
    nunca los lleva y aceptarlos delataría una configuración equivocada.
    """
    if not isinstance(origen, str):
        raise ValueError(f"Origen CORS no válido (se esperaba texto): {origen!r}")
    texto = origen.strip()
    if texto.endswith("/"):
        texto = texto[:-1]
    if "*" in texto:
        raise ValueError(f"Origen CORS no válido, no se admiten comodines: {origen!r}")
    if texto.lower() == "null":
        raise ValueError("Origen CORS no válido: 'null' no está permitido.")
    if not texto or any(c.isspace() for c in texto):
        raise ValueError(f"Origen CORS no válido: {origen!r}")
    try:
        partes = urlsplit(texto)
        host = partes.hostname
        partes.port  # noqa: B018 - provoca ValueError si el puerto no es válido
    except ValueError as exc:
        raise ValueError(f"Origen CORS no válido: {origen!r}") from exc
    if partes.scheme.lower() not in ("http", "https"):
        raise ValueError(f"Origen CORS no válido, el esquema debe ser http o https: {origen!r}")
    if not host:
        raise ValueError(f"Origen CORS no válido, falta el host: {origen!r}")
    if "@" in partes.netloc:
        raise ValueError(f"Origen CORS no válido, no admite credenciales: {origen!r}")
    if partes.path or partes.query or partes.fragment or "?" in texto or "#" in texto:
        raise ValueError(
            "Origen CORS no válido, solo esquema, host y puerto "
            f"(sin ruta, consulta ni fragmento): {origen!r}"
        )
    return texto.lower()


def _validar_host(host) -> str:
    """Valida un host de confianza: nombre o IP sin puerto; `*.dominio` permitido, `*` no."""
    if not isinstance(host, str):
        raise ValueError(f"Host de confianza no válido (se esperaba texto): {host!r}")
    texto = host.strip().lower()
    resto = texto[2:] if texto.startswith("*.") else texto
    if "*" in resto:
        raise ValueError(
            f"Host de confianza no válido, solo se admite el comodín inicial '*.dominio': {host!r}"
        )
    if not resto or any(c.isspace() or c in "/:@?#" for c in resto):
        raise ValueError(
            f"Host de confianza no válido, use solo el nombre sin puerto ni ruta: {host!r}"
        )
    return texto


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
    trusted_hosts: Annotated[list[str], NoDecode] = ["localhost", "127.0.0.1"]
    api_docs: bool = False
    # Límite de tasa por IP (peticiones por minuto). `consulta` llama al LLM de pago.
    rate_limit_enabled: bool = True
    rate_limit_rpm: int = Field(60, ge=1)
    rate_limit_consulta_rpm: int = Field(10, ge=1)
    # Proxies de confianza delante del backend (0 = ninguno: se usa la IP del socket).
    rate_limit_trusted_hops: int = Field(0, ge=0, le=10)

    @field_validator("cors_origins", "trusted_hosts", mode="before")
    @classmethod
    def _separar_valores(cls, valor):
        return _separar_lista(valor)

    @field_validator("cors_origins")
    @classmethod
    def _validar_origenes(cls, valor: list[str]) -> list[str]:
        return [_normalizar_origen(o) for o in valor]

    @field_validator("trusted_hosts")
    @classmethod
    def _validar_hosts(cls, valor: list[str]) -> list[str]:
        if not valor:
            raise ValueError("Se necesita al menos un host de confianza.")
        return [_validar_host(h) for h in valor]


@lru_cache
def get_settings() -> Settings:
    return Settings()
