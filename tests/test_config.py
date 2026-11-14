import pytest
from pydantic import ValidationError

from core.config import Settings, get_settings
from core import esquema

VARIABLES = [
    "API_IA_NVIDIA", "NVIDIA_MODEL", "DUCKDB_PATH", "CORS_ORIGINS", "TRUSTED_HOSTS", "API_DOCS",
]


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
    assert s.trusted_hosts == ["localhost", "127.0.0.1"]
    assert s.api_docs is False


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
    assert s.trusted_hosts == ["localhost", "127.0.0.1"]
    assert s.api_docs is False


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


# --- CORS, hosts de confianza y documentación -------------------------------------------


def test_origenes_se_normalizan(monkeypatch):
    _limpiar(monkeypatch)
    monkeypatch.setenv("CORS_ORIGINS", " https://App.Ejemplo.com/ , http://localhost:5173/ ")
    assert Settings(_env_file=None).cors_origins == [
        "https://app.ejemplo.com",
        "http://localhost:5173",
    ]


def test_origenes_en_json(monkeypatch):
    _limpiar(monkeypatch)
    monkeypatch.setenv("CORS_ORIGINS", '["https://a.com", "http://b.com:8080"]')
    assert Settings(_env_file=None).cors_origins == ["https://a.com", "http://b.com:8080"]


@pytest.mark.parametrize(
    "origen",
    [
        "*",
        "http://*.ejemplo.com",
        "null",
        "NULL",
        "ftp://a.com",
        "file:///etc/passwd",
        "a.com",
        "//a.com",
        "http://",
        "http://a.com/ruta",
        "http://a.com//",
        "http://a.com?x=1",
        "http://a.com#frag",
        "http://usuario@a.com",
        "http://usuario:clave@a.com",
        "http://a.com:abc",
        "http://a b.com",
        "javascript:alert(1)",
    ],
)
def test_origen_invalido_rechazado(monkeypatch, origen):
    _limpiar(monkeypatch)
    monkeypatch.setenv("CORS_ORIGINS", origen)
    with pytest.raises(ValidationError, match="Origen CORS no válido"):
        Settings(_env_file=None)


def test_un_origen_invalido_en_la_lista_rechaza_todo(monkeypatch):
    _limpiar(monkeypatch)
    monkeypatch.setenv("CORS_ORIGINS", "http://a.com,*")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_origen_json_no_texto_rechazado(monkeypatch):
    _limpiar(monkeypatch)
    monkeypatch.setenv("CORS_ORIGINS", '["http://a.com", 5]')
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_hosts_de_confianza_desde_entorno(monkeypatch):
    _limpiar(monkeypatch)
    monkeypatch.setenv("TRUSTED_HOSTS", "Api.Ejemplo.com, *.ejemplo.org ,127.0.0.1")
    assert Settings(_env_file=None).trusted_hosts == [
        "api.ejemplo.com",
        "*.ejemplo.org",
        "127.0.0.1",
    ]


def test_hosts_de_confianza_en_json(monkeypatch):
    _limpiar(monkeypatch)
    monkeypatch.setenv("TRUSTED_HOSTS", '["a.com", "b.com"]')
    assert Settings(_env_file=None).trusted_hosts == ["a.com", "b.com"]


@pytest.mark.parametrize(
    "host", ["*", "*.", "a.*.com", "*.*.com", "a.com:8000", "http://a.com", "a.com/x", "a b"]
)
def test_host_de_confianza_invalido_rechazado(monkeypatch, host):
    _limpiar(monkeypatch)
    monkeypatch.setenv("TRUSTED_HOSTS", host)
    with pytest.raises(ValidationError, match="Host de confianza no válido"):
        Settings(_env_file=None)


def test_hosts_de_confianza_vacios_rechazados():
    with pytest.raises(ValidationError, match="al menos un host"):
        Settings(_env_file=None, trusted_hosts=[])


def test_defecto_sin_testserver_ni_dominios_de_despliegue():
    s = Settings(_env_file=None)
    assert "testserver" not in s.trusted_hosts
    assert not any("." in h and not h.replace(".", "").isdigit() for h in s.trusted_hosts)


@pytest.mark.parametrize("texto, esperado", [("true", True), ("1", True), ("false", False)])
def test_api_docs_desde_entorno(monkeypatch, texto, esperado):
    _limpiar(monkeypatch)
    monkeypatch.setenv("API_DOCS", texto)
    assert Settings(_env_file=None).api_docs is esperado
