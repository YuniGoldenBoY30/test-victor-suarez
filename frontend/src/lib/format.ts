import type { ValorCelda } from '../api'

const LOCALE = 'es-ES'

const formatoNumero = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 2, useGrouping: 'always' })
const formatoImporte = new Intl.NumberFormat(LOCALE, {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  useGrouping: 'always',
})
const formatoCompacto = new Intl.NumberFormat(LOCALE, { notation: 'compact', maximumFractionDigits: 1 })
const formatoEntero = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 0, useGrouping: 'always' })

export function formatearImporte(valor: number): string {
  return formatoImporte.format(valor)
}

export function formatearEntero(valor: number): string {
  return formatoEntero.format(valor)
}

export function formatearCompacto(valor: number): string {
  return formatoCompacto.format(valor)
}

/** Convierte "YYYY-MM-DD" en una fecha UTC (evita desfases de zona horaria). */
function fechaUtc(iso: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!m) return null
  return new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])))
}

const formatoMesCorto = new Intl.DateTimeFormat(LOCALE, { month: 'short', year: '2-digit', timeZone: 'UTC' })
const formatoMesLargo = new Intl.DateTimeFormat(LOCALE, { month: 'long', year: 'numeric', timeZone: 'UTC' })

export function mesCorto(iso: string): string {
  const f = fechaUtc(iso)
  return f ? formatoMesCorto.format(f).replace('.', '') : iso
}

export function mesLargo(iso: string): string {
  const f = fechaUtc(iso)
  return f ? formatoMesLargo.format(f) : iso
}

const FECHA_ISO = /^\d{4}-\d{2}-\d{2}$/
const formatoFecha = new Intl.DateTimeFormat(LOCALE, { dateStyle: 'medium', timeZone: 'UTC' })

/** Texto de una celda del resultado dinámico. */
export function formatearCelda(valor: ValorCelda): string {
  if (valor === null) return '—'
  if (typeof valor === 'number') return formatoNumero.format(valor)
  if (typeof valor === 'boolean') return valor ? 'Sí' : 'No'
  if (FECHA_ISO.test(valor)) {
    const f = fechaUtc(valor)
    if (f) return formatoFecha.format(f)
  }
  return valor
}

export function esNumero(valor: ValorCelda): boolean {
  return typeof valor === 'number'
}

export function plural(n: number, singular: string, pluralTexto: string): string {
  return `${formatoEntero.format(n)} ${n === 1 ? singular : pluralTexto}`
}
