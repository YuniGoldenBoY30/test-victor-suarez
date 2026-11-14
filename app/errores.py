"""Errores de dominio de la capa de datos (sin dependencias de FastAPI)."""


class ErrorAplicacion(Exception):
    """Base: lleva un código estable y un mensaje en español."""

    codigo = "error"

    def __init__(self, mensaje: str) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje


class BaseDatosNoDisponibleError(ErrorAplicacion):
    codigo = "base_datos_no_disponible"


class ErrorEjecucionSQL(ErrorAplicacion):
    codigo = "error_ejecucion"
