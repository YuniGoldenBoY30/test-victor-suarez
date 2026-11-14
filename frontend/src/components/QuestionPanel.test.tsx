import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { QuestionPanel, PREGUNTAS_EJEMPLO } from './QuestionPanel'
import { ErrorNotice } from './ErrorNotice'
import { MENSAJES_ERROR, presentarError } from '../lib/mensajesError'
import { ApiError } from '../api'

function respuestaJson(cuerpo: unknown, status = 200): Response {
  return new Response(JSON.stringify(cuerpo), { status, headers: { 'Content-Type': 'application/json' } })
}

const fetchSimulado = vi.fn<typeof fetch>()

function simular(respuesta: Response | Error) {
  if (respuesta instanceof Response) fetchSimulado.mockResolvedValue(respuesta)
  else fetchSimulado.mockRejectedValue(respuesta)
  vi.stubGlobal('fetch', fetchSimulado)
}

afterEach(() => {
  fetchSimulado.mockReset()
  vi.unstubAllGlobals()
})

describe('QuestionPanel', () => {
  it('muestra el SQL generado y una tabla dinámica con la respuesta', async () => {
    simular(
      respuestaJson({
        pregunta: '¿Cuánto vendimos en España en marzo de 2024?',
        sql: "SELECT SUM(total_ventas) AS total FROM ventas_por_mes_pais WHERE pais = 'España' LIMIT 1000",
        columnas: ['mes', 'total'],
        filas: [['2024-03-01', 12345.67]],
      }),
    )
    const usuario = userEvent.setup()
    render(<QuestionPanel />)

    await usuario.type(screen.getByLabelText('Tu pregunta'), '¿Cuánto vendimos en España en marzo de 2024?')
    await usuario.click(screen.getByRole('button', { name: 'Preguntar' }))

    expect(await screen.findByText(/SELECT SUM\(total_ventas\)/)).toBeInTheDocument()
    const tabla = screen.getByRole('table', { name: /Resultado: 1 fila y 2 columnas/ })
    expect(within(tabla).getByRole('columnheader', { name: 'total' })).toBeInTheDocument()
    expect(within(tabla).getByText('12.345,67')).toBeInTheDocument()
  })

  it('envía la pregunta de un ejemplo pulsable', async () => {
    simular(respuestaJson({ pregunta: PREGUNTAS_EJEMPLO[0], sql: 'SELECT 1', columnas: ['x'], filas: [[1]] }))
    const usuario = userEvent.setup()
    render(<QuestionPanel />)

    await usuario.click(screen.getByRole('button', { name: PREGUNTAS_EJEMPLO[0] }))

    expect(await screen.findByText('SELECT 1')).toBeInTheDocument()
    expect(screen.getByLabelText('Tu pregunta')).toHaveValue(PREGUNTAS_EJEMPLO[0])
    const init = fetchSimulado.mock.calls[0]?.[1]
    expect(JSON.parse(String(init?.body))).toEqual({ pregunta: PREGUNTAS_EJEMPLO[0] })
  })

  it('no envía una pregunta vacía y lo explica en un aviso', async () => {
    simular(respuestaJson({}))
    const usuario = userEvent.setup()
    render(<QuestionPanel />)

    await usuario.click(screen.getByRole('button', { name: 'Preguntar' }))

    expect(screen.getByRole('alert')).toHaveTextContent('Escribe una pregunta antes de enviar.')
    expect(fetchSimulado).not.toHaveBeenCalled()
  })

  it.each([
    ['llm_no_configurado', 503, 'El asistente de IA no está configurado'],
    ['llm_error', 502, 'El asistente de IA no ha respondido'],
    ['sql_no_valida', 422, 'La consulta generada no es válida'],
    ['error_ejecucion', 422, 'No se pudo ejecutar la consulta'],
    ['base_datos_no_disponible', 503, 'La base de datos no está disponible'],
  ] as const)('muestra un mensaje en español para %s', async (codigo, status, titulo) => {
    simular(respuestaJson({ error: codigo, mensaje: 'detalle del servidor', sql: 'DELETE FROM pedidos' }, status))
    const usuario = userEvent.setup()
    render(<QuestionPanel />)

    await usuario.type(screen.getByLabelText('Tu pregunta'), 'borra todo')
    await usuario.click(screen.getByRole('button', { name: 'Preguntar' }))

    const alerta = await screen.findByRole('alert')
    expect(alerta).toHaveTextContent(titulo)
    expect(alerta).toHaveAttribute('data-codigo', codigo)
  })

  it('muestra el SQL rechazado cuando llega en el error', async () => {
    simular(respuestaJson({ error: 'sql_no_valida', mensaje: 'Solo SELECT', sql: 'DROP TABLE pedidos' }, 422))
    const usuario = userEvent.setup()
    render(<QuestionPanel />)

    await usuario.type(screen.getByLabelText('Tu pregunta'), 'elimina pedidos')
    await usuario.keyboard('{Enter}')

    expect(await screen.findByText('DROP TABLE pedidos')).toBeInTheDocument()
  })

  it('avisa cuando no hay conexión con el servidor', async () => {
    simular(new TypeError('Failed to fetch'))
    const usuario = userEvent.setup()
    render(<QuestionPanel />)

    await usuario.type(screen.getByLabelText('Tu pregunta'), 'hola')
    await usuario.click(screen.getByRole('button', { name: 'Preguntar' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo conectar con el servidor')
  })
})

describe('ErrorNotice y mensajes por código', () => {
  it('define un mensaje para cada código', () => {
    for (const mensaje of Object.values(MENSAJES_ERROR)) {
      expect(mensaje.titulo.length).toBeGreaterThan(0)
      expect(mensaje.ayuda.length).toBeGreaterThan(0)
    }
  })

  it('ofrece reintentar solo en errores reintentables', async () => {
    const usuario = userEvent.setup()
    const reintentar = vi.fn()
    const { rerender } = render(
      <ErrorNotice error={presentarError(new ApiError({ error: 'llm_error', mensaje: 'x' }))} onReintentar={reintentar} />,
    )
    await usuario.click(screen.getByRole('button', { name: 'Reintentar' }))
    expect(reintentar).toHaveBeenCalledOnce()

    rerender(
      <ErrorNotice
        error={presentarError(new ApiError({ error: 'sql_no_valida', mensaje: 'x' }))}
        onReintentar={reintentar}
      />,
    )
    expect(screen.queryByRole('button', { name: 'Reintentar' })).not.toBeInTheDocument()
  })

  it('trata una excepción desconocida como error inesperado', () => {
    expect(presentarError(new Error('boom')).codigo).toBe('error_desconocido')
  })
})
