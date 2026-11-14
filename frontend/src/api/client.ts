import { ApiError, errorDeRed, errorDesdeRespuesta } from './errors'
import type {
  ConsultaPeticion,
  ConsultaRespuesta,
  TopCliente,
  VentaMesPais,
} from './types'

const URL_BASE_DEFECTO = 'http://localhost:8000'

/** Normaliza la URL base: valor vacío -> defecto; sin barra final. */
export function resolverUrlBase(valor: string | undefined): string {
  const limpio = (valor ?? '').trim()
  return (limpio === '' ? URL_BASE_DEFECTO : limpio).replace(/\/+$/, '')
}

export const URL_BASE = resolverUrlBase(import.meta.env.VITE_API_URL)

interface OpcionesPeticion {
  method?: 'GET' | 'POST'
  body?: unknown
  signal?: AbortSignal
}

async function leerJson(respuesta: Response): Promise<unknown> {
  try {
    return await respuesta.json()
  } catch {
    return undefined
  }
}

/** Único punto de acceso HTTP de la aplicación. */
async function peticion<T>(ruta: string, opciones: OpcionesPeticion = {}): Promise<T> {
  const { method = 'GET', body, signal } = opciones
  let respuesta: Response
  try {
    respuesta = await fetch(`${URL_BASE}${ruta}`, {
      method,
      signal,
      headers: {
        Accept: 'application/json',
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch (causa) {
    // Una cancelación voluntaria no es un fallo de red: se propaga tal cual.
    if ((causa as { name?: string } | null)?.name === 'AbortError') throw causa
    throw errorDeRed()
  }

  const cuerpo = await leerJson(respuesta)
  if (!respuesta.ok) throw errorDesdeRespuesta(respuesta.status, cuerpo)
  if (cuerpo === undefined) {
    throw new ApiError(
      { error: 'error_desconocido', mensaje: 'La respuesta del servidor no es JSON válido.' },
      respuesta.status,
    )
  }
  return cuerpo as T
}

export function obtenerVentasPorMesPais(pais?: string, signal?: AbortSignal): Promise<VentaMesPais[]> {
  const consulta = pais ? `?${new URLSearchParams({ pais }).toString()}` : ''
  return peticion<VentaMesPais[]>(`/ventas-por-mes-pais${consulta}`, { signal })
}

export function obtenerTopClientes(signal?: AbortSignal): Promise<TopCliente[]> {
  return peticion<TopCliente[]>('/top-clientes', { signal })
}

export function enviarConsulta(pregunta: string, signal?: AbortSignal): Promise<ConsultaRespuesta> {
  const cuerpo: ConsultaPeticion = { pregunta }
  return peticion<ConsultaRespuesta>('/consulta', { method: 'POST', body: cuerpo, signal })
}
