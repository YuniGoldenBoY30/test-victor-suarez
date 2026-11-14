import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  enviarConsulta,
  obtenerTopClientes,
  obtenerVentasPorMesPais,
  resolverUrlBase,
  URL_BASE,
} from './index'

function respuestaJson(cuerpo: unknown, status = 200): Response {
  return new Response(JSON.stringify(cuerpo), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const fetchSimulado = vi.fn<typeof fetch>()

afterEach(() => {
  fetchSimulado.mockReset()
  vi.unstubAllGlobals()
})

function simularFetch(respuesta: Response | Error | DOMException) {
  if (respuesta instanceof Response) fetchSimulado.mockResolvedValue(respuesta)
  else fetchSimulado.mockRejectedValue(respuesta)
  vi.stubGlobal('fetch', fetchSimulado)
}

describe('resolverUrlBase', () => {
  it('usa el valor por defecto si no hay variable o está vacía', () => {
    expect(resolverUrlBase(undefined)).toBe('http://localhost:8000')
    expect(resolverUrlBase('  ')).toBe('http://localhost:8000')
  })

  it('quita la barra final y admite rutas relativas (Docker)', () => {
    expect(resolverUrlBase('/api/')).toBe('/api')
    expect(resolverUrlBase('http://api.local:9000//')).toBe('http://api.local:9000')
  })
})

describe('cliente de API', () => {
  it('pide las ventas sin filtro a /ventas-por-mes-pais', async () => {
    const filas = [{ mes: '2024-03-01', pais: 'España', num_pedidos: 3, total_ventas: 120.5 }]
    simularFetch(respuestaJson(filas))

    await expect(obtenerVentasPorMesPais()).resolves.toEqual(filas)
    expect(fetchSimulado.mock.calls[0]?.[0]).toBe(`${URL_BASE}/ventas-por-mes-pais`)
  })

  it('codifica el país en la consulta', async () => {
    simularFetch(respuestaJson([]))
    await obtenerVentasPorMesPais('Estados Unidos')
    expect(fetchSimulado.mock.calls[0]?.[0]).toBe(`${URL_BASE}/ventas-por-mes-pais?pais=Estados+Unidos`)
  })

  it('pide el top de clientes', async () => {
    const filas = [{ cliente: 'Ana', num_pedidos: 2, total_comprado: 99 }]
    simularFetch(respuestaJson(filas))
    await expect(obtenerTopClientes()).resolves.toEqual(filas)
    expect(fetchSimulado.mock.calls[0]?.[0]).toBe(`${URL_BASE}/top-clientes`)
  })

  it('envía la pregunta por POST con cuerpo JSON', async () => {
    const respuesta = { pregunta: 'p', sql: 'SELECT 1', columnas: ['x'], filas: [[1]] }
    simularFetch(respuestaJson(respuesta))

    await expect(enviarConsulta('p')).resolves.toEqual(respuesta)
    const [url, init] = fetchSimulado.mock.calls[0]!
    expect(url).toBe(`${URL_BASE}/consulta`)
    expect(init?.method).toBe('POST')
    expect(init?.body).toBe(JSON.stringify({ pregunta: 'p' }))
    expect(new Headers(init?.headers).get('Content-Type')).toBe('application/json')
  })
})

describe('errores del cliente', () => {
  it.each([
    ['llm_no_configurado', 503],
    ['llm_error', 502],
    ['sql_no_valida', 422],
    ['error_ejecucion', 422],
    ['base_datos_no_disponible', 503],
  ] as const)('conserva el código %s del contrato', async (codigo, status) => {
    simularFetch(respuestaJson({ error: codigo, mensaje: 'Mensaje en español', sql: 'DROP TABLE x' }, status))

    const error = await enviarConsulta('hola').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ error: codigo, mensaje: 'Mensaje en español', sql: 'DROP TABLE x', status })
  })

  it('traduce el 422 por defecto de FastAPI a cuerpo_invalido', async () => {
    simularFetch(respuestaJson({ detail: [{ loc: ['body', 'pregunta'], msg: 'too short' }] }, 422))
    await expect(enviarConsulta('')).rejects.toMatchObject({ error: 'cuerpo_invalido', status: 422 })
  })

  it('traduce un fallo de red a error_red', async () => {
    simularFetch(new TypeError('Failed to fetch'))
    await expect(obtenerTopClientes()).rejects.toMatchObject({ error: 'error_red' })
  })

  it('usa error_desconocido ante un código o cuerpo inesperado', async () => {
    simularFetch(new Response('<html>boom</html>', { status: 500 }))
    await expect(obtenerTopClientes()).rejects.toMatchObject({ error: 'error_desconocido', status: 500 })
  })

  it('no confunde una cancelación con un fallo de red', async () => {
    simularFetch(new DOMException('Cancelado', 'AbortError'))
    await expect(obtenerTopClientes()).rejects.toMatchObject({ name: 'AbortError' })
  })
})
