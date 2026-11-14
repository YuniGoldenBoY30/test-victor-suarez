"""Configuración central de la aplicación (única fuente de ajustes)."""
import json
import re
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


_TOKEN_CABECERA = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
# Cabeceras que el cliente puede escribir o ampliar: nunca son una fuente fiable de la IP.
_CABECERAS_IP_PROHIBIDAS = frozenset({"x-forwarded-for", "forwarded"})


def _validar_cabecera_ip(valor) -> str:
    """Nombre de cabecera HTTP (caracteres de token); vacío significa «no usar cabecera»."""
    if not isinstance(valor, str):
        raise ValueError(f"Nombre de cabecera no válido (se esperaba texto): {valor!r}")
    texto = valor.strip()
    if not texto:
        return ""
    if not _TOKEN_CABECERA.match(texto):
        raise ValueError(f"Nombre de cabecera no válido, solo caracteres de token HTTP: {valor!r}")
    if texto.lower() in _CABECERAS_IP_PROHIBIDAS:
        raise ValueError(
            f"{texto} no es una fuente fiable de la IP del cliente: la puede escribir el "
            "cliente. Use una cabecera que el proxy sobrescriba (p. ej. X-Cliente-IP)."
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
    # Límites de POST /consulta (0 desactiva el límite). Ver docs/TRD.md, secciones 10 y 11.
    limite_consultas_minuto: int = Field(default=10, ge=0)
    limite_consultas_hora: int = Field(default=60, ge=0)
    limite_consultas_dia: int = Field(default=500, ge=0)
    # Vacío: la IP del cliente es la de la conexión TCP. Con valor (p. ej. X-Cliente-IP, que
    # Apache sobrescribe con la IP real) se usa esa cabecera si trae una IP válida.
    cabecera_ip_cliente: str = ""

    @field_validator("cors_origins", "trusted_hosts", mode="before")
    @classmethod
    def _separar_valores(cls, valor):
        return _separar_lista(valor)

    @field_validator("cabecera_ip_cliente", mode="before")
    @classmethod
    def _validar_cabecera(cls, valor):
        return _validar_cabecera_ip(valor)

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
