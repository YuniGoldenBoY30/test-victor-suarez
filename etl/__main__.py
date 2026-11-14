"""CLI: python -m etl [--csv RUTA] [--db RUTA] [--si-falta]"""
import argparse
import csv
import sys
from pathlib import Path

from core.config import get_settings
from core.esquema import RUTA_CSV_RAW
from etl.carga import cargar_duckdb
from etl.limpieza import limpiar_filas


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m etl", description="Limpia el CSV y carga DuckDB.")
    ap.add_argument("--csv", default=RUTA_CSV_RAW, help="CSV de pedidos sucio")
    ap.add_argument("--db", default=None, help="ruta del archivo DuckDB (por defecto DUCKDB_PATH)")
    ap.add_argument("--si-falta", action="store_true", help="solo construir si la base no existe")
    args = ap.parse_args(argv)

    db = Path(args.db or get_settings().duckdb_path)
    if args.si_falta and db.exists():
        print(f"La base {db} ya existe; no se reconstruye.")
        return 0
    with open(args.csv, newline="", encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    limpias, informe = limpiar_filas(filas)
    cargadas = cargar_duckdb(limpias, db)
    for clave, valor in informe.items():
        print(f"{clave}: {valor}")
    print(f"Cargadas {cargadas} filas en {db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
