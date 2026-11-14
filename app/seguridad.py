"""Middlewares ASGI de seguridad: cabeceras, 500 genérico, límite de tasa y guarda de /consulta."""
import ipaddress
import logging
import math
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Collection, Hashable, Mapping

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
RUTA_CONSULTA = "/consulta"


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
        ruta: str = RUTA_CONSULTA,
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


# --- Limitación de tasa por IP ------------------------------------------------------------------


def _ip_valida(texto: str) -> str | None:
    """Normaliza una IP (v4 o v6) para usarla como clave; `None` si no es una IP.

    Una IPv6 se agrupa por su prefijo /64 (la asignación habitual a un solo cliente), para
    que rotar la parte baja de la dirección no evada el límite. Una IPv4 mapeada en IPv6
    (`::ffff:a.b.c.d`) cuenta como la IPv4. Se admite el sufijo `:puerto` en IPv4.
    """
    texto = texto.strip()
    try:
        ip = ipaddress.ip_address(texto)
    except ValueError:
        anfitrion, _, puerto = texto.rpartition(":")
        if not puerto.isdigit():
            return None
        try:
            ip = ipaddress.IPv4Address(anfitrion)
        except ValueError:
            return None
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.IPv6Network((ip, 64), strict=False))
    return str(ip)


def ip_cliente(scope: Scope, saltos_confianza: int = 0) -> str:
    """Clave de cliente de una petición HTTP, a prueba de `X-Forwarded-For` falsificado.

    `X-Forwarded-For` lo puede escribir cualquiera, así que por defecto (`saltos_confianza=0`)
    se ignora y se usa la IP del socket. Con N proxies de confianza (contando el último, el
    que tiene conectado el backend) cada uno añade al final de la cabecera la IP de su
    cliente, de modo que la dirección real es la N-ésima empezando por la derecha; lo que
    haya a su izquierda lo puede haber puesto el cliente y no se mira. Si la cabecera trae
    menos entradas de las esperadas (la petición no pasó por toda la cadena) o la entrada
    no es una IP, se usa la IP del socket.
    """
    par = scope.get("client")
    socket_ = par[0] if par else "desconocido"
    if saltos_confianza > 0:
        valores = Headers(scope=scope).getlist("x-forwarded-for")
        entradas = [e.strip() for v in valores for e in v.split(",") if e.strip()]
        if len(entradas) >= saltos_confianza:
            ip = _ip_valida(entradas[-saltos_confianza])
            if ip is not None:
                return ip
    return _ip_valida(socket_) or socket_


class LimitadorVentana:
    """Ventana deslizante en memoria: como mucho `limite` eventos por clave en `ventana` s.

    Memoria acotada: una lista de marcas de tiempo por clave (nunca más de `limite`) y como
    mucho `max_claves` claves; al llenarse se purgan las vencidas y, si no basta, se descarta
    la clave menos usada recientemente. Los rechazos no se registran, así que el cliente
    recupera el acceso exactamente `ventana` segundos después de su última petición admitida.
    El estado es por proceso: con varios workers cada uno lleva su propia cuenta.
    No usa awaits, por lo que en el bucle de eventos cada llamada es atómica.
    """

    def __init__(
        self,
        ventana: float = 60.0,
        max_claves: int = 10_000,
        reloj: Callable[[], float] = time.monotonic,
        intervalo_purga: float = 10.0,
    ) -> None:
        self.ventana = ventana
        self.max_claves = max_claves
        self._reloj = reloj
        self._intervalo_purga = intervalo_purga
        self._ultima_purga = reloj()
        self._marcas: OrderedDict[Hashable, deque[float]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._marcas)

    def _purgar(self, ahora: float) -> None:
        self._ultima_purga = ahora
        corte = ahora - self.ventana
        for clave in [c for c, m in self._marcas.items() if not m or m[-1] <= corte]:
            del self._marcas[clave]

    def intentar(self, clave: Hashable, limite: int) -> int | None:
        """Registra un evento. `None` si se admite; si no, los segundos (>= 1) hasta poder."""
        ahora = self._reloj()
        marcas = self._marcas.get(clave)
        if marcas is None:
            if len(self._marcas) >= self.max_claves:
                if ahora - self._ultima_purga >= self._intervalo_purga:
                    self._purgar(ahora)
                if len(self._marcas) >= self.max_claves:
                    self._marcas.popitem(last=False)
            marcas = self._marcas[clave] = deque()
        else:
            self._marcas.move_to_end(clave)
        corte = ahora - self.ventana
        while marcas and marcas[0] <= corte:
            marcas.popleft()
        if len(marcas) >= limite:
            return max(1, math.ceil(marcas[0] + self.ventana - ahora))
        marcas.append(ahora)
        return None


class MiddlewareLimiteTasa:
    """Limita las peticiones por IP: un cupo estricto para `POST <ruta_consulta>` y otro general.

    `POST /consulta` llama al LLM de pago, por eso tiene su propio cupo, mucho menor. El resto
    de rutas comparte el cupo general. Exentos: `OPTIONS` (preflight CORS) y `rutas_exentas`
    (`/health`, que usa el healthcheck de Docker). Se coloca DENTRO de CORS, para que el 429
    lleve cabeceras CORS y el navegador pueda leerlo, y FUERA de `GuardaCuerpoJSON`, para
    rechazar antes de leer el cuerpo. El 429 usa el cuerpo de error uniforme y `Retry-After`.
    """

    def __init__(
        self,
        app: ASGIApp,
        limite_general: int = 60,
        limite_consulta: int = 10,
        saltos_confianza: int = 0,
        ruta_consulta: str = RUTA_CONSULTA,
        rutas_exentas: Collection[str] = ("/health",),
        ventana: float = 60.0,
        max_claves: int = 10_000,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app = app
        self.limite_general = limite_general
        self.limite_consulta = limite_consulta
        self.saltos_confianza = saltos_confianza
        self.ruta_consulta = ruta_consulta
        self.rutas_exentas = frozenset(rutas_exentas)
        self.limitador = LimitadorVentana(ventana=ventana, max_claves=max_claves, reloj=reloj)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] == "OPTIONS"
            or scope["path"] in self.rutas_exentas
        ):
            await self.app(scope, receive, send)
            return

        if scope["method"] == "POST" and scope["path"] == self.ruta_consulta:
            cupo, limite = "consulta", self.limite_consulta
        else:
            cupo, limite = "general", self.limite_general
        espera = self.limitador.intentar((cupo, ip_cliente(scope, self.saltos_confianza)), limite)
        if espera is None:
            await self.app(scope, receive, send)
            return

        respuesta = respuesta_error(
            429,
            "demasiadas_peticiones",
            f"Demasiadas peticiones. Inténtalo de nuevo en {espera} segundos.",
        )
        respuesta.headers["Retry-After"] = str(espera)
        await respuesta(scope, receive, send)
