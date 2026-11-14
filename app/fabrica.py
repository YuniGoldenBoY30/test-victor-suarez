"""Fábrica de la API FastAPI: dashboard (vistas) y consultas en lenguaje natural."""
import time
from collections.abc import Callable

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.dependencias import get_repositorio, get_servicio, get_settings
from app.errores import BaseDatosNoDisponibleError, ErrorAplicacion, ErrorEjecucionSQL
from app.limites import (
    LimiteExcedidoError,
    LimitadorConsultas,
    resolver_ip_cliente,
)
from app.llm import LLMError, LLMNoConfiguradoError
from app.modelos import (
    ConsultaEntrada,
    ConsultaSalida,
    Salud,
    TopCliente,
    VentaMesPais,
)
from app.repositorio_vistas import RepositorioVistas
from app.seguridad import (
    CSP_DOCS,
    GuardaCuerpoJSON,
    MiddlewareSeguridad,
    respuesta_error as _respuesta_error,
)
from app.servicio import ServicioConsultas
from app.validador_sql import SQLNoPermitidoError
from core.config import Settings

# Orden: subclases antes que su base (LLMNoConfiguradoError hereda de LLMError).
_ESTADOS = {
    LLMNoConfiguradoError: 503,
    LLMError: 502,
    ErrorEjecucionSQL: 422,
    BaseDatosNoDisponibleError: 503,
}


def _manejar_aplicacion(_: Request, exc: ErrorAplicacion):
    estado = next((e for t, e in _ESTADOS.items() if isinstance(exc, t)), 500)
    return _respuesta_error(estado, exc.codigo, exc.mensaje)


def _manejar_sql(_: Request, exc: SQLNoPermitidoError):
    return _respuesta_error(422, exc.codigo, exc.mensaje, getattr(exc, "sql", None))


def _manejar_limite(_: Request, exc: LimiteExcedidoError):
    return _respuesta_error(
        429, exc.codigo, exc.mensaje, cabeceras={"Retry-After": str(exc.reintentar_en)}
    )


def create_app(
    settings: Settings | None = None, reloj: Callable[[], float] = time.time
) -> FastAPI:
    """`reloj` (segundos epoch UTC) solo se inyecta en tests para controlar los límites."""
    settings = settings or get_settings()
    limitador = LimitadorConsultas(
        settings.limite_consultas_minuto,
        settings.limite_consultas_hora,
        settings.limite_consultas_dia,
        reloj=reloj,
    )
    cabecera_ip = settings.cabecera_ip_cliente
    docs = settings.api_docs
    app = FastAPI(
        title="Consultas de pedidos en lenguaje natural",
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    # add_middleware antepone: el último añadido es el más externo.
    # Orden externo -> interno: seguridad -> hosts de confianza -> CORS -> guarda de /consulta.
    app.add_middleware(GuardaCuerpoJSON, ruta="/consulta")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Accept"],
        expose_headers=["Retry-After"],
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts, www_redirect=False
    )
    app.add_middleware(
        MiddlewareSeguridad,
        csp_por_ruta={"/docs": CSP_DOCS, "/redoc": CSP_DOCS} if docs else None,
    )
    app.add_exception_handler(ErrorAplicacion, _manejar_aplicacion)
    app.add_exception_handler(SQLNoPermitidoError, _manejar_sql)
    app.add_exception_handler(LimiteExcedidoError, _manejar_limite)

    @app.get("/health", response_model=Salud)
    def health():
        return Salud()

    @app.get("/ventas-por-mes-pais", response_model=list[VentaMesPais])
    def ventas_por_mes_pais(
        pais: str | None = None,
        repositorio: RepositorioVistas = Depends(get_repositorio),
    ):
        return repositorio.ventas_por_mes_pais(pais)

    @app.get("/top-clientes", response_model=list[TopCliente])
    def top_clientes(repositorio: RepositorioVistas = Depends(get_repositorio)):
        return repositorio.top_10_clientes()

    @app.post("/consulta", response_model=ConsultaSalida)
    def consulta(
        request: Request,
        cuerpo: ConsultaEntrada,
        servicio: ServicioConsultas = Depends(get_servicio),
    ):
        # Tras validar el cuerpo (los 422 no gastan cuota; 413/415 ya los cortó el middleware)
        # y antes de llamar al LLM: una petición rechazada por límite nunca llega a NVIDIA.
        valores = request.headers.getlist(cabecera_ip) if cabecera_ip else []
        peer = request.client.host if request.client else None
        limitador.registrar(resolver_ip_cliente(peer, valores))
        r = servicio.consultar(cuerpo.pregunta)
        return ConsultaSalida(
            pregunta=r.pregunta, sql=r.sql, columnas=r.columnas, filas=r.filas
        )

    return app
