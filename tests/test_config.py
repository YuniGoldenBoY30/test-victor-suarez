import pytest

from core.config import Settings, get_settings
from core import esquema

VARIABLES = ["API_IA_NVIDIA", "NVIDIA_MODEL", "DUCKDB_PATH", "CORS_ORIGINS"]


@pytest.fixture(autouse=True)
def _aislar(monkeypatch, tmp_path):
    """Ningún test abre el .env real: cwd vacío, variables limpias y caché vacía."""
    monkeypatch.chdir(tmp_path)
    for v in VARIABLES:
        monkeypatch.delenv(v, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _limpiar(monkeypatch):
    for v in VARIABLES:
        monkeypatch.delenv(v, raising=False)


def test_valores_por_defecto(monkeypatch):
    _limpiar(monkeypatch)
    s = Settings(_env_file=None)
    assert s.api_ia_nvidia is None
    assert s.nvidia_model == "meta/llama-3.3-70b-instruct"
    assert s.nvidia_base_url == "https://integrate.api.nvidia.com/v1"
    assert s.llm_timeout == 30
    assert s.duckdb_path == "data/pedidos.duckdb"
    assert s.cors_origins == ["http://localhost:5173"]


def test_variables_de_entorno(monkeypatch):
    _limpiar(monkeypatch)
    monkeypatch.setenv("NVIDIA_MODEL", "otro/modelo")
    monkeypatch.setenv("DUCKDB_PATH", "x/y.duckdb")
    monkeypatch.setenv("CORS_ORIGINS", "http://a.com, http://b.com")
    s = Settings(_env_file=None)
    assert s.nvidia_model == "otro/modelo"
    assert s.duckdb_path == "x/y.duckdb"
    assert s.cors_origins == ["http://a.com", "http://b.com"]


def test_valores_vacios_usan_defecto(monkeypatch):
    for v in VARIABLES:
        monkeypatch.setenv(v, "")
    s = Settings(_env_file=None)
    assert s.api_ia_nvidia is None
    assert s.duckdb_path == "data/pedidos.duckdb"
    assert s.cors_origins == ["http://localhost:5173"]


def test_clave_no_aparece_en_repr(monkeypatch):
    _limpiar(monkeypatch)
    monkeypatch.setenv("API_IA_NVIDIA", "clave-falsa-de-prueba")
    s = Settings(_env_file=None)
    assert s.api_ia_nvidia.get_secret_value() == "clave-falsa-de-prueba"
    assert "clave-falsa-de-prueba" not in repr(s)
    assert "clave-falsa-de-prueba" not in str(s)


def test_get_settings_cacheado():
    assert get_settings() is get_settings()


def test_esquema_constantes():
    assert esquema.COLUMNAS_CSV == ["fecha", "cliente", "pais", "producto", "importe", "estado"]
    assert esquema.ESTADO_EXCLUIDO_VENTAS in esquema.ESTADOS
    assert esquema.RELACIONES_PERMITIDAS == {"pedidos", "ventas_por_mes_pais", "top_10_clientes"}
    assert set(esquema.VARIANTES_PAIS.values()) == set(esquema.PAISES)
    assert esquema.FECHA_MIN < esquema.FECHA_MAX
