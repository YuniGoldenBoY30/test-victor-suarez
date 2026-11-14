"""Endurecimiento de la API: CORS, hosts de confianza, cabeceras, 500 genérico, 413/415, docs."""
import asyncio
import json
import logging

import pytest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.dependencias import get_cliente_llm, get_settings
from app.fabrica import create_app
from app.seguridad import (
    CSP_API,
    CSP_DOCS,
    GuardaCuerpoJSON,
    MAX_CUERPO_CONSULTA,
    MiddlewareSeguridad,
)
from core.config import Settings

ORIGEN = "http://localhost:5173"
MALO = "http://malo.example"
GENERICO = {"error": "error_interno", "mensaje": "Error interno del servidor."}
CABECERAS_JSON = {"Content-Type": "application/json"}

ESPERADAS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "cache-control": "no-store",
    "content-security-policy": CSP_API,
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
}


class LLMFalso:
    def generar_sql(self, pregunta):
        return "SELECT cliente FROM pedidos"


@pytest.fixture
def montar(db_prueba):
    def _montar(base_url="http://localhost", **ajustes):
        settings = Settings(
            _env_file=None,
            api_ia_nvidia=None,
            duckdb_path=str(db_prueba),
            cors_origins=[ORIGEN],
            **ajustes,
        )
        app = create_app(settings)
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_cliente_llm] = lambda: LLMFalso()
        return TestClient(app, base_url=base_url)

    return _montar


def _con_cabeceras(r):
    for nombre, valor in ESPERADAS.items():
        assert r.headers.get(nombre) == valor, f"{nombre} en {r.status_code}"


# --- CORS ---------------------------------------------------------------------------------


def test_origen_permitido_sin_credenciales(montar):
    r = montar().get("/health", headers={"Origin": ORIGEN})
    assert r.headers["access-control-allow-origin"] == ORIGEN
    assert "access-control-allow-credentials" not in r.headers


def test_origen_no_permitido_sin_acao(montar):
    r = montar().get("/health", headers={"Origin": MALO})
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers


def _preflight(c, origen, cabeceras="content-type"):
    return c.options(
        "/consulta",
        headers={
            "Origin": origen,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": cabeceras,
        },
    )


def test_preflight_permitido_sin_comodin(montar):
    r = _preflight(montar(), ORIGEN)
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == ORIGEN
    assert "access-control-allow-credentials" not in r.headers
    permitidas = {h.strip().lower() for h in r.headers["access-control-allow-headers"].split(",")}
    # Starlette añade además las cabeceras "safelisted" del estándar CORS.
    assert {"content-type", "accept"} <= permitidas
    assert permitidas <= {"content-type", "accept", "accept-language", "content-language"}
    assert "*" not in r.headers["access-control-allow-headers"]
    assert "*" not in r.headers["access-control-allow-origin"]
    assert "*" not in r.headers["access-control-allow-methods"]
    _con_cabeceras(r)


def test_preflight_origen_no_permitido_rechazado(montar):
    r = _preflight(montar(), MALO)
    assert r.status_code == 400
    assert "access-control-allow-origin" not in r.headers
    _con_cabeceras(r)


def test_preflight_cabecera_no_permitida_rechazada(montar):
    r = _preflight(montar(), ORIGEN, cabeceras="authorization")
    assert r.status_code == 400


def test_configuracion_cors_y_orden_de_middlewares(montar):
    app = montar().app
    clases = [m.cls for m in app.user_middleware]  # de fuera hacia dentro
    assert clases == [MiddlewareSeguridad, TrustedHostMiddleware, CORSMiddleware, GuardaCuerpoJSON]
    cors = next(m for m in app.user_middleware if m.cls is CORSMiddleware).kwargs
    assert cors["allow_credentials"] is False
    assert cors["allow_origins"] == [ORIGEN]
    assert cors["allow_headers"] == ["Content-Type", "Accept"]
    assert cors["allow_methods"] == ["GET", "POST", "OPTIONS"]
    assert "*" not in cors["allow_origins"] + cors["allow_headers"] + cors["allow_methods"]


# --- Cabeceras de seguridad en todas las respuestas ------------------------------------------


def test_cabeceras_en_200(montar):
    r = montar().get("/health")
    assert r.status_code == 200
    _con_cabeceras(r)


def test_cabeceras_en_404(montar):
    r = montar().get("/no-existe")
    assert r.status_code == 404
    _con_cabeceras(r)


def test_cabeceras_en_405(montar):
    r = montar().delete("/health")
    assert r.status_code == 405
    _con_cabeceras(r)


def test_cabeceras_en_422(montar):
    r = montar().post("/consulta", json={})
    assert r.status_code == 422
    _con_cabeceras(r)


def test_cabeceras_en_error_de_aplicacion(montar):
    r = montar().get("/ventas-por-mes-pais", params={"pais": "x"})
    assert r.status_code == 200
    _con_cabeceras(r)


def test_cabeceras_en_415(montar):
    r = montar().post("/consulta", content=b"{}", headers={"Content-Type": "text/plain"})
    assert r.status_code == 415
    _con_cabeceras(r)


def test_cabeceras_en_413(montar):
    r = montar().post("/consulta", content=b"x" * 9000, headers=CABECERAS_JSON)
    assert r.status_code == 413
    _con_cabeceras(r)


def test_cabeceras_en_host_no_permitido(montar):
    r = montar(base_url="http://evil.example").get("/health")
    assert r.status_code == 400
    _con_cabeceras(r)


def test_host_permitido_configurable(montar):
    c = montar(base_url="http://api.ejemplo.com", trusted_hosts=["api.ejemplo.com"])
    assert c.get("/health").status_code == 200
    assert montar(base_url="http://localhost", trusted_hosts=["api.ejemplo.com"]).get(
        "/health"
    ).status_code == 400


def test_host_con_comodin_de_subdominio(montar):
    c = montar(base_url="http://x.ejemplo.com", trusted_hosts=["*.ejemplo.com"])
    assert c.get("/health").status_code == 200


def test_testserver_no_es_host_por_defecto(montar):
    assert montar(base_url="http://testserver").get("/health").status_code == 400


# --- 500 genérico ------------------------------------------------------------------------------


def test_500_generico_con_cabeceras_y_sin_fugas(montar, caplog):
    c = montar()

    @c.app.get("/explota")
    def explota():
        raise RuntimeError("detalle-secreto-interno")

    with caplog.at_level(logging.ERROR):
        r = c.get("/explota")

    assert r.status_code == 500
    assert r.json() == GENERICO
    assert r.text == json.dumps(GENERICO, separators=(",", ":"))
    for fuga in ("Traceback", "RuntimeError", "detalle-secreto-interno"):
        assert fuga not in r.text
    _con_cabeceras(r)
    # La causa real solo queda en el log del servidor.
    assert "detalle-secreto-interno" in caplog.text


def test_500_desde_dependencia(montar):
    c = montar()

    def rota():
        raise ValueError("clave-interna")

    c.app.dependency_overrides[get_cliente_llm] = rota
    r = c.post("/consulta", json={"pregunta": "x"})
    assert r.status_code == 500 and r.json() == GENERICO
    assert "clave-interna" not in r.text
    _con_cabeceras(r)


def test_500_no_reescribe_respuesta_ya_iniciada():
    """Si la respuesta ya empezó, la excepción se propaga y no se envía un segundo cuerpo."""
    enviados = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("tarde")

    async def send(mensaje):
        enviados.append(mensaje)

    async def receive():
        return {"type": "http.disconnect"}

    scope = {"type": "http", "method": "GET", "path": "/x", "headers": []}
    with pytest.raises(RuntimeError):
        asyncio.run(MiddlewareSeguridad(app)(scope, receive, send))
    assert [m["type"] for m in enviados] == ["http.response.start"]


# --- Documentación desactivada por defecto -----------------------------------------------------


@pytest.mark.parametrize("ruta", ["/docs", "/redoc", "/openapi.json"])
def test_docs_desactivadas_por_defecto(montar, ruta):
    r = montar().get(ruta)
    assert r.status_code == 404
    _con_cabeceras(r)


@pytest.mark.parametrize("ruta", ["/docs", "/redoc", "/openapi.json"])
def test_docs_activables(montar, ruta):
    r = montar(api_docs=True).get(ruta)
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    esperada = CSP_API if ruta == "/openapi.json" else CSP_DOCS
    assert r.headers["content-security-policy"] == esperada
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


# --- 415 Content-Type --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cabeceras",
    [
        {"Content-Type": "text/plain"},
        {"Content-Type": "application/x-www-form-urlencoded"},
        {"Content-Type": "multipart/form-data; boundary=x"},
        {"Content-Type": "application/jsonx"},
        {"Content-Type": ""},
        {},
    ],
)
def test_415_si_no_es_json(montar, cabeceras):
    r = montar().post("/consulta", content=b'{"pregunta": "x"}', headers=cabeceras)
    assert r.status_code == 415
    cuerpo = r.json()
    assert set(cuerpo) == {"error", "mensaje"}
    assert cuerpo["error"] == "tipo_contenido_no_soportado" and cuerpo["mensaje"]


@pytest.mark.parametrize(
    "tipo",
    ["application/json", "Application/JSON", "application/json; charset=utf-8", " application/json ;charset=UTF-8"],
)
def test_json_admitido_sin_importar_mayusculas_ni_parametros(montar, tipo):
    r = montar().post(
        "/consulta", content=b'{"pregunta": "lista"}', headers={"Content-Type": tipo}
    )
    assert r.status_code == 200 and r.json()["pregunta"] == "lista"


def test_415_con_cabeceras_cors_para_origen_permitido(montar):
    r = montar().post(
        "/consulta", content=b"{}", headers={"Content-Type": "text/plain", "Origin": ORIGEN}
    )
    assert r.status_code == 415
    assert r.headers["access-control-allow-origin"] == ORIGEN


def test_preflight_a_consulta_no_es_415(montar):
    r = _preflight(montar(), ORIGEN)
    assert r.status_code == 200


def test_get_no_exige_content_type(montar):
    c = montar()
    assert c.get("/health", headers={"Content-Type": "text/plain"}).status_code == 200
    assert c.get("/top-clientes", headers={"Content-Type": "text/plain"}).status_code == 200


# --- 413 tamaño ----------------------------------------------------------------------------------


def _json_de_tamano(n):
    base = json.dumps({"pregunta": "lista", "relleno": ""}, separators=(",", ":")).encode()
    return json.dumps(
        {"pregunta": "lista", "relleno": "a" * (n - len(base))}, separators=(",", ":")
    ).encode()


def test_413_por_content_length(montar):
    cuerpo = _json_de_tamano(MAX_CUERPO_CONSULTA + 1)
    assert len(cuerpo) == MAX_CUERPO_CONSULTA + 1
    r = montar().post("/consulta", content=cuerpo, headers=CABECERAS_JSON)
    assert r.status_code == 413
    resp = r.json()
    assert set(resp) == {"error", "mensaje"} and resp["error"] == "cuerpo_demasiado_grande"


def test_cuerpo_justo_en_el_limite_pasa(montar):
    cuerpo = _json_de_tamano(MAX_CUERPO_CONSULTA)
    assert len(cuerpo) == MAX_CUERPO_CONSULTA
    r = montar().post("/consulta", content=cuerpo, headers=CABECERAS_JSON)
    assert r.status_code == 200 and r.json()["pregunta"] == "lista"


def test_413_en_cuerpo_en_streaming_sin_content_length(montar):
    def trozos():
        for _ in range(3):
            yield b"a" * 4000

    r = montar().post("/consulta", content=trozos(), headers=CABECERAS_JSON)
    assert r.status_code == 413
    assert r.json()["error"] == "cuerpo_demasiado_grande"
    _con_cabeceras(r)


def test_streaming_pequeno_pasa(montar):
    def trozos():
        yield b'{"pregunta":'
        yield b' "lista"}'

    r = montar().post("/consulta", content=trozos(), headers=CABECERAS_JSON)
    assert r.status_code == 200 and r.json()["pregunta"] == "lista"


def test_413_con_cabeceras_cors_para_origen_permitido(montar):
    r = montar().post(
        "/consulta",
        content=b"x" * 9000,
        headers={**CABECERAS_JSON, "Origin": ORIGEN},
    )
    assert r.status_code == 413
    assert r.headers["access-control-allow-origin"] == ORIGEN


def test_cuerpo_de_422_sigue_siendo_posible_bajo_el_limite(montar):
    r = montar().post("/consulta", json={"pregunta": "a" * 501})
    assert r.status_code == 422 and "detail" in r.json()


# --- Guarda a nivel ASGI (sin cliente HTTP) ------------------------------------------------------


def _ejecutar_guarda(cabeceras, mensajes, max_bytes=8192):
    """Ejecuta la guarda con un receive guionizado; devuelve (respuesta, cuerpo visto, receive_usado)."""
    visto = {}
    enviados = []
    cola = list(mensajes)
    leidos = []

    async def interna(scope, receive, send):
        cuerpo = b""
        while True:
            m = await receive()
            cuerpo += m.get("body", b"")
            if not m.get("more_body", False):
                break
        visto["cuerpo"] = cuerpo
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        leidos.append(1)
        return cola.pop(0) if cola else {"type": "http.disconnect"}

    async def send(m):
        enviados.append(m)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/consulta",
        "headers": [(k.encode(), v.encode()) for k, v in cabeceras],
    }
    asyncio.run(GuardaCuerpoJSON(interna, max_bytes=max_bytes)(scope, receive, send))
    estado = next((m["status"] for m in enviados if m["type"] == "http.response.start"), None)
    return estado, visto.get("cuerpo"), len(leidos)


def test_guarda_content_length_excesivo_no_lee_el_cuerpo():
    estado, visto, lecturas = _ejecutar_guarda(
        [("content-type", "application/json"), ("content-length", "999999")],
        [{"type": "http.request", "body": b"x", "more_body": False}],
    )
    assert estado == 413 and visto is None and lecturas == 0


def test_guarda_cuenta_bytes_de_trozos_sin_content_length():
    trozos = [{"type": "http.request", "body": b"a" * 60, "more_body": True} for _ in range(3)]
    trozos.append({"type": "http.request", "body": b"", "more_body": False})
    estado, visto, _ = _ejecutar_guarda(
        [("content-type", "application/json")], trozos, max_bytes=100
    )
    assert estado == 413 and visto is None


def test_guarda_content_length_mentiroso_no_evita_el_limite():
    """Un Content-Length pequeño con más bytes de los declarados sigue limitado."""
    estado, _, _ = _ejecutar_guarda(
        [("content-type", "application/json"), ("content-length", "5")],
        [{"type": "http.request", "body": b"a" * 200, "more_body": False}],
        max_bytes=100,
    )
    assert estado == 413


def test_guarda_reenvia_el_cuerpo_integro_a_la_app():
    trozos = [
        {"type": "http.request", "body": b'{"a":', "more_body": True},
        {"type": "http.request", "body": b"1}", "more_body": False},
    ]
    estado, visto, _ = _ejecutar_guarda([("content-type", "application/json")], trozos)
    assert estado == 204 and visto == b'{"a":1}'


def test_guarda_cliente_desconectado_no_responde():
    estado, visto, _ = _ejecutar_guarda(
        [("content-type", "application/json")], [{"type": "http.disconnect"}]
    )
    assert estado is None and visto is None
