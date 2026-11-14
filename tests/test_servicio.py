import json
import traceback
from types import SimpleNamespace

import duckdb
import pytest
from pydantic import SecretStr

from app.db import abrir_conexion_lectura
from app.errores import BaseDatosNoDisponibleError, ErrorEjecucionSQL
from app.llm import ClienteNvidia, LLMError, LLMNoConfiguradoError
from app.servicio import ServicioConsultas
from app.validador_sql import SQLNoPermitidoError
from core.config import Settings


class LLMFalso:
    def __init__(self, sql=None, error=None):
        self.sql, self.error = sql, error

    def generar_sql(self, pregunta):
        if self.error:
            raise self.error
        return self.sql


def servicio(db, llm):
    return ServicioConsultas(llm, lambda: abrir_conexion_lectura(db))


def test_exito_filas_json_seguras(db_prueba):
    s = servicio(db_prueba, LLMFalso("SELECT mes, total_ventas FROM ventas_por_mes_pais ORDER BY mes"))
    r = s.consultar("ventas")
    assert r.columnas == ["mes", "total_ventas"]
    assert r.filas[0] == ["2024-01-01", 150.5]
    assert "LIMIT" in r.sql.upper()
    json.dumps(r.filas)


def test_error_llm_se_propaga(db_prueba):
    with pytest.raises(LLMError):
        servicio(db_prueba, LLMFalso(error=LLMError("x"))).consultar("q")


def test_sql_no_permitido(db_prueba):
    with pytest.raises(SQLNoPermitidoError):
        servicio(db_prueba, LLMFalso("DROP TABLE pedidos")).consultar("q")


def test_columna_desconocida(db_prueba):
    with pytest.raises(ErrorEjecucionSQL):
        servicio(db_prueba, LLMFalso("SELECT nada FROM pedidos")).consultar("q")


def test_base_inexistente(tmp_path):
    with pytest.raises(BaseDatosNoDisponibleError):
        servicio(tmp_path / "no.duckdb", LLMFalso("SELECT 1 FROM pedidos")).consultar("q")


def test_conexion_solo_lectura(db_prueba):
    con = abrir_conexion_lectura(db_prueba)
    with pytest.raises(duckdb.Error):
        con.execute("DELETE FROM pedidos")
    with pytest.raises(duckdb.Error):
        con.execute("SELECT * FROM read_csv('x.csv')")
    con.close()


class _Completions:
    def __init__(self, contenido=None, error=None):
        self.contenido, self.error, self.llamadas = contenido, error, []

    def create(self, **kw):
        self.llamadas.append(kw)
        if self.error:
            raise self.error
        msg = SimpleNamespace(content=self.contenido)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def openai_falso(**kw):
    comp = _Completions(**kw)
    return SimpleNamespace(chat=SimpleNamespace(completions=comp)), comp


def ajustes(clave="secreta"):
    return Settings(_env_file=None, api_ia_nvidia=SecretStr(clave) if clave else None)


def test_nvidia_quita_vallas():
    cli, comp = openai_falso(contenido="```sql\nSELECT 1 FROM pedidos\n```")
    assert ClienteNvidia(ajustes(), cli).generar_sql("p") == "SELECT 1 FROM pedidos"
    assert comp.llamadas[0]["model"] == ajustes().nvidia_model


def test_nvidia_sin_vallas():
    cli, _ = openai_falso(contenido="  SELECT 2 FROM pedidos ")
    assert ClienteNvidia(ajustes(), cli).generar_sql("p") == "SELECT 2 FROM pedidos"


def test_nvidia_error_envuelto_sin_filtrar_clave():
    cli, _ = openai_falso(error=RuntimeError("fallo con secreta"))
    with pytest.raises(LLMError) as exc:
        ClienteNvidia(ajustes(), cli).generar_sql("p")
    assert "secreta" not in str(exc.value)


@pytest.mark.parametrize("contenido", [None, "", "   ", "```\n```"])
def test_nvidia_vacio(contenido):
    cli, _ = openai_falso(contenido=contenido)
    with pytest.raises(LLMError):
        ClienteNvidia(ajustes(), cli).generar_sql("p")


def test_nvidia_sin_clave():
    with pytest.raises(LLMNoConfiguradoError):
        ClienteNvidia(ajustes(None)).generar_sql("p")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT list(fecha) AS f FROM pedidos",
        "SELECT list(importe) AS i FROM pedidos",
        "SELECT {'f': min(fecha), 'i': max(importe)} AS s FROM pedidos",
        "SELECT [list(fecha)] AS anidada FROM pedidos",
    ],
)
def test_tipos_anidados_son_json_seguros(db_prueba, sql):
    r = servicio(db_prueba, LLMFalso(sql)).consultar("q")
    json.dumps(r.filas)


def test_a_json_tipos_anidados():
    import uuid
    from datetime import date, datetime, time, timedelta
    from decimal import Decimal

    from app.servicio import a_json

    valor = {"a": [date(2024, 1, 2), (Decimal("1.5"), time(1, 2))], "b": uuid.UUID(int=1),
             "c": timedelta(seconds=5), "d": b"\x01", "e": datetime(2024, 1, 2, 3, 4)}
    res = a_json(valor)
    assert res["a"] == ["2024-01-02", [1.5, "01:02:00"]]
    assert res["e"] == "2024-01-02T03:04:00"
    json.dumps(res)


CLAVE_DUMMY = "clave-dummy-123"


def _afirmar_sin_clave(exc):
    """La clave no aparece en el mensaje, la causa, el contexto ni el traceback."""
    assert CLAVE_DUMMY not in str(exc)
    assert CLAVE_DUMMY not in exc.mensaje
    assert CLAVE_DUMMY not in repr(exc)
    assert exc.__cause__ is None
    assert exc.__context__ is None
    assert CLAVE_DUMMY not in "".join(traceback.format_exception(exc))


def test_constructor_sdk_que_falla_no_filtra_la_clave(monkeypatch):
    import app.llm as llm

    def constructor(**kw):
        raise RuntimeError(f"fallo al crear cliente con {kw['api_key']}")

    monkeypatch.setattr(llm, "OpenAI", constructor)
    with pytest.raises(LLMError) as exc:
        ClienteNvidia(ajustes(CLAVE_DUMMY)).generar_sql("p")
    _afirmar_sin_clave(exc.value)


def test_llamada_sdk_que_falla_no_filtra_la_clave():
    cli, _ = openai_falso(error=RuntimeError(f"401 con api_key={CLAVE_DUMMY}"))
    with pytest.raises(LLMError) as exc:
        ClienteNvidia(ajustes(CLAVE_DUMMY), cli).generar_sql("p")
    _afirmar_sin_clave(exc.value)


def test_respuesta_mal_formada_no_filtra_la_clave():
    class Rara:
        @property
        def choices(self):
            raise ValueError(f"respuesta con {CLAVE_DUMMY}")

    comp = SimpleNamespace(create=lambda **kw: Rara())
    cli = SimpleNamespace(chat=SimpleNamespace(completions=comp))
    with pytest.raises(LLMError) as exc:
        ClienteNvidia(ajustes(CLAVE_DUMMY), cli).generar_sql("p")
    _afirmar_sin_clave(exc.value)
