import { ApiError, errorDeRed, errorDesdeRespuesta } from './errors'
import type {
  ConsultaPeticion,
  ConsultaRespuesta,
  TopCliente,
  VentaMesPais,
} from './types'

const URL_BASE_DESARROLLO = 'http://localhost:8000'
/** En producción la API se sirve en el mismo origen (proxy), nunca en un host fijo. */
const URL_BASE_PRODUCCION = '/api'

/**
 * Valida y normaliza la URL base de la API (sin barra final).
 * Vacío -> localhost en desarrollo y `/api` en producción. Solo se admiten una
 * ruta absoluta del mismo origen (`/api`) o una URL http(s) sin credenciales.
 */
export function resolverUrlBase(
  valor: string | undefined,
  esDesarrollo: boolean = import.meta.env.DEV,
): string {
  const limpio = (valor ?? '').trim()
  if (limpio === '') return esDesarrollo ? URL_BASE_DESARROLLO : URL_BASE_PRODUCCION

  const invalida = () => new Error('VITE_API_URL no es válida: use una ruta como /api o una URL http(s).')

  if (limpio.startsWith('/')) {
    // '//host' y '/\\host' son URL relativas al protocolo: apuntan a otro origen.
    if (limpio.startsWith('//') || limpio.includes('\\')) throw invalida()
    return limpio.replace(/\/+$/, '')
  }

  let url: URL
  try {
    url = new URL(limpio)
  } catch {
    throw invalida()
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') throw invalida()
  if (url.username !== '' || url.password !== '') throw invalida()
  return limpio.replace(/\/+$/, '')
}

export const URL_BASE = resolverUrlBase(import.meta.env.VITE_API_URL)

/** Una base relativa es del mismo origen; una absoluta exige CORS. */
export function modoPeticion(base: string): 'same-origin' | 'cors' {
  return base.startsWith('/') ? 'same-origin' : 'cors'
}

interface OpcionesPeticion {
  method?: 'GET' | 'POST'
  body?: unknown
  signal?: AbortSignal
}

function esJson(respuesta: Response): boolean {
  const tipo = (respuesta.headers.get('Content-Type') ?? '').split(';')[0]?.trim().toLowerCase() ?? ''
  return tipo === 'application/json' || /^application\/[\w.+-]+\+json$/.test(tipo)
}

async function leerJson(respuesta: Response): Promise<unknown> {
  // Un cuerpo que no declara JSON no se interpreta.
  if (!esJson(respuesta)) return undefined
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
      mode: modoPeticion(URL_BASE),
      credentials: 'omit',
      referrerPolicy: 'no-referrer',
      cache: 'no-store',
      redirect: 'error',
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
