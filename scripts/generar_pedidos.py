"""Genera data/pedidos_raw.csv: pedidos sucios con errores deliberados y semilla fija."""
import csv
import random
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from core.esquema import (  # noqa: E402
    COLUMNAS_CSV,
    ESTADOS,
    FECHA_MAX,
    FECHA_MIN,
    FORMATOS_FECHA,
    PAISES,
    RUTA_CSV_RAW,
    VARIANTES_PAIS,
)

SEMILLA = 42
N_PEDIDOS = 1000
PROB_FECHA_IMPOSIBLE = 0.03
PROB_IMPORTE_VACIO = 0.02
PROB_DUPLICADO = 0.05
PROB_PAIS_VARIANTE = 0.2
PROB_COMA_DECIMAL = 0.1

FECHAS_IMPOSIBLES = ["2024-02-30", "31/04/2024", "2024-13-05", "15-13-2024"]


def _pedido(rng: random.Random, contadores: Counter) -> dict:
    dias = (FECHA_MAX - FECHA_MIN).days
    dia = FECHA_MIN + timedelta(days=rng.randrange(dias + 1))
    formato = rng.choice(FORMATOS_FECHA)
    fecha = dia.strftime(formato)
    contadores[f"formato_fecha {formato}"] += 1

    if rng.random() < PROB_PAIS_VARIANTE:
        variante = rng.choice(list(VARIANTES_PAIS))
        pais = variante.upper() if rng.random() < 0.5 else f"  {variante} "
        contadores["pais_variante"] += 1
    else:
        pais = rng.choice(PAISES)

    importe = f"{rng.uniform(10, 2000):.2f}"
    if rng.random() < PROB_COMA_DECIMAL:
        importe = importe.replace(".", ",")
        contadores["importe_coma_decimal"] += 1

    return {
        "fecha": fecha,
        "cliente": f"Cliente {rng.randint(1, 200):03d}",
        "pais": pais,
        "producto": f"PROD-{rng.randint(1, 50):03d}",
        "importe": importe,
        "estado": rng.choice(ESTADOS),
    }


def generar_filas(n: int = N_PEDIDOS, semilla: int = SEMILLA) -> list[dict]:
    """Devuelve n pedidos sucios (más duplicados exactos) con semilla fija."""
    filas, _ = _generar(n, semilla)
    return filas


def _generar(n: int, semilla: int) -> tuple[list[dict], Counter]:
    rng = random.Random(semilla)
    contadores: Counter = Counter()
    filas = []
    for _ in range(n):
        fila = _pedido(rng, contadores)
        r = rng.random()
        if r < PROB_FECHA_IMPOSIBLE:
            fila["fecha"] = rng.choice(FECHAS_IMPOSIBLES)
            contadores["fecha_imposible"] += 1
        elif r < PROB_FECHA_IMPOSIBLE + PROB_IMPORTE_VACIO:
            fila["importe"] = ""
            contadores["importe_vacio"] += 1
        filas.append(fila)

    for _ in range(int(n * PROB_DUPLICADO)):
        filas.append(dict(rng.choice(filas)))
        contadores["duplicado_exacto"] += 1

    rng.shuffle(filas)
    return filas, contadores


def main(ruta: Path | None = None) -> Path:
    destino = Path(ruta) if ruta is not None else RAIZ / RUTA_CSV_RAW
    filas, contadores = _generar(N_PEDIDOS, SEMILLA)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUMNAS_CSV)
        escritor.writeheader()
        escritor.writerows(filas)

    print(f"Escritas {len(filas)} filas en {destino}")
    for clave in sorted(contadores):
        print(f"  {clave}: {contadores[clave]}")
    return destino


if __name__ == "__main__":
    main()
