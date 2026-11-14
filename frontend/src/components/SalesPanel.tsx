import { Suspense, lazy, useCallback, useEffect, useId, useMemo, useState, type CSSProperties } from 'react'
import { obtenerVentasPorMesPais } from '../api'
import { useCarga } from '../hooks/useCarga'
import { useMovimientoReducido } from '../hooks/useMovimientoReducido'
import { formatearImporte, mesLargo, plural } from '../lib/format'
import { presentarError } from '../lib/mensajesError'
import { colorSerie, pivotarVentas } from '../lib/ventas'
import { ErrorNotice } from './ErrorNotice'

// recharts pesa bastante: el gráfico se carga aparte para no retrasar la portada.
const SalesChart = lazy(() => import('./SalesChart').then((m) => ({ default: m.SalesChart })))

/** Contenedor: carga las ventas, gestiona el filtro de país y la leyenda interactiva. */
export function SalesPanel() {
  const idFiltro = useId()
  const reducido = useMovimientoReducido()
  const [pais, setPais] = useState('')
  const [catalogo, setCatalogo] = useState<string[]>([])
  const [ocultos, setOcultos] = useState<ReadonlySet<string>>(new Set())

  const cargar = useCallback((signal: AbortSignal) => obtenerVentasPorMesPais(pais || undefined, signal), [pais])
  const { estado, reintentar } = useCarga(cargar)

  const pivot = useMemo(() => (estado.fase === 'listo' ? pivotarVentas(estado.datos) : null), [estado])

  // El catálogo completo de países sale de la carga sin filtro y se conserva al filtrar.
  useEffect(() => {
    if (pivot && pais === '') setCatalogo(pivot.paises)
  }, [pivot, pais])

  function alternar(nombre: string) {
    setOcultos((previo) => {
      const siguiente = new Set(previo)
      if (siguiente.has(nombre)) siguiente.delete(nombre)
      else siguiente.add(nombre)
      return siguiente
    })
  }

  const colorDe = (nombre: string) => {
    const i = catalogo.indexOf(nombre)
    return colorSerie(i >= 0 ? i : 0)
  }

  const opcionesPais = catalogo.length > 0 ? catalogo : pais ? [pais] : []
  const visibles = pivot ? pivot.paises.filter((p) => !ocultos.has(p)) : []
  const series = visibles.map((p) => ({ pais: p, color: colorDe(p) }))

  const resumen =
    pivot && pivot.puntos.length > 0
      ? `Ventas de ${mesLargo(pivot.puntos[0]!.mes)} a ${mesLargo(pivot.puntos[pivot.puntos.length - 1]!.mes)}: ${formatearImporte(pivot.totalGeneral)} en ${plural(pivot.paises.length, 'país', 'países')}${pais ? ` (filtrado por ${pais})` : ''}.`
      : ''

  return (
    <section className="panel panel--ventas" aria-labelledby="titulo-ventas">
      <div className="panel__cabecera">
        <h2 id="titulo-ventas" className="panel__titulo">
          Ventas por mes y país
        </h2>
        <div className="campo campo--inline">
          <label htmlFor={idFiltro}>País</label>
          <select id={idFiltro} value={pais} onChange={(e) => setPais(e.target.value)}>
            <option value="">Todos los países</option>
            {opcionesPais.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
      </div>

      {estado.fase === 'error' && <ErrorNotice error={presentarError(estado.error)} onReintentar={reintentar} />}

      {estado.fase === 'cargando' && (
        <div className="esqueleto esqueleto--grafico" role="status" aria-label="Cargando ventas" aria-busy="true">
          <span className="visually-hidden">Cargando ventas…</span>
        </div>
      )}

      {pivot && pivot.puntos.length === 0 && (
        <p className="vacio">
          {pais
            ? `No hay ventas registradas para ${pais}. Elige otro país o quita el filtro.`
            : 'Aún no hay ventas que mostrar. Carga los datos con python -m etl y recarga la página.'}
        </p>
      )}

      {pivot && pivot.puntos.length > 0 && (
        <>
          <p className="resumen" aria-live="polite">
            {resumen}
          </p>

          <ul className="leyenda" aria-label="Países del gráfico. Pulsa para mostrar u ocultar.">
            {pivot.paises.map((p) => {
              const oculto = ocultos.has(p)
              return (
                <li key={p}>
                  <button
                    type="button"
                    className="leyenda__boton"
                    aria-pressed={!oculto}
                    onClick={() => alternar(p)}
                  >
                    <span
                      className={`swatch${oculto ? ' swatch--hueco' : ''}`}
                      style={{ '--color': colorDe(p) } as CSSProperties}
                      aria-hidden="true"
                    />
                    {p}
                  </button>
                </li>
              )
            })}
          </ul>

          {series.length > 0 ? (
            <Suspense fallback={<div className="esqueleto esqueleto--grafico" aria-hidden="true" />}>
              <SalesChart puntos={pivot.puntos} series={series} animado={!reducido} />
            </Suspense>
          ) : (
            <p className="vacio">Has ocultado todos los países. Pulsa uno de la leyenda para volver a verlo.</p>
          )}

          <details className="alternativa">
            <summary>Ver los mismos datos como tabla</summary>
            <div className="tabla-scroll" role="region" aria-label="Ventas por mes y país en tabla" tabIndex={0}>
              <table className="tabla">
                <caption className="visually-hidden">Total de ventas por mes y país</caption>
                <thead>
                  <tr>
                    <th scope="col">Mes</th>
                    {pivot.paises.map((p) => (
                      <th key={p} scope="col" className="num">
                        {p}
                      </th>
                    ))}
                    <th scope="col" className="num">
                      Total
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {pivot.puntos.map((punto) => (
                    <tr key={punto.mes}>
                      <th scope="row">{mesLargo(punto.mes)}</th>
                      {pivot.paises.map((p) => (
                        <td key={p} className="num">
                          {formatearImporte(punto.totales[p] ?? 0)}
                        </td>
                      ))}
                      <td className="num">{formatearImporte(punto.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
    </section>
  )
}
