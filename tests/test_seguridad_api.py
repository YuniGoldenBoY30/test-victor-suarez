"""Endurecimiento de la API: CORS, hosts, cabeceras, 500 genérico, 413/415, docs, límite de tasa."""
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
    LimitadorVentana,
    MAX_CUERPO_CONSULTA,
    MiddlewareLimiteTasa,
    MiddlewareSeguridad,
    ip_cliente,
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
    assert clases == [
        MiddlewareSeguridad,
        TrustedHostMiddleware,
        CORSMiddleware,
        MiddlewareLimiteTasa,
        GuardaCuerpoJSON,
    ]
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


# --- Límite de tasa por IP -------------------------------------------------------------------------

CUERPO_429 = {"error", "mensaje"}


def _consultar(c, **extra):
    return c.post("/consulta", json={"pregunta": "lista"}, **extra)


def _xff(valor):
    return {"X-Forwarded-For": valor}


def test_limite_de_consulta_devuelve_429_uniforme(montar):
    c = montar(rate_limit_consulta_rpm=3)
    for _ in range(3):
        assert _consultar(c).status_code == 200
    r = _consultar(c)
    assert r.status_code == 429
    cuerpo = r.json()
    assert set(cuerpo) == CUERPO_429
    assert cuerpo["error"] == "demasiadas_peticiones" and cuerpo["mensaje"]
    assert r.headers["retry-after"].isdigit()
    assert 1 <= int(r.headers["retry-after"]) <= 60


def test_429_lleva_cabeceras_de_seguridad_y_cors(montar):
    c = montar(rate_limit_consulta_rpm=1)
    assert _consultar(c).status_code == 200
    r = _consultar(c, headers={"Origin": ORIGEN})
    assert r.status_code == 429
    _con_cabeceras(r)
    assert r.headers["access-control-allow-origin"] == ORIGEN


def test_limite_general_en_gets(montar):
    c = montar(rate_limit_rpm=3)
    assert [c.get("/top-clientes").status_code for _ in range(3)] == [200, 200, 200]
    r = c.get("/top-clientes")
    assert r.status_code == 429 and r.json()["error"] == "demasiadas_peticiones"
    assert "retry-after" in r.headers
    # El cupo general es común a todas las rutas no exentas.
    assert c.get("/ventas-por-mes-pais").status_code == 429


def test_cupos_de_consulta_y_general_son_independientes(montar):
    c = montar(rate_limit_rpm=2, rate_limit_consulta_rpm=1)
    assert _consultar(c).status_code == 200
    assert _consultar(c).status_code == 429
    assert c.get("/top-clientes").status_code == 200
    assert c.get("/top-clientes").status_code == 200
    assert c.get("/top-clientes").status_code == 429
    # Los GET no gastan el cupo de /consulta ni al revés.
    assert _consultar(c).status_code == 429


def test_cupo_de_consulta_no_afecta_a_los_get(montar):
    c = montar(rate_limit_consulta_rpm=1)
    assert [c.get("/top-clientes").status_code for _ in range(5)] == [200] * 5


def test_health_exento(montar):
    c = montar(rate_limit_rpm=1, rate_limit_consulta_rpm=1)
    assert [c.get("/health").status_code for _ in range(10)] == [200] * 10
    assert c.get("/top-clientes").status_code == 200  # el cupo sigue intacto


def test_preflight_options_exento(montar):
    c = montar(rate_limit_rpm=1, rate_limit_consulta_rpm=1)
    assert [_preflight(c, ORIGEN).status_code for _ in range(5)] == [200] * 5
    assert _consultar(c).status_code == 200  # el preflight no gastó el cupo


def test_limite_se_aplica_antes_de_leer_el_cuerpo(montar):
    c = montar(rate_limit_consulta_rpm=1)
    assert _consultar(c).status_code == 200
    r = c.post("/consulta", content=b"x" * 9000, headers=CABECERAS_JSON)
    assert r.status_code == 429  # no 413: el cuerpo ni se mira


def test_peticiones_invalidas_tambien_consumen_cupo(montar):
    c = montar(rate_limit_consulta_rpm=2)
    assert c.post("/consulta", json={}).status_code == 422
    r = c.post("/consulta", content=b"{}", headers={"Content-Type": "text/plain"})
    assert r.status_code == 415
    assert _consultar(c).status_code == 429


def test_limite_desactivable(montar):
    c = montar(rate_limit_enabled=False, rate_limit_rpm=1, rate_limit_consulta_rpm=1)
    assert MiddlewareLimiteTasa not in [m.cls for m in c.app.user_middleware]
    assert [_consultar(c).status_code for _ in range(5)] == [200] * 5
    assert [c.get("/top-clientes").status_code for _ in range(5)] == [200] * 5


def test_ips_distintas_no_se_bloquean_entre_si(montar):
    c = montar(rate_limit_consulta_rpm=1, rate_limit_trusted_hops=1)
    assert _consultar(c, headers=_xff("1.1.1.1")).status_code == 200
    assert _consultar(c, headers=_xff("1.1.1.1")).status_code == 429
    assert _consultar(c, headers=_xff("2.2.2.2")).status_code == 200
    assert _consultar(c, headers=_xff("2.2.2.2")).status_code == 429


def test_xff_se_ignora_sin_proxies_de_confianza(montar):
    """Con 0 saltos, rotar X-Forwarded-For no evade el límite (cuenta la IP del socket)."""
    c = montar(rate_limit_consulta_rpm=1)
    assert _consultar(c, headers=_xff("1.1.1.1")).status_code == 200
    assert _consultar(c, headers=_xff("2.2.2.2")).status_code == 429
    assert _consultar(c).status_code == 429


def test_xff_con_saltos_no_se_deja_falsificar_por_la_izquierda(montar):
    # Cadena real: cliente, Cloudflare, Apache (nginx es el socket): 3 saltos de confianza.
    c = montar(rate_limit_consulta_rpm=1, rate_limit_trusted_hops=3)
    cadena = "{falso}, 1.1.1.1, 172.64.0.1, 127.0.0.1"
    assert _consultar(c, headers=_xff(cadena.format(falso="6.6.6.6"))).status_code == 200
    # Cambiar lo que el cliente puede escribir no da cupo nuevo ...
    assert _consultar(c, headers=_xff(cadena.format(falso="7.7.7.7"))).status_code == 429
    # ... y un cliente real distinto sí tiene el suyo.
    otra = "6.6.6.6, 3.3.3.3, 172.64.0.1, 127.0.0.1"
    assert _consultar(c, headers=_xff(otra)).status_code == 200


def test_xff_incompleto_usa_la_ip_del_socket(montar):
    c = montar(rate_limit_consulta_rpm=1, rate_limit_trusted_hops=3)
    assert _consultar(c, headers=_xff("1.1.1.1")).status_code == 200
    assert _consultar(c, headers=_xff("2.2.2.2")).status_code == 429


def _scope(xff=(), cliente=("10.0.0.1", 5000)):
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/x",
        "headers": [(b"x-forwarded-for", v.encode()) for v in xff],
    }
    if cliente is not None:
        scope["client"] = cliente
    return scope


@pytest.mark.parametrize(
    "saltos, xff, cliente, esperada",
    [
        (0, ["9.9.9.9"], ("10.0.0.1", 1), "10.0.0.1"),
        (1, ["9.9.9.9"], ("10.0.0.1", 1), "9.9.9.9"),
        (1, ["6.6.6.6, 9.9.9.9"], ("10.0.0.1", 1), "9.9.9.9"),
        (2, ["6.6.6.6, 1.1.1.1, 2.2.2.2"], ("10.0.0.1", 1), "1.1.1.1"),
        (2, ["6.6.6.6", "1.1.1.1, 2.2.2.2"], ("10.0.0.1", 1), "1.1.1.1"),  # varias cabeceras
        (3, ["1.1.1.1, 2.2.2.2"], ("10.0.0.1", 1), "10.0.0.1"),  # cadena incompleta
        (1, [], ("10.0.0.1", 1), "10.0.0.1"),  # sin cabecera
        (1, ["basura"], ("10.0.0.1", 1), "10.0.0.1"),  # entrada que no es IP
        (1, [" , "], ("10.0.0.1", 1), "10.0.0.1"),
        (1, ["1.2.3.4:5555"], ("10.0.0.1", 1), "1.2.3.4"),
        (1, ["::ffff:1.2.3.4"], ("10.0.0.1", 1), "1.2.3.4"),
        (1, ["2001:db8:1:2:aaaa:bbbb:cccc:dddd"], ("10.0.0.1", 1), "2001:db8:1:2::/64"),
        (0, [], ("2001:db8:1:2:1:1:1:1", 1), "2001:db8:1:2::/64"),
        (0, [], ("testclient", 1), "testclient"),
        (0, [], None, "desconocido"),
        (1, ["9.9.9.9"], None, "9.9.9.9"),
    ],
)
def test_ip_cliente(saltos, xff, cliente, esperada):
    assert ip_cliente(_scope(xff, cliente), saltos) == esperada


def test_ipv6_del_mismo_prefijo_comparte_cupo(montar):
    c = montar(rate_limit_consulta_rpm=1, rate_limit_trusted_hops=1)
    assert _consultar(c, headers=_xff("2001:db8:1:2::1")).status_code == 200
    assert _consultar(c, headers=_xff("2001:db8:1:2:ffff::9")).status_code == 429
    assert _consultar(c, headers=_xff("2001:db8:1:3::1")).status_code == 200


class Reloj:
    def __init__(self):
        self.ahora = 1000.0

    def __call__(self):
        return self.ahora


def test_limitador_ventana_deslizante_y_retry_after():
    reloj = Reloj()
    lim = LimitadorVentana(ventana=60, reloj=reloj)
    assert lim.intentar("a", 2) is None  # t=0
    reloj.ahora += 10
    assert lim.intentar("a", 2) is None  # t=10
    reloj.ahora += 5
    assert lim.intentar("a", 2) == 45  # t=15: la más antigua (t=0) vence en t=60
    reloj.ahora += 44.5
    assert lim.intentar("a", 2) == 1  # t=59.5: 0.5 s se redondea hacia arriba
    reloj.ahora += 0.5
    assert lim.intentar("a", 2) is None  # t=60: venció la primera marca
    assert lim.intentar("a", 2) == 10  # quedan t=10 y t=60: la más antigua vence en t=70


def test_limitador_rechazos_no_alargan_el_bloqueo():
    reloj = Reloj()
    lim = LimitadorVentana(ventana=60, reloj=reloj)
    assert lim.intentar("a", 1) is None
    for _ in range(50):
        reloj.ahora += 1
        assert lim.intentar("a", 1) is not None  # insistir no empuja la recuperación
    reloj.ahora += 10  # t=60 desde la única petición admitida
    assert lim.intentar("a", 1) is None


def test_limitador_claves_independientes():
    lim = LimitadorVentana(reloj=Reloj())
    assert lim.intentar(("consulta", "1.1.1.1"), 1) is None
    assert lim.intentar(("consulta", "1.1.1.1"), 1) is not None
    assert lim.intentar(("consulta", "2.2.2.2"), 1) is None
    assert lim.intentar(("general", "1.1.1.1"), 1) is None


def test_limitador_memoria_acotada_con_purga_de_vencidas():
    reloj = Reloj()
    lim = LimitadorVentana(ventana=60, max_claves=3, reloj=reloj, intervalo_purga=10)
    for clave in "abc":
        assert lim.intentar(clave, 1) is None
    reloj.ahora += 61  # todas vencidas
    assert lim.intentar("d", 1) is None
    assert len(lim) == 1  # la purga eliminó las tres vencidas


def test_limitador_descarta_la_menos_reciente_si_todo_esta_vigente():
    reloj = Reloj()
    lim = LimitadorVentana(ventana=60, max_claves=3, reloj=reloj, intervalo_purga=10)
    for clave in "abc":
        assert lim.intentar(clave, 1) is None
        reloj.ahora += 1
    assert lim.intentar("a", 1) is not None  # "a" pasa a ser la más reciente
    assert lim.intentar("d", 1) is None  # tabla llena y vigente: sale "b", la menos reciente
    assert len(lim) == 3
    assert lim.intentar("a", 1) is not None  # "a" sigue contando
    assert lim.intentar("b", 1) is None  # "b" fue descartada y empieza de cero


def _llamar(mw, metodo="GET", ruta="/top-clientes", cliente=("1.1.1.1", 1)):
    enviados = []

    async def send(mensaje):
        enviados.append(mensaje)

    async def receive():
        return {"type": "http.disconnect"}

    scope = {"type": "http", "method": metodo, "path": ruta, "headers": [], "client": cliente}
    asyncio.run(mw(scope, receive, send))
    inicio = next(m for m in enviados if m["type"] == "http.response.start")
    return inicio["status"], {k.decode(): v.decode() for k, v in inicio["headers"]}


async def _app_204(scope, receive, send):
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


def test_middleware_recupera_el_acceso_al_pasar_la_ventana():
    reloj = Reloj()
    mw = MiddlewareLimiteTasa(_app_204, limite_general=2, ventana=60, reloj=reloj)
    assert _llamar(mw)[0] == 204
    assert _llamar(mw)[0] == 204
    estado, cabeceras = _llamar(mw)
    assert estado == 429 and cabeceras["retry-after"] == "60"
    reloj.ahora += 30
    assert _llamar(mw)[1]["retry-after"] == "30"
    reloj.ahora += 30
    assert _llamar(mw)[0] == 204


def test_middleware_ignora_ambitos_que_no_son_http():
    llamadas = []

    async def app(scope, receive, send):
        llamadas.append(scope["type"])

    mw = MiddlewareLimiteTasa(app, limite_general=1, limite_consulta=1)

    async def nada(*_):
        return {}

    for tipo in ("lifespan", "websocket", "lifespan", "websocket"):
        asyncio.run(mw({"type": tipo}, nada, nada))
    assert llamadas == ["lifespan", "websocket", "lifespan", "websocket"]
