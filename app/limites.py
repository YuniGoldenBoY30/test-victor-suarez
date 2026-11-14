"""Límites de uso de POST /consulta: por cliente (minuto y hora) y tope diario global.

Sin dependencias de FastAPI. El estado vive en memoria y está protegido por un cerrojo:
vale para un único proceso (el despliegue actual: un worker de uvicorn). Con varios
workers o varias réplicas cada proceso contaría por su cuenta y haría falta un almacén
compartido (por ejemplo Redis), que queda fuera de alcance.
"""
import ipaddress
import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence

from app.errores import ErrorAplicacion

logger = logging.getLogger(__name__)

SEGUNDOS_MINUTO = 60
SEGUNDOS_HORA = 3600
SEGUNDOS_DIA = 86400

CODIGO_LIMITE_PETICIONES = "limite_peticiones"
CODIGO_LIMITE_DIARIO = "limite_diario"

# Clave de reserva cuando ni la cabecera ni la conexión TCP dan una dirección.
CLIENTE_DESCONOCIDO = "desconocido"


class LimiteExcedidoError(ErrorAplicacion):
    """Se superó un límite; `reintentar_en` son los segundos enteros (>= 1) del Retry-After."""

    def __init__(self, codigo: str, mensaje: str, reintentar_en: int) -> None:
        super().__init__(mensaje)
        self.codigo = codigo
        self.reintentar_en = reintentar_en


def _segundos_enteros(segundos: float) -> int:
    return max(1, math.ceil(segundos))


def normalizar_cliente(direccion: str) -> str:
    """Clave de contabilidad de un cliente.

    IPv4 y IPv6 se devuelven en forma canónica; una IPv4 mapeada en IPv6 cuenta como la IPv4,
    y una IPv6 se agrupa por su prefijo /64 (rotar dentro de un /64 no da cuota nueva). Un
    texto que no es una IP (p. ej. el cliente de un socket Unix) se usa tal cual.
    """
    try:
        ip = ipaddress.ip_address(direccion.strip())
    except ValueError:
        return direccion
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.IPv6Network((ip, 64), strict=False))
    return str(ip)


def resolver_ip_cliente(peer: str | None, valores_cabecera: Sequence[str] = ()) -> str:
    """Clave del cliente de una petición.

    `valores_cabecera` son los valores de la cabecera de IP configurada (vacío si no hay
    cabecera configurada o no vino). Solo se confía en ella si llega UN valor y es una
    dirección IP válida; en cualquier otro caso (ausente, repetida, con comas, texto
    arbitrario) se usa la IP de la conexión TCP (`peer`). Nunca se interpreta
    X-Forwarded-For: lo puede escribir el cliente.
    """
    if len(valores_cabecera) == 1:
        valor = valores_cabecera[0].strip()
        try:
            ipaddress.ip_address(valor)
        except ValueError:
            pass
        else:
            return normalizar_cliente(valor)
    if peer:
        return normalizar_cliente(peer)
    return CLIENTE_DESCONOCIDO


class LimitadorConsultas:
    """Ventana deslizante por cliente (minuto y hora) y contador global por día UTC.

    Un límite en 0 lo desactiva. `registrar` comprueba y, solo si todo pasa, anota la
    petición: las rechazadas no consumen cuota ni alargan el bloqueo. Primero se mira el
    límite del cliente y después el diario, de modo que quien abusa recibe su propio 429
    y no agota el tope global con intentos rechazados. `reloj` devuelve segundos epoch (UTC).
    """

    def __init__(
        self,
        por_minuto: int = 10,
        por_hora: int = 60,
        por_dia: int = 500,
        reloj: Callable[[], float] = time.time,
    ) -> None:
        for nombre, valor in (("por_minuto", por_minuto), ("por_hora", por_hora), ("por_dia", por_dia)):
            if not isinstance(valor, int) or isinstance(valor, bool) or valor < 0:
                raise ValueError(f"{nombre} debe ser un entero no negativo, no {valor!r}")
        self.por_minuto = por_minuto
        self.por_hora = por_hora
        self.por_dia = por_dia
        self._reloj = reloj
        # Ventana más larga que hace falta recordar por cliente.
        self._retencion = SEGUNDOS_HORA if por_hora else SEGUNDOS_MINUTO
        self._cerrojo = threading.Lock()
        self._marcas: dict[str, deque[float]] = {}
        self._dia = int(reloj() // SEGUNDOS_DIA)
        self._usadas_dia = 0
        self._proxima_purga = reloj() + SEGUNDOS_MINUTO

    @staticmethod
    def _espera(marcas: deque[float], ahora: float, ventana: int, limite: int) -> float:
        """Segundos hasta poder anotar otra marca en esa ventana (0 si ya se puede)."""
        if not limite:
            return 0.0
        recientes = [t for t in marcas if t > ahora - ventana]
        if len(recientes) < limite:
            return 0.0
        return recientes[len(recientes) - limite] + ventana - ahora

    def _podar(self, marcas: deque[float], ahora: float) -> None:
        while marcas and marcas[0] <= ahora - self._retencion:
            marcas.popleft()

    def _purgar(self, ahora: float) -> None:
        """Olvida los clientes sin actividad reciente para que el diccionario no crezca."""
        if ahora < self._proxima_purga:
            return
        self._proxima_purga = ahora + SEGUNDOS_MINUTO
        for cliente in list(self._marcas):
            marcas = self._marcas[cliente]
            self._podar(marcas, ahora)
            if not marcas:
                del self._marcas[cliente]

    def registrar(self, cliente: str) -> None:
        """Anota una consulta del cliente o lanza LimiteExcedidoError sin anotar nada."""
        with self._cerrojo:
            ahora = self._reloj()
            self._purgar(ahora)

            marcas = self._marcas.get(cliente)
            if marcas is None:
                marcas = deque()
            else:
                self._podar(marcas, ahora)
            espera = max(
                self._espera(marcas, ahora, SEGUNDOS_MINUTO, self.por_minuto),
                self._espera(marcas, ahora, SEGUNDOS_HORA, self.por_hora),
            )
            if espera > 0:
                segundos = _segundos_enteros(espera)
                logger.warning("Límite de consultas por cliente superado (cliente=%s)", cliente)
                raise LimiteExcedidoError(
                    CODIGO_LIMITE_PETICIONES,
                    "Demasiadas consultas desde su dirección. "
                    f"Vuelva a intentarlo en {segundos} segundos.",
                    segundos,
                )

            dia = int(ahora // SEGUNDOS_DIA)
            if dia != self._dia:
                self._dia, self._usadas_dia = dia, 0
            if self.por_dia and self._usadas_dia >= self.por_dia:
                segundos = _segundos_enteros((dia + 1) * SEGUNDOS_DIA - ahora)
                logger.warning("Tope diario global de consultas alcanzado")
                raise LimiteExcedidoError(
                    CODIGO_LIMITE_DIARIO,
                    "Se alcanzó el límite diario de consultas del servicio. "
                    "Vuelva a intentarlo mañana.",
                    segundos,
                )

            self._usadas_dia += 1
            if self.por_minuto or self.por_hora:
                marcas.append(ahora)
                self._marcas[cliente] = marcas
