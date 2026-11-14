"""Limpieza pura de filas de pedidos (sin E/S).

Reglas: recortar espacios, normalizar país a su forma canónica, parsear la fecha con
FORMATOS_FECHA (imposibles o no parseables se descartan), descartar importes vacíos,
inválidos o negativos (sin imputar) y eliminar duplicados exactos tras normalizar las
6 columnas (no hay id de pedido; el duplicado se define por todas las columnas).
Fechas fuera de FECHA_MIN..FECHA_MAX se descartan. El cliente se normaliza con str.title()
(p. ej. " ana  lópez" -> "Ana López") para unificar mayúsculas y espacios.
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from core.esquema import ESTADOS, FECHA_MAX, FECHA_MIN, FORMATOS_FECHA, VARIANTES_PAIS

_CENT = Decimal("0.01")
_IMPORTE_MAX = Decimal("9999999999.99")  # límite de DECIMAL(12,2)


def _texto(valor) -> str:
    return " ".join(str(valor if valor is not None else "").split())


def parsear_fecha(valor) -> date | None:
    texto = _texto(valor)
    for formato in FORMATOS_FECHA:
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def parsear_importe(valor) -> Decimal | None:
    texto = _texto(valor).replace(" ", "")
    if not texto:
        return None
    if "," in texto and "." in texto:
        # El último separador es el decimal.
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        importe = Decimal(texto)
    except InvalidOperation:
        return None
    if not importe.is_finite() or importe < 0 or importe > _IMPORTE_MAX + _CENT:
        return None
    try:
        importe = importe.quantize(_CENT)
    except InvalidOperation:
        return None
    return importe if importe <= _IMPORTE_MAX else None


def limpiar_filas(filas):
    """Devuelve (filas_limpias, informe). Cada fila es un dict con las 6 columnas."""
    informe = {
        "filas_entrada": 0,
        "descartadas_fecha": 0,
        "descartadas_fecha_fuera_rango": 0,
        "descartadas_importe": 0,
        "descartadas_pais": 0,
        "descartadas_estado": 0,
        "descartadas_campos_vacios": 0,
        "duplicados": 0,
        "filas_salida": 0,
    }
    limpias = []
    vistas = set()
    for fila in filas:
        informe["filas_entrada"] += 1
        fecha = parsear_fecha(fila.get("fecha"))
        if fecha is None:
            informe["descartadas_fecha"] += 1
            continue
        if not FECHA_MIN <= fecha <= FECHA_MAX:
            informe["descartadas_fecha_fuera_rango"] += 1
            continue
        importe = parsear_importe(fila.get("importe"))
        if importe is None:
            informe["descartadas_importe"] += 1
            continue
        pais = VARIANTES_PAIS.get(_texto(fila.get("pais")).lower())
        if pais is None:
            informe["descartadas_pais"] += 1
            continue
        estado = _texto(fila.get("estado")).lower()
        if estado not in ESTADOS:
            informe["descartadas_estado"] += 1
            continue
        cliente = _texto(fila.get("cliente")).title()
        producto = _texto(fila.get("producto"))
        if not cliente or not producto:
            informe["descartadas_campos_vacios"] += 1
            continue
        limpia = {
            "fecha": fecha, "cliente": cliente, "pais": pais,
            "producto": producto, "importe": importe, "estado": estado,
        }
        clave = tuple(limpia.values())
        if clave in vistas:
            informe["duplicados"] += 1
            continue
        vistas.add(clave)
        limpias.append(limpia)
    informe["filas_salida"] = len(limpias)
    return limpias, informe
