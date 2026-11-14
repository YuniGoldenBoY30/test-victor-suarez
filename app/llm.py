"""Cliente LLM: Protocol y la implementación para NVIDIA (API compatible con OpenAI)."""
import re
from typing import Any, Protocol

from openai import OpenAI

from app.errores import ErrorAplicacion
from app.prompt import construir_mensajes
from core.config import Settings


class LLMError(ErrorAplicacion):
    codigo = "llm_error"


class LLMNoConfiguradoError(LLMError):
    codigo = "llm_no_configurado"


class ClienteLLM(Protocol):
    def generar_sql(self, pregunta: str) -> str: ...


_VALLA = re.compile(r"^\s*```[a-zA-Z]*\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


def _quitar_vallas(texto: str) -> str:
    coincidencia = _VALLA.match(texto)
    return (coincidencia.group(1) if coincidencia else texto).strip()


class ClienteNvidia:
    def __init__(self, settings: Settings, cliente_openai: Any = None) -> None:
        self._settings = settings
        self._cliente = cliente_openai

    def _obtener_cliente(self) -> Any:
        if self._cliente is None:
            clave = self._settings.api_ia_nvidia
            if clave is None or not clave.get_secret_value().strip():
                raise LLMNoConfiguradoError("La clave del LLM no está configurada.")
            self._cliente = OpenAI(
                api_key=clave.get_secret_value(),
                base_url=self._settings.nvidia_base_url,
                timeout=self._settings.llm_timeout,
            )
        return self._cliente

    def generar_sql(self, pregunta: str) -> str:
        tipo_fallo: str | None = None
        contenido = None
        try:
            cliente = self._obtener_cliente()
            respuesta = cliente.chat.completions.create(
                model=self._settings.nvidia_model,
                messages=construir_mensajes(pregunta),
                temperature=0,
            )
            contenido = respuesta.choices[0].message.content
        except LLMError:
            raise
        except Exception as fallo:  # constructor del SDK, red o respuesta mal formada
            # Solo se conserva el nombre del tipo: ni el mensaje ni el objeto de la
            # excepción original (podrían contener la clave).
            tipo_fallo = type(fallo).__name__
        if tipo_fallo is not None:
            # Se lanza FUERA del bloque except: así no lleva __cause__ ni __context__
            # y el traceback no arrastra la excepción del SDK.
            raise LLMError(f"Error al consultar el modelo de lenguaje ({tipo_fallo}).")
        if not contenido or not contenido.strip():
            raise LLMError("El modelo de lenguaje devolvió una respuesta vacía.")
        sql = _quitar_vallas(contenido)
        if not sql:
            raise LLMError("El modelo de lenguaje devolvió una respuesta vacía.")
        return sql
