"""Fábrica de la API FastAPI: dashboard (vistas) y consultas en lenguaje natural."""
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.dependencias import get_repositorio, get_servicio, get_settings
from app.errores import BaseDatosNoDisponibleError, ErrorAplicacion, ErrorEjecucionSQL
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
    RUTA_CONSULTA,
    GuardaCuerpoJSON,
    MiddlewareLimiteTasa,
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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    docs = settings.api_docs
    app = FastAPI(
        title="Consultas de pedidos en lenguaje natural",
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    # add_middleware antepone: el último añadido es el más externo.
    # Orden externo -> interno: seguridad -> hosts de confianza -> CORS -> límite de tasa
    # -> guarda de /consulta. El límite va dentro de CORS (el 429 lleva cabeceras CORS) y
    # fuera de la guarda (se rechaza antes de leer el cuerpo).
    app.add_middleware(GuardaCuerpoJSON, ruta=RUTA_CONSULTA)
    if settings.rate_limit_enabled:
        app.add_middleware(
            MiddlewareLimiteTasa,
            limite_general=settings.rate_limit_rpm,
            limite_consulta=settings.rate_limit_consulta_rpm,
            saltos_confianza=settings.rate_limit_trusted_hops,
            ruta_consulta=RUTA_CONSULTA,
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Accept"],
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
        cuerpo: ConsultaEntrada,
        servicio: ServicioConsultas = Depends(get_servicio),
    ):
        r = servicio.consultar(cuerpo.pregunta)
        return ConsultaSalida(
            pregunta=r.pregunta, sql=r.sql, columnas=r.columnas, filas=r.filas
        )

    return app
