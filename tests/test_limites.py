"""Límites de POST /consulta: ventana por cliente, tope diario global e IP del cliente."""
import threading
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.dependencias import get_cliente_llm, get_settings
from app.fabrica import create_app
from app.limites import (
    CLIENTE_DESCONOCIDO,
    CODIGO_LIMITE_DIARIO,
    CODIGO_LIMITE_PETICIONES,
    LimiteExcedidoError,
    LimitadorConsultas,
    normalizar_cliente,
    resolver_ip_cliente,
)
from app.seguridad import CSP_API
from core.config import Settings

JSON = {"Content-Type": "application/json"}
PREGUNTA = {"pregunta": "¿Quién compró más?"}
CABECERA = "X-Cliente-IP"
INICIO = datetime(2024, 5, 10, 12, 0, 0, tzinfo=timezone.utc).timestamp()
MEDIANOCHE = datetime(2024, 5, 11, 0, 0, 0, tzinfo=timezone.utc).timestamp()


class Reloj:
    def __init__(self, t=INICIO):
        self.t = t

    def __call__(self):
        return self.t

    def avanzar(self, segundos):
        self.t += segundos


def _rechazo(limitador, cliente="a"):
    with pytest.raises(LimiteExcedidoError) as e:
        limitador.registrar(cliente)
    return e.value


# --- LimitadorConsultas (sin HTTP) ------------------------------------------------------


def test_por_minuto_rechaza_con_retry_after_y_se_libera():
    reloj = Reloj()
    lim = LimitadorConsultas(3, 0, 0, reloj)
    for _ in range(3):
        lim.registrar("a")
        reloj.avanzar(10)  # t = +10, +20, +30
    err = _rechazo(lim)
    assert err.codigo == CODIGO_LIMITE_PETICIONES
    assert err.reintentar_en == 30  # la primera marca (t=0) caduca en t=60
    reloj.avanzar(29)
    assert _rechazo(lim).reintentar_en == 1
    reloj.avanzar(1)  # t = +60: la primera marca ya salió de la ventana
    lim.registrar("a")


def test_las_rechazadas_no_consumen_cuota_ni_alargan_el_bloqueo():
    reloj = Reloj()
    lim = LimitadorConsultas(1, 0, 0, reloj)
    lim.registrar("a")
    for _ in range(20):
        reloj.avanzar(1)
        _rechazo(lim)
    reloj.avanzar(40)  # t = +60 desde la única marca aceptada
    lim.registrar("a")


def test_por_hora_se_aplica_aunque_el_minuto_este_libre():
    reloj = Reloj()
    lim = LimitadorConsultas(10, 4, 0, reloj)
    for _ in range(4):
        lim.registrar("a")
        reloj.avanzar(120)  # +0, +120, +240, +360
    err = _rechazo(lim)  # t = +480
    assert err.codigo == CODIGO_LIMITE_PETICIONES
    assert err.reintentar_en == 3600 - 480
    reloj.avanzar(3600 - 480)
    lim.registrar("a")


def test_retry_after_es_el_mayor_de_las_dos_ventanas():
    reloj = Reloj()
    lim = LimitadorConsultas(1, 1, 0, reloj)
    lim.registrar("a")
    reloj.avanzar(5)
    assert _rechazo(lim).reintentar_en == 3595


def test_clientes_independientes():
    lim = LimitadorConsultas(1, 0, 0, Reloj())
    lim.registrar("a")
    lim.registrar("b")
    _rechazo(lim, "a")
    _rechazo(lim, "b")


def test_retry_after_se_redondea_hacia_arriba_y_nunca_es_cero():
    reloj = Reloj()
    lim = LimitadorConsultas(1, 0, 0, reloj)
    lim.registrar("a")
    reloj.avanzar(59.2)
    assert _rechazo(lim).reintentar_en == 1
    reloj.avanzar(0.8)
    lim.registrar("a")


def test_tope_diario_global_entre_clientes():
    lim = LimitadorConsultas(0, 0, 3, Reloj())
    for cliente in "abc":
        lim.registrar(cliente)
    err = _rechazo(lim, "d")
    assert err.codigo == CODIGO_LIMITE_DIARIO
    assert err.reintentar_en == 12 * 3600  # hasta la medianoche UTC


def test_tope_diario_se_reinicia_a_medianoche_utc():
    reloj = Reloj(MEDIANOCHE - 10)
    lim = LimitadorConsultas(0, 0, 1, reloj)
    lim.registrar("a")
    err = _rechazo(lim, "b")
    assert err.codigo == CODIGO_LIMITE_DIARIO and err.reintentar_en == 10
    reloj.avanzar(9)
    _rechazo(lim, "b")
    reloj.avanzar(1)  # 00:00:00 UTC del día siguiente
    lim.registrar("b")
    assert _rechazo(lim, "c").reintentar_en == 86400


def test_el_limite_del_cliente_se_mira_antes_que_el_diario_y_no_gasta_el_global():
    lim = LimitadorConsultas(1, 0, 2, Reloj())
    lim.registrar("a")
    assert _rechazo(lim, "a").codigo == CODIGO_LIMITE_PETICIONES
    lim.registrar("b")  # el rechazo de "a" no gastó el segundo hueco global
    assert _rechazo(lim, "c").codigo == CODIGO_LIMITE_DIARIO


def test_el_rechazo_diario_no_anota_al_cliente():
    reloj = Reloj()
    lim = LimitadorConsultas(1, 0, 1, reloj)
    lim.registrar("a")
    reloj.avanzar(MEDIANOCHE - INICIO)  # otro día y, de paso, la marca de "a" ya caducó
    lim.registrar("b")
    assert _rechazo(lim, "c").codigo == CODIGO_LIMITE_DIARIO
    reloj.avanzar(86400)
    lim.registrar("c")  # no le quedó ninguna marca del intento rechazado


def test_cero_desactiva_cada_limite():
    lim = LimitadorConsultas(0, 0, 0, Reloj())
    for _ in range(1000):
        lim.registrar("a")
    solo_hora = LimitadorConsultas(0, 2, 0, Reloj())
    solo_hora.registrar("a")
    solo_hora.registrar("a")
    _rechazo(solo_hora)


@pytest.mark.parametrize("malo", [-1, 1.5, "10", None, True])
def test_valores_no_validos_del_limitador(malo):
    with pytest.raises(ValueError):
        LimitadorConsultas(malo, 0, 0)


def test_se_olvidan_los_clientes_inactivos():
    reloj = Reloj()
    lim = LimitadorConsultas(5, 5, 0, reloj)
    for i in range(50):
        lim.registrar(f"c{i}")
    assert len(lim._marcas) == 50
    reloj.avanzar(3601)
    lim.registrar("nuevo")
    assert list(lim._marcas) == ["nuevo"]


def test_humo_de_concurrencia_no_deja_pasar_mas_del_limite():
    lim = LimitadorConsultas(0, 0, 50, lambda: INICIO)
    aceptadas, rechazadas = [], []
    barrera = threading.Barrier(16)

    def hilo():
        barrera.wait()
        for _ in range(20):
            try:
                lim.registrar("a")
                aceptadas.append(1)
            except LimiteExcedidoError:
                rechazadas.append(1)

    hilos = [threading.Thread(target=hilo) for _ in range(16)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert len(aceptadas) == 50 and len(rechazadas) == 16 * 20 - 50


def test_humo_de_concurrencia_por_cliente():
    lim = LimitadorConsultas(7, 0, 0, lambda: INICIO)
    aceptadas = []
    barrera = threading.Barrier(12)

    def hilo():
        barrera.wait()
        for _ in range(10):
            try:
                lim.registrar("a")
                aceptadas.append(1)
            except LimiteExcedidoError:
                pass

    hilos = [threading.Thread(target=hilo) for _ in range(12)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert len(aceptadas) == 7


# --- IP del cliente ---------------------------------------------------------------------


def test_sin_cabecera_se_usa_la_ip_de_la_conexion():
    assert resolver_ip_cliente("203.0.113.9") == "203.0.113.9"
    assert resolver_ip_cliente("203.0.113.9", []) == "203.0.113.9"


def test_cabecera_con_ip_valida_manda_sobre_la_conexion():
    assert resolver_ip_cliente("172.18.0.3", ["198.51.100.7"]) == "198.51.100.7"
    assert resolver_ip_cliente("172.18.0.3", [" 198.51.100.7 "]) == "198.51.100.7"


@pytest.mark.parametrize(
    "valores",
    [
        ["no-es-una-ip"],
        [""],
        ["198.51.100.7, 10.0.0.1"],  # lista tipo X-Forwarded-For
        ["198.51.100.7:8080"],
        ["198.51.100.7", "198.51.100.8"],  # cabecera repetida
        ["999.1.1.1"],
        ["198.51.100.7\r\n"],
    ],
)
def test_cabecera_invalida_o_ambigua_vuelve_a_la_conexion(valores):
    esperado = "198.51.100.7" if valores == ["198.51.100.7\r\n"] else "172.18.0.3"
    assert resolver_ip_cliente("172.18.0.3", valores) == esperado


def test_sin_peer_ni_cabecera_clave_de_reserva():
    assert resolver_ip_cliente(None) == CLIENTE_DESCONOCIDO
    assert resolver_ip_cliente("") == CLIENTE_DESCONOCIDO


def test_normalizacion_ipv6_e_ipv4_mapeada():
    assert normalizar_cliente("::ffff:203.0.113.9") == "203.0.113.9"
    # Dentro de un /64 es el mismo cliente; otro /64 es otro cliente.
    assert normalizar_cliente("2001:db8:1:2::1") == normalizar_cliente("2001:db8:1:2:ffff::9")
    assert normalizar_cliente("2001:db8:1:3::1") != normalizar_cliente("2001:db8:1:2::1")
    assert normalizar_cliente("testclient") == "testclient"


# --- Settings ---------------------------------------------------------------------------


def _ajustes(**kw):
    return Settings(_env_file=None, **kw)


def test_ajustes_por_defecto():
    s = _ajustes()
    assert (s.limite_consultas_minuto, s.limite_consultas_hora, s.limite_consultas_dia) == (10, 60, 500)
    assert s.cabecera_ip_cliente == ""


def test_ajustes_desde_el_entorno(monkeypatch):
    monkeypatch.setenv("LIMITE_CONSULTAS_MINUTO", "3")
    monkeypatch.setenv("LIMITE_CONSULTAS_HORA", "0")
    monkeypatch.setenv("LIMITE_CONSULTAS_DIA", "7")
    monkeypatch.setenv("CABECERA_IP_CLIENTE", " X-Cliente-IP ")
    s = _ajustes()
    assert (s.limite_consultas_minuto, s.limite_consultas_hora, s.limite_consultas_dia) == (3, 0, 7)
    assert s.cabecera_ip_cliente == "X-Cliente-IP"


def test_variables_vacias_usan_el_defecto(monkeypatch):
    for v in ("LIMITE_CONSULTAS_MINUTO", "LIMITE_CONSULTAS_HORA", "LIMITE_CONSULTAS_DIA", "CABECERA_IP_CLIENTE"):
        monkeypatch.setenv(v, "")
    s = _ajustes()
    assert s.limite_consultas_minuto == 10 and s.cabecera_ip_cliente == ""


@pytest.mark.parametrize("campo", ["limite_consultas_minuto", "limite_consultas_hora", "limite_consultas_dia"])
@pytest.mark.parametrize("valor", [-1, "abc", "1.5"])
def test_limites_no_validos(campo, valor):
    with pytest.raises(ValidationError):
        _ajustes(**{campo: valor})


@pytest.mark.parametrize(
    "nombre",
    ["X Cliente", "X-Cliente:IP", "X-Cliente-IP\r\nX-Otro", "Cabecera/IP", "añadir", "(x)", "a,b"],
)
def test_nombre_de_cabecera_no_valido(nombre):
    with pytest.raises(ValidationError):
        _ajustes(cabecera_ip_cliente=nombre)


@pytest.mark.parametrize("nombre", ["X-Forwarded-For", "x-forwarded-for", "Forwarded"])
def test_x_forwarded_for_nunca_se_acepta_como_cabecera_de_ip(nombre):
    with pytest.raises(ValidationError):
        _ajustes(cabecera_ip_cliente=nombre)


# --- API --------------------------------------------------------------------------------


class LLMFalso:
    def __init__(self):
        self.llamadas = 0

    def generar_sql(self, pregunta):
        self.llamadas += 1
        return "SELECT cliente FROM pedidos"


@pytest.fixture
def montar(db_prueba):
    def _montar(minuto=0, hora=0, dia=0, cabecera="", reloj=None):
        settings = Settings(
            _env_file=None,
            api_ia_nvidia=None,
            duckdb_path=str(db_prueba),
            limite_consultas_minuto=minuto,
            limite_consultas_hora=hora,
            limite_consultas_dia=dia,
            cabecera_ip_cliente=cabecera,
        )
        llm = LLMFalso()
        app = create_app(settings, reloj=reloj or Reloj())
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_cliente_llm] = lambda: llm
        return TestClient(app, base_url="http://localhost"), llm

    return _montar


def _post(c, ip=None, **kw):
    cabeceras = dict(JSON)
    if ip is not None:
        cabeceras[CABECERA] = ip
    return c.post("/consulta", json=PREGUNTA, headers=cabeceras, **kw)


def test_429_por_cliente_con_formato_retry_after_y_cabeceras_de_seguridad(montar):
    c, llm = montar(minuto=2)
    assert _post(c).status_code == 200 and _post(c).status_code == 200
    r = _post(c)
    assert r.status_code == 429
    cuerpo = r.json()
    assert cuerpo["error"] == "limite_peticiones" and cuerpo["mensaje"]
    assert set(cuerpo) == {"error", "mensaje"}
    assert r.headers["retry-after"] == "60"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["content-security-policy"] == CSP_API
    assert llm.llamadas == 2  # la rechazada no llegó al LLM


def test_429_diario_global_con_retry_after_hasta_medianoche_utc(montar):
    reloj = Reloj()
    c, llm = montar(dia=2, reloj=reloj)
    assert _post(c, "198.51.100.1").status_code == 200
    assert _post(c, "198.51.100.2").status_code == 200
    r = _post(c, "198.51.100.3")
    assert r.status_code == 429
    assert r.json()["error"] == "limite_diario"
    assert r.headers["retry-after"] == str(12 * 3600)
    assert r.headers["content-security-policy"] == CSP_API
    assert llm.llamadas == 2
    reloj.t = MEDIANOCHE
    assert _post(c).status_code == 200
    assert llm.llamadas == 3


def test_429_lleva_cabeceras_cors_y_expone_retry_after(montar):
    c, _ = montar(minuto=1)
    origen = {"Origin": "http://localhost:5173"}
    assert c.post("/consulta", json=PREGUNTA, headers={**JSON, **origen}).status_code == 200
    r = c.post("/consulta", json=PREGUNTA, headers={**JSON, **origen})
    assert r.status_code == 429
    assert r.headers["access-control-allow-origin"] == origen["Origin"]
    assert "retry-after" in r.headers["access-control-expose-headers"].lower()


def test_get_nunca_se_limita(montar):
    c, _ = montar(minuto=1, hora=1, dia=1)
    assert _post(c).status_code == 200
    assert _post(c).status_code == 429
    for _ in range(30):
        assert c.get("/health").status_code == 200
        assert c.get("/top-clientes").status_code == 200
        assert c.get("/ventas-por-mes-pais").status_code == 200


def test_la_cabecera_solo_cuenta_si_esta_configurada(montar):
    # Sin cabecera configurada: cambiar X-Cliente-IP no da cuota nueva (lo escribe el cliente).
    c, llm = montar(minuto=1)
    assert _post(c, "198.51.100.1").status_code == 200
    assert _post(c, "198.51.100.2").status_code == 429
    assert llm.llamadas == 1

    # Con la cabecera configurada: cada IP válida tiene su cuota.
    c, llm = montar(minuto=1, cabecera=CABECERA)
    assert _post(c, "198.51.100.1").status_code == 200
    assert _post(c, "198.51.100.2").status_code == 200
    assert _post(c, "198.51.100.1").status_code == 429
    assert llm.llamadas == 2


def test_cabecera_invalida_o_ausente_cae_en_la_conexion_y_no_da_cuota_extra(montar):
    c, llm = montar(minuto=1, cabecera=CABECERA)
    assert _post(c).status_code == 200  # sin cabecera: IP de la conexión
    for valor in ("basura", "198.51.100.1, 198.51.100.2", "", "300.1.1.1"):
        assert _post(c, valor).status_code == 429, valor
    assert llm.llamadas == 1


def test_cabecera_repetida_no_se_confia(montar):
    c, llm = montar(minuto=1, cabecera=CABECERA)
    assert _post(c).status_code == 200
    r = c.post(
        "/consulta",
        json=PREGUNTA,
        headers=[
            ("content-type", "application/json"),
            ("x-cliente-ip", "198.51.100.1"),
            ("x-cliente-ip", "198.51.100.2"),
        ],
    )
    assert r.status_code == 429
    assert llm.llamadas == 1


def test_x_forwarded_for_se_ignora_con_y_sin_cabecera_configurada(montar):
    for cabecera in ("", CABECERA):
        c, llm = montar(minuto=1, cabecera=cabecera)
        for ip in ("198.51.100.1", "198.51.100.2"):
            r = c.post("/consulta", json=PREGUNTA, headers={**JSON, "X-Forwarded-For": ip})
            assert r.status_code == (200 if ip.endswith(".1") else 429)
        assert llm.llamadas == 1


def test_415_413_y_422_no_consumen_cuota(montar):
    c, llm = montar(minuto=1, dia=1)
    assert c.post("/consulta", content="x", headers={"Content-Type": "text/plain"}).status_code == 415
    assert c.post("/consulta", content=b"{" + b" " * 9000 + b"}", headers=JSON).status_code == 413
    assert c.post("/consulta", json={"pregunta": ""}, headers=JSON).status_code == 422
    assert c.post("/consulta", json={}, headers=JSON).status_code == 422
    assert c.post("/consulta", content=b"no es json", headers=JSON).status_code == 422
    assert llm.llamadas == 0
    assert _post(c).status_code == 200  # la cuota minuto y el hueco diario seguían intactos
    assert _post(c).status_code == 429


def test_con_los_limites_a_cero_no_hay_429(montar):
    c, llm = montar()
    for _ in range(40):
        assert _post(c).status_code == 200
    assert llm.llamadas == 40


def test_la_ventana_se_libera_con_el_reloj(montar):
    reloj = Reloj()
    c, _ = montar(minuto=1, reloj=reloj)
    assert _post(c).status_code == 200
    r = _post(c)
    assert r.status_code == 429 and r.headers["retry-after"] == "60"
    reloj.avanzar(60)
    assert _post(c).status_code == 200


def test_error_del_llm_o_sql_invalida_si_consume_cuota(montar):
    # Estas peticiones sí llegaron al LLM (gasto real): cuentan.
    c, llm = montar(minuto=1)
    llm.generar_sql = lambda pregunta: "DROP TABLE pedidos"
    assert _post(c).status_code == 422
    assert _post(c).status_code == 429


def test_no_cambia_la_pila_de_middlewares(montar):
    from app.seguridad import GuardaCuerpoJSON, MiddlewareSeguridad

    c, _ = montar()
    clases = [m.cls for m in c.app.user_middleware]
    assert clases[0] is MiddlewareSeguridad and clases[-1] is GuardaCuerpoJSON
