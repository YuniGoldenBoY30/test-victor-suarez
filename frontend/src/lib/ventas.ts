import type { VentaMesPais } from '../api'

export interface PuntoMes {
  mes: string
  /** Total de ventas por país en ese mes (0 si no hubo). */
  totales: Record<string, number>
  total: number
}

export interface VentasPivotadas {
  paises: string[]
  puntos: PuntoMes[]
  totalGeneral: number
}

/** Agrupa las filas (mes, país) en una fila por mes, ordenada cronológicamente. */
export function pivotarVentas(filas: readonly VentaMesPais[]): VentasPivotadas {
  const paises = [...new Set(filas.map((f) => f.pais))].sort((a, b) => a.localeCompare(b, 'es'))
  const porMes = new Map<string, PuntoMes>()
  for (const fila of filas) {
    let punto = porMes.get(fila.mes)
    if (!punto) {
      punto = { mes: fila.mes, totales: {}, total: 0 }
      porMes.set(fila.mes, punto)
    }
    punto.totales[fila.pais] = (punto.totales[fila.pais] ?? 0) + fila.total_ventas
    punto.total += fila.total_ventas
  }
  const puntos = [...porMes.values()].sort((a, b) => a.mes.localeCompare(b.mes))
  const totalGeneral = puntos.reduce((suma, p) => suma + p.total, 0)
  return { paises, puntos, totalGeneral }
}

/** Número de colores de serie definidos en CSS (--serie-1 ... --serie-N). */
export const NUM_SERIES = 8

/** Color CSS estable de un país según su posición en el catálogo completo. */
export function colorSerie(indice: number): string {
  return `var(--serie-${(indice % NUM_SERIES) + 1})`
}
