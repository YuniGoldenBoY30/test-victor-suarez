import type { CodigoError, CuerpoError } from './types'

/** Error del cliente de API; transporta {error, mensaje, sql?} y el estado HTTP. */
export class ApiError extends Error implements CuerpoError {
  readonly error: CodigoError
  readonly mensaje: string
  readonly sql?: string
  readonly status?: number

  constructor(cuerpo: { error: CodigoError; mensaje: string; sql?: string }, status?: number) {
    super(cuerpo.mensaje)
    this.name = 'ApiError'
    this.error = cuerpo.error
    this.mensaje = cuerpo.mensaje
    this.sql = cuerpo.sql
    this.status = status
  }
}

export function esApiError(valor: unknown): valor is ApiError {
  return valor instanceof ApiError
}

const CODIGOS_CONOCIDOS: ReadonlySet<string> = new Set<CodigoError>([
  'llm_no_configurado',
  'llm_error',
  'sql_no_valida',
  'error_ejecucion',
  'base_datos_no_disponible',
])

function esObjeto(valor: unknown): valor is Record<string, unknown> {
  return typeof valor === 'object' && valor !== null
}

/**
 * Convierte una respuesta HTTP no satisfactoria en un ApiError.
 * Admite el formato del contrato y el 422 por defecto de FastAPI ({detail: [...]}).
 */
export function errorDesdeRespuesta(status: number, cuerpo: unknown): ApiError {
  if (esObjeto(cuerpo) && typeof cuerpo.error === 'string' && CODIGOS_CONOCIDOS.has(cuerpo.error)) {
    return new ApiError(
      {
        error: cuerpo.error as CodigoError,
        mensaje: typeof cuerpo.mensaje === 'string' ? cuerpo.mensaje : '',
        sql: typeof cuerpo.sql === 'string' ? cuerpo.sql : undefined,
      },
      status,
    )
  }
  if (status === 422 && esObjeto(cuerpo) && 'detail' in cuerpo) {
    return new ApiError({ error: 'cuerpo_invalido', mensaje: 'La petición no es válida.' }, status)
  }
  return new ApiError(
    { error: 'error_desconocido', mensaje: `El servidor respondió con el estado ${status}.` },
    status,
  )
}

export function errorDeRed(): ApiError {
  return new ApiError({ error: 'error_red', mensaje: 'No se pudo contactar con el servidor.' })
}
