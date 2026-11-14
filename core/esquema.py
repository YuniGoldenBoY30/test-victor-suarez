"""Constantes compartidas (única definición) del esquema de pedidos."""
from datetime import date

COLUMNAS_CSV = ["fecha", "cliente", "pais", "producto", "importe", "estado"]

PAISES = ["España", "Francia", "Alemania", "Italia", "Portugal", "México"]

# Variantes sucias (en minúsculas, sin espacios sobrantes) -> país canónico.
VARIANTES_PAIS = {
    "españa": "España", "espana": "España", "spain": "España", "es": "España", "esp": "España",
    "francia": "Francia", "france": "Francia", "fr": "Francia",
    "alemania": "Alemania", "germany": "Alemania", "deutschland": "Alemania", "de": "Alemania",
    "italia": "Italia", "italy": "Italia", "it": "Italia",
    "portugal": "Portugal", "pt": "Portugal",
    "méxico": "México", "mexico": "México", "mx": "México",
}

ESTADOS = ["completado", "enviado", "pendiente", "cancelado"]
ESTADO_EXCLUIDO_VENTAS = "cancelado"

FECHA_MIN = date(2024, 1, 1)
FECHA_MAX = date(2025, 6, 30)

# Formatos strptime admitidos al limpiar fechas.
FORMATOS_FECHA = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"]

RELACIONES_PERMITIDAS = frozenset({"pedidos", "ventas_por_mes_pais", "top_10_clientes"})
LIMITE_FILAS_DEFECTO = 1000

RUTA_CSV_RAW = "data/pedidos_raw.csv"
RUTA_VISTAS = "sql/vistas.sql"

DESCRIPCION_ESQUEMA = """\
Base de datos DuckDB de solo lectura con estas relaciones:

pedidos(fecha DATE, cliente VARCHAR, pais VARCHAR, producto VARCHAR, importe DECIMAL(12,2), estado VARCHAR)
  Un pedido por fila. Estados posibles: completado, enviado, pendiente, cancelado.

ventas_por_mes_pais(mes DATE, pais VARCHAR, num_pedidos BIGINT, total_ventas DECIMAL)
  Vista: ventas mensuales por país (mes = primer día del mes), sin pedidos cancelados.

top_10_clientes(cliente VARCHAR, num_pedidos BIGINT, total_comprado DECIMAL)
  Vista: los 10 clientes que más han comprado, sin pedidos cancelados.
"""
