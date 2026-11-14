import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { PREGUNTA_MAX, enviarConsulta, type ConsultaRespuesta } from '../api'
import { plural } from '../lib/format'
import { presentarError, type ErrorPresentado } from '../lib/mensajesError'
import { ErrorNotice } from './ErrorNotice'
import { ResultTable } from './ResultTable'
import { SqlBlock } from './SqlBlock'

export const PREGUNTAS_EJEMPLO = [
  '¿Cuánto vendimos en España en marzo de 2024?',
  '¿Cuáles son los 5 clientes que más han comprado?',
  '¿Cuántos pedidos cancelados hay en cada país?',
  '¿Qué producto ha generado más importe en 2024?',
] as const

type Estado =
  | { fase: 'reposo' }
  | { fase: 'cargando'; pregunta: string }
  | { fase: 'listo'; resultado: ConsultaRespuesta }
  | { fase: 'error'; error: ErrorPresentado; pregunta: string }

/** Contenedor del panel de preguntas: formulario, ejemplos y resultado. */
export function QuestionPanel() {
  const idCampo = useId()
  const idAyuda = `${idCampo}-ayuda`
  const idAviso = `${idCampo}-aviso`
  const [texto, setTexto] = useState('')
  const [aviso, setAviso] = useState('')
  const [estado, setEstado] = useState<Estado>({ fase: 'reposo' })
  const control = useRef<AbortController | null>(null)

  useEffect(() => () => control.current?.abort(), [])

  async function preguntar(pregunta: string) {
    const limpia = pregunta.trim()
    if (limpia === '') {
      setAviso('Escribe una pregunta antes de enviar.')
      return
    }
    setAviso('')
    control.current?.abort()
    const actual = new AbortController()
    control.current = actual
    setEstado({ fase: 'cargando', pregunta: limpia })
    try {
      const resultado = await enviarConsulta(limpia, actual.signal)
      if (!actual.signal.aborted) setEstado({ fase: 'listo', resultado })
    } catch (error) {
      if (actual.signal.aborted) return
      setEstado({ fase: 'error', error: presentarError(error), pregunta: limpia })
    }
  }

  function alEnviar(e: FormEvent) {
    e.preventDefault()
    void preguntar(texto)
  }

  function usarEjemplo(ejemplo: string) {
    setTexto(ejemplo)
    void preguntar(ejemplo)
  }

  const cargando = estado.fase === 'cargando'
  const anuncio =
    estado.fase === 'cargando'
      ? 'Consultando los datos…'
      : estado.fase === 'listo'
        ? `Resultado listo: ${plural(estado.resultado.filas.length, 'fila', 'filas')}.`
        : ''

  return (
    <section className="pregunta" aria-labelledby="titulo-pregunta">
      <h1 id="titulo-pregunta" className="pregunta__titulo">
        Pregunta a tus pedidos
      </h1>
      <p className="pregunta__intro">
        Escribe en español lo que quieres saber. Te mostramos el SQL de solo lectura que se ejecutó para que puedas
        comprobar la respuesta.
      </p>

      <form className="pregunta__form" onSubmit={alEnviar} noValidate>
        <label htmlFor={idCampo} className="pregunta__etiqueta">
          Tu pregunta
        </label>
        <div className="pregunta__fila">
          <input
            id={idCampo}
            className="pregunta__entrada"
            type="text"
            value={texto}
            maxLength={PREGUNTA_MAX}
            autoComplete="off"
            enterKeyHint="send"
            placeholder="Por ejemplo: ¿Cuánto vendimos en España en marzo de 2024?"
            aria-describedby={aviso ? `${idAyuda} ${idAviso}` : idAyuda}
            aria-invalid={aviso ? true : undefined}
            onChange={(e) => setTexto(e.target.value)}
          />
          <button type="submit" className="boton boton--primario" disabled={cargando} aria-busy={cargando}>
            {cargando ? (
              <>
                <span className="spinner" aria-hidden="true" />
                Consultando…
              </>
            ) : (
              'Preguntar'
            )}
          </button>
        </div>
        <p id={idAyuda} className="nota">
          Pulsa Intro para enviar. Máximo {PREGUNTA_MAX} caracteres.
        </p>
        {aviso && (
          <p id={idAviso} className="campo-error" role="alert">
            {aviso}
          </p>
        )}
      </form>

      <div className="ejemplos">
        <p id="ejemplos-titulo" className="ejemplos__titulo">
          Prueba con una de estas
        </p>
        <ul className="ejemplos__lista" aria-labelledby="ejemplos-titulo">
          {PREGUNTAS_EJEMPLO.map((ejemplo) => (
            <li key={ejemplo}>
              <button type="button" className="chip" onClick={() => usarEjemplo(ejemplo)}>
                {ejemplo}
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="resultado">
        <p className="visually-hidden" role="status" aria-live="polite">
          {anuncio}
        </p>

        {estado.fase === 'cargando' && (
          <div className="esqueleto esqueleto--tabla" aria-hidden="true" />
        )}

        {estado.fase === 'error' && <ErrorNotice error={estado.error} onReintentar={() => void preguntar(estado.pregunta)} />}

        {estado.fase === 'listo' && (
          <div className="resultado__contenido">
            <h2 className="resultado__titulo">{estado.resultado.pregunta}</h2>
            <p className="resultado__resumen">
              {plural(estado.resultado.filas.length, 'fila', 'filas')} y{' '}
              {plural(estado.resultado.columnas.length, 'columna', 'columnas')}
            </p>
            <SqlBlock sql={estado.resultado.sql} />
            <ResultTable columnas={estado.resultado.columnas} filas={estado.resultado.filas} />
          </div>
        )}
      </div>
    </section>
  )
}
