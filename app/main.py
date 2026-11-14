"""Punto de entrada de uvicorn: `uvicorn app.main:app`."""
from app.fabrica import create_app

app = create_app()
