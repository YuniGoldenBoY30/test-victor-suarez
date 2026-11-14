import { esApiError, type CodigoError } from '../api'

export interface MensajeError {
  titulo: string
  /** Qué ha pasado y qué puede hacer la persona. */
  ayuda: string
  /** Se puede reintentar con la misma petición. */
  reintentable: boolean
}

/** Mensaje en español para cada código de error (contrato + errores del cliente). */
export const MENSAJES_ERROR: Record<CodigoError, MensajeError> = {
  llm_no_configurado: {
    titulo: 'El asistente de IA no está configurado',
    ayuda:
      'Falta la clave de NVIDIA en el servidor. Define API_IA_NVIDIA en el archivo .env y reinicia el backend. El dashboard sigue funcionando.',
    reintentable: false,
  },
  llm_error: {
    titulo: 'El asistente de IA no ha respondido',
    ayuda: 'El modelo de lenguaje falló o tardó demasiado. Vuelve a intentarlo en unos segundos.',
    reintentable: true,
  },
  sql_no_valida: {
    titulo: 'La consulta generada no es válida',
    ayuda:
      'El SQL que propuso el asistente no cumple las reglas de seguridad: solo se permite leer pedidos y las vistas aprobadas. No se ha ejecutado nada. Reformula la pregunta.',
    reintentable: false,
  },
  error_ejecucion: {
    titulo: 'No se pudo ejecutar la consulta',
    ayuda: 'La base de datos rechazó el SQL generado. Prueba a reformular la pregunta con otras palabras.',
    reintentable: false,
  },
  base_datos_no_disponible: {
    titulo: 'La base de datos no está disponible',
    ayuda: 'El backend no encuentra la base de datos. Ejecuta python -m etl para crearla y vuelve a intentarlo.',
    reintentable: true,
  },
  cuerpo_invalido: {
    titulo: 'La pregunta no es válida',
    ayuda: 'Debe tener entre 1 y 500 caracteres.',
    reintentable: false,
  },
  error_red: {
    titulo: 'No se pudo conectar con el servidor',
    ayuda:
      'Comprueba que el backend está en marcha y que la dirección de la API es correcta. Después, vuelve a intentarlo.',
    reintentable: true,
  },
  error_desconocido: {
    titulo: 'Ha ocurrido un error inesperado',
    ayuda: 'Vuelve a intentarlo. Si persiste, revisa los registros del backend.',
    reintentable: true,
  },
}

export interface ErrorPresentado extends MensajeError {
  codigo: CodigoError
  /** Mensaje original del servidor, si aporta algo. */
  detalle?: string
  sql?: string
}

/** Traduce cualquier excepción a lo que se muestra en pantalla. */
export function presentarError(error: unknown): ErrorPresentado {
  if (esApiError(error)) {
    return {
      ...MENSAJES_ERROR[error.error],
      codigo: error.error,
      detalle: error.mensaje || undefined,
      sql: error.sql,
    }
  }
  return { ...MENSAJES_ERROR.error_desconocido, codigo: 'error_desconocido' }
}
