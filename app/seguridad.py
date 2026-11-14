"""Middlewares ASGI de seguridad: cabeceras, 500 genérico y guarda de cuerpo de /consulta."""
import logging
from collections.abc import Mapping

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

CSP_API = "default-src 'none'; frame-ancestors 'none'"
# Solo para /docs y /redoc cuando API_DOCS está activo (cargan Swagger UI y ReDoc de un CDN).
CSP_DOCS = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "connect-src 'self'; worker-src blob:; frame-ancestors 'none'"
)
CABECERAS_SEGURIDAD = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

MAX_CUERPO_CONSULTA = 8192


def respuesta_error(
    estado: int, codigo: str, mensaje: str, sql: str | None = None
) -> JSONResponse:
    """Cuerpo de error uniforme de la API: {"error", "mensaje"[, "sql"]}."""
    cuerpo = {"error": codigo, "mensaje": mensaje}
    if sql is not None:
        cuerpo["sql"] = sql
    return JSONResponse(status_code=estado, content=cuerpo)


class MiddlewareSeguridad:
    """Añade las cabeceras de seguridad a TODA respuesta y convierte los fallos en 500 genérico.

    Debe ser el middleware más externo. Starlette coloca su ServerErrorMiddleware por fuera
    de los middlewares de usuario, así que un handler de `Exception` daría un 500 sin
    cabeceras; por eso este middleware captura la excepción él mismo.
    """

    def __init__(self, app: ASGIApp, csp_por_ruta: Mapping[str, str] | None = None) -> None:
        self.app = app
        self.csp_por_ruta = dict(csp_por_ruta or {})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        csp = self.csp_por_ruta.get(scope["path"], CSP_API)
        iniciada = False

        async def enviar(mensaje: Message) -> None:
            nonlocal iniciada
            if mensaje["type"] == "http.response.start":
                iniciada = True
                cabeceras = MutableHeaders(scope=mensaje)
                for nombre, valor in CABECERAS_SEGURIDAD.items():
                    cabeceras[nombre] = valor
                cabeceras["Content-Security-Policy"] = csp
            await send(mensaje)

        try:
            await self.app(scope, receive, enviar)
        except Exception:
            # Solo al log del servidor: nada de traza, clase ni mensaje hacia el cliente.
            logger.exception("Error no controlado en %s %s", scope["method"], scope["path"])
            if iniciada:
                raise
            respuesta = respuesta_error(500, "error_interno", "Error interno del servidor.")
            await respuesta(scope, receive, enviar)


class GuardaCuerpoJSON:
    """Para `POST <ruta>`: exige `application/json` (415) y limita el cuerpo (413).

    El límite se aplica con `Content-Length` (sin leer el cuerpo) y también contando los
    bytes recibidos cuando no hay `Content-Length` (chunked). El cuerpo ya leído, pequeño
    por construcción, se reenvía a la aplicación. Se coloca DENTRO de CORS para que el
    413/415 lleve las cabeceras CORS; el preflight OPTIONS no llega hasta aquí.
    """

    def __init__(
        self,
        app: ASGIApp,
        ruta: str = "/consulta",
        max_bytes: int = MAX_CUERPO_CONSULTA,
    ) -> None:
        self.app = app
        self.ruta = ruta
        self.max_bytes = max_bytes

    def _demasiado_grande(self) -> JSONResponse:
        return respuesta_error(
            413,
            "cuerpo_demasiado_grande",
            f"El cuerpo de la petición supera el máximo de {self.max_bytes} bytes.",
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != self.ruta:
            await self.app(scope, receive, send)
            return

        cabeceras = Headers(scope=scope)
        tipo = cabeceras.get("content-type", "").split(";", 1)[0].strip().lower()
        if tipo != "application/json":
            respuesta = respuesta_error(
                415,
                "tipo_contenido_no_soportado",
                "El Content-Type debe ser application/json.",
            )
            await respuesta(scope, receive, send)
            return

        declarado = cabeceras.get("content-length", "")
        if declarado.isascii() and declarado.isdigit() and int(declarado) > self.max_bytes:
            await self._demasiado_grande()(scope, receive, send)
            return

        # Sin Content-Length fiable (chunked) se cuenta lo recibido, sin pasar del límite.
        cuerpo = bytearray()
        while True:
            mensaje = await receive()
            if mensaje["type"] != "http.request":
                return  # el cliente se fue: no hay a quién responder
            cuerpo += mensaje.get("body", b"")
            if len(cuerpo) > self.max_bytes:
                await self._demasiado_grande()(scope, receive, send)
                return
            if not mensaje.get("more_body", False):
                break

        entregado = False

        async def reproducir() -> Message:
            nonlocal entregado
            if not entregado:
                entregado = True
                return {"type": "http.request", "body": bytes(cuerpo), "more_body": False}
            return await receive()

        await self.app(scope, reproducir, send)
