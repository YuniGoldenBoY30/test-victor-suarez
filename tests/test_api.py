"""Tests de la API con TestClient, dependency_overrides y un LLM falso (sin red ni .env)."""
import pytest
from fastapi.testclient import TestClient

from app.dependencias import get_cliente_llm, get_settings
from app.llm import LLMError, LLMNoConfiguradoError
from app.fabrica import create_app
from core.config import Settings

ORIGEN = "http://localhost:5173"


class LLMFalso:
    def __init__(self, sql=None, error=None):
        self.sql, self.error = sql, error

    def generar_sql(self, pregunta):
        if self.error:
            raise self.error
        return self.sql


@pytest.fixture
def montar(db_prueba):
    """Devuelve una función que crea un cliente de pruebas con el LLM indicado."""

    def _montar(llm=None, ruta=None):
        settings = Settings(
            _env_file=None,
            api_ia_nvidia=None,
            duckdb_path=str(ruta or db_prueba),
            cors_origins=[ORIGEN],
        )
        app = create_app(settings)
        app.dependency_overrides[get_settings] = lambda: settings
        if llm is not None:
            app.dependency_overrides[get_cliente_llm] = lambda: llm
        return TestClient(app)

    return _montar


def test_health(montar):
    r = montar().get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_ventas_por_mes_pais_con_y_sin_filtro(montar):
    c = montar()
    todo = c.get("/ventas-por-mes-pais").json()
    assert {"mes", "pais", "num_pedidos", "total_ventas"} == set(todo[0])
    assert todo[0]["mes"] == "2024-01-01"
    assert {f["pais"] for f in todo} == {"España", "Francia"}
    solo = c.get("/ventas-por-mes-pais", params={"pais": "Francia"}).json()
    assert [f["pais"] for f in solo] == ["Francia"]
    assert solo[0]["total_ventas"] == 75.0


def test_top_clientes(montar):
    datos = montar().get("/top-clientes").json()
    assert set(datos[0]) == {"cliente", "num_pedidos", "total_comprado"}
    assert datos[0]["cliente"] == "Ana" and datos[0]["total_comprado"] == 150.5
    assert "Luis" in [d["cliente"] for d in datos]


def test_consulta_exitosa(montar):
    llm = LLMFalso("SELECT cliente, importe FROM pedidos ORDER BY importe")
    r = montar(llm).post("/consulta", json={"pregunta": "lista de pedidos"})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["pregunta"] == "lista de pedidos"
    assert cuerpo["columnas"] == ["cliente", "importe"]
    assert len(cuerpo["filas"]) == 5 and "LIMIT" in cuerpo["sql"].upper()


def test_llm_error_502(montar):
    r = montar(LLMFalso(error=LLMError("fallo"))).post("/consulta", json={"pregunta": "x"})
    assert r.status_code == 502
    assert r.json() == {"error": "llm_error", "mensaje": "fallo"}


def test_llm_no_configurado_503(montar):
    r = montar(LLMFalso(error=LLMNoConfiguradoError("sin clave"))).post(
        "/consulta", json={"pregunta": "x"}
    )
    assert r.status_code == 503 and r.json()["error"] == "llm_no_configurado"


def test_llm_real_sin_clave_503(montar):
    r = montar().post("/consulta", json={"pregunta": "x"})
    assert r.status_code == 503 and r.json()["error"] == "llm_no_configurado"


@pytest.mark.parametrize(
    "sql",
    ["DROP TABLE pedidos", "SELECT * FROM otra_tabla", "SELECT * FROM read_csv('a.csv')"],
)
def test_sql_no_valida_422_con_sql(montar, sql):
    r = montar(LLMFalso(sql)).post("/consulta", json={"pregunta": "x"})
    assert r.status_code == 422
    cuerpo = r.json()
    assert cuerpo["error"] == "sql_no_valida" and cuerpo["sql"] == sql and cuerpo["mensaje"]


def test_error_ejecucion_422(montar):
    r = montar(LLMFalso("SELECT CAST(cliente AS INTEGER) FROM pedidos")).post("/consulta", json={"pregunta": "x"})
    assert r.status_code == 422
    assert r.json()["error"] == "error_ejecucion" and "sql" not in r.json()


def test_base_datos_no_disponible_503(montar, tmp_path):
    c = montar(LLMFalso("SELECT 1 FROM pedidos"), ruta=tmp_path / "no_existe.duckdb")
    for r in (
        c.post("/consulta", json={"pregunta": "x"}),
        c.get("/top-clientes"),
        c.get("/ventas-por-mes-pais"),
    ):
        assert r.status_code == 503 and r.json()["error"] == "base_datos_no_disponible"


@pytest.mark.parametrize("cuerpo", [{}, {"pregunta": ""}, {"pregunta": "a" * 501}, {"otra": 1}])
def test_cuerpo_invalido_422(montar, cuerpo):
    r = montar(LLMFalso("SELECT 1 FROM pedidos")).post("/consulta", json=cuerpo)
    assert r.status_code == 422 and "detail" in r.json()


def test_cors(montar):
    c = montar()
    cab = {
        "Origin": ORIGEN,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }
    r = c.options("/consulta", headers=cab)
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == ORIGEN
    r = c.get("/health", headers={"Origin": ORIGEN})
    assert r.headers["access-control-allow-origin"] == ORIGEN
    r = c.get("/health", headers={"Origin": "http://malo.example"})
    assert "access-control-allow-origin" not in r.headers


def test_sql_rechazado_incluye_sql_con_servicio_real(montar):
    """Servicio real + LLM falso: el SQL generado viaja en el 422."""
    r = montar(LLMFalso("DROP TABLE pedidos")).post("/consulta", json={"pregunta": "x"})
    assert r.status_code == 422
    assert r.json()["error"] == "sql_no_valida" and r.json()["sql"] == "DROP TABLE pedidos"


def test_celdas_anidadas_en_json(montar):
    r = montar(LLMFalso("SELECT [1,2] AS lista FROM pedidos LIMIT 1")).post(
        "/consulta", json={"pregunta": "x"}
    )
    assert r.status_code == 200 and r.json()["filas"] == [[[1, 2]]]
