import type { ValorCelda } from '../api'
import { esNumero, formatearCelda, plural } from '../lib/format'

/** Filas que se pintan como máximo; la API ya limita a 1000. */
export const MAX_FILAS_VISIBLES = 200

interface Props {
  columnas: string[]
  filas: ValorCelda[][]
}

/** Tabla dinámica: columnas y celdas vienen del resultado de la consulta. */
export function ResultTable({ columnas, filas }: Props) {
  if (filas.length === 0) {
    return (
      <p className="vacio">
        La consulta se ejecutó pero no devolvió filas. Prueba con otro país, otro mes o un rango más amplio.
      </p>
    )
  }
  const visibles = filas.slice(0, MAX_FILAS_VISIBLES)
  // El tipo de columna se deduce de la primera fila con valor, para alinear números a la derecha.
  const numericas = columnas.map((_, i) => {
    const primera = filas.find((f) => f[i] !== null && f[i] !== undefined)
    return primera ? esNumero(primera[i] as ValorCelda) : false
  })

  return (
    <>
      <div className="tabla-scroll" role="region" aria-label="Resultado de la consulta" tabIndex={0}>
        <table className="tabla">
          <caption className="visually-hidden">
            Resultado: {plural(filas.length, 'fila', 'filas')} y {plural(columnas.length, 'columna', 'columnas')}
          </caption>
          <thead>
            <tr>
              {columnas.map((c, i) => (
                <th key={`${c}-${i}`} scope="col" className={numericas[i] ? 'num' : undefined}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibles.map((fila, r) => (
              <tr key={r}>
                {columnas.map((_, i) => (
                  <td key={i} className={numericas[i] ? 'num' : undefined}>
                    {formatearCelda(fila[i] ?? null)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {filas.length > visibles.length && (
        <p className="nota">
          Se muestran las primeras {plural(visibles.length, 'fila', 'filas')} de {plural(filas.length, 'fila', 'filas')}.
        </p>
      )}
    </>
  )
}
