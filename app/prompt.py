"""Construcción del prompt para el LLM, solo a partir de constantes de core.esquema."""
from core.esquema import (
    DESCRIPCION_ESQUEMA,
    ESTADOS,
    FECHA_MAX,
    FECHA_MIN,
    LIMITE_FILAS_DEFECTO,
    PAISES,
)


def construir_mensajes(pregunta: str) -> list[dict[str, str]]:
    """Devuelve los mensajes (sistema + usuario) para generar un único SELECT de DuckDB."""
    sistema = (
        "Eres un asistente que traduce preguntas en español a SQL de DuckDB.\n"
        f"{DESCRIPCION_ESQUEMA}\n"
        f"Valores canónicos de pais: {', '.join(PAISES)}.\n"
        f"Valores de estado: {', '.join(ESTADOS)}.\n"
        f"Los datos cubren desde {FECHA_MIN.isoformat()} hasta {FECHA_MAX.isoformat()}.\n"
        "Si la pregunta menciona un mes sin año, considera todos los años del rango "
        "(no asumas uno solo).\n"
        "Reglas: responde únicamente con UNA sentencia SELECT, sin explicaciones ni "
        "bloques markdown; usa solo las relaciones indicadas; nunca modifiques datos; "
        f"limita el resultado a {LIMITE_FILAS_DEFECTO} filas como máximo."
    )
    return [
        {"role": "system", "content": sistema},
        {"role": "user", "content": pregunta},
    ]
