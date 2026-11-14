from datetime import date
from decimal import Decimal

import pytest

from etl.limpieza import limpiar_filas


def fila(**kw):
    base = {"fecha": "2024-03-01", "cliente": "Ana", "pais": "España",
            "producto": "Teclado", "importe": "10.50", "estado": "completado"}
    base.update(kw)
    return base


def test_normaliza_pais_espacios_y_estado():
    out, _ = limpiar_filas([fila(pais="  spain ", cliente="  ana  lópez", estado=" ENVIADO ")])
    assert out[0]["pais"] == "España"
    assert out[0]["cliente"] == "Ana López"
    assert out[0]["estado"] == "enviado"


@pytest.mark.parametrize("texto", ["2024-03-01", "01/03/2024", "01-03-2024", "2024/03/01"])
def test_formato_de_fecha(texto):
    out, inf = limpiar_filas([fila(fecha=texto)])
    assert out[0]["fecha"] == date(2024, 3, 1)
    assert inf["descartadas_fecha"] == 0


@pytest.mark.parametrize("texto", ["2023-12-31", "2025-07-01", "01/01/1999", "2030-01-01"])
def test_fechas_fuera_de_rango_descartadas(texto):
    out, inf = limpiar_filas([fila(fecha=texto)])
    assert out == []
    assert inf["descartadas_fecha_fuera_rango"] == 1
    assert inf["descartadas_fecha"] == 0


def test_limites_de_rango_incluidos():
    out, _ = limpiar_filas([fila(fecha="2024-01-01"), fila(fecha="2025-06-30")])
    assert len(out) == 2


@pytest.mark.parametrize("texto", ["1e100", "NaN", "Infinity", "-Infinity", "10000000000.00",
                                   "9999999999.995", "99999999999999999999999999999999"])
def test_importes_extremos_descartados_sin_excepcion(texto):
    out, inf = limpiar_filas([fila(importe=texto)])
    assert out == []
    assert inf["descartadas_importe"] == 1


def test_importe_maximo_valido_y_redondeo():
    out, _ = limpiar_filas([fila(importe="9999999999.99"), fila(importe="1.005", cliente="B")])
    assert out[0]["importe"] == Decimal("9999999999.99")
    assert out[1]["importe"] == Decimal("1.00")  # redondeo half-even a 2 decimales


def test_informe_completo():
    filas = [
        fila(), fila(),                      # 1 duplicado
        fila(fecha="2024-02-30"),            # fecha imposible
        fila(fecha="2020-01-01"),            # fuera de rango
        fila(importe=""),                    # importe
        fila(pais="Narnia"),                 # país
        fila(estado="raro"),                 # estado
        fila(cliente="  "),                  # campo vacío
    ]
    out, inf = limpiar_filas(filas)
    assert inf == {
        "filas_entrada": 8,
        "descartadas_fecha": 1,
        "descartadas_fecha_fuera_rango": 1,
        "descartadas_importe": 1,
        "descartadas_pais": 1,
        "descartadas_estado": 1,
        "descartadas_campos_vacios": 1,
        "duplicados": 1,
        "filas_salida": 1,
    }
    assert len(out) == 1


def test_fechas_imposibles_descartadas():
    out, inf = limpiar_filas([fila(fecha=f) for f in ["2024-02-30", "31/04/2024", "2024-13-01", "xx"]])
    assert out == []
    assert inf["descartadas_fecha"] == 4


def test_importes_invalidos_descartados_y_coma_decimal():
    out, inf = limpiar_filas([
        fila(importe=""), fila(importe="abc"), fila(importe="-5"),
        fila(importe="12,5", cliente="B"),
    ])
    assert inf["descartadas_importe"] == 3
    assert out[0]["importe"] == Decimal("12.50")


def test_duplicados_tras_normalizar():
    out, inf = limpiar_filas([fila(), fila(pais="spain", cliente=" ana "), fila(fecha="01/03/2024")])
    assert len(out) == 1
    assert inf["duplicados"] == 2
    assert inf["filas_entrada"] == 3 and inf["filas_salida"] == 1


def test_pais_o_estado_desconocido_descartado():
    out, inf = limpiar_filas([fila(pais="Narnia"), fila(estado="raro")])
    assert out == []
    assert inf["descartadas_pais"] == 1 and inf["descartadas_estado"] == 1
