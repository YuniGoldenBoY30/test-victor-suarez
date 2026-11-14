import { describe, expect, it } from 'vitest'
import { colorSerie, NUM_SERIES, pivotarVentas } from './ventas'
import { formatearCelda, mesCorto } from './format'

describe('pivotarVentas', () => {
  it('agrupa por mes, ordena cronológicamente y suma los totales', () => {
    const resultado = pivotarVentas([
      { mes: '2024-02-01', pais: 'España', num_pedidos: 1, total_ventas: 10 },
      { mes: '2024-01-01', pais: 'México', num_pedidos: 2, total_ventas: 5.5 },
      { mes: '2024-01-01', pais: 'España', num_pedidos: 3, total_ventas: 20 },
    ])

    expect(resultado.paises).toEqual(['España', 'México'])
    expect(resultado.puntos.map((p) => p.mes)).toEqual(['2024-01-01', '2024-02-01'])
    expect(resultado.puntos[0]).toMatchObject({ totales: { México: 5.5, España: 20 }, total: 25.5 })
    expect(resultado.totalGeneral).toBe(35.5)
  })

  it('devuelve vacío sin filas', () => {
    expect(pivotarVentas([])).toEqual({ paises: [], puntos: [], totalGeneral: 0 })
  })
})

describe('colorSerie', () => {
  it('reutiliza los colores de forma cíclica', () => {
    expect(colorSerie(0)).toBe('var(--serie-1)')
    expect(colorSerie(NUM_SERIES)).toBe('var(--serie-1)')
  })
})

describe('formato', () => {
  it('formatea el mes sin desfase de zona horaria', () => {
    expect(mesCorto('2024-03-01')).toMatch(/mar/)
  })

  it('formatea celdas: nulos, números y fechas ISO', () => {
    expect(formatearCelda(null)).toBe('—')
    expect(formatearCelda(12345.5)).toBe('12.345,5')
    expect(formatearCelda('2024-03-01')).toMatch(/2024/)
    expect(formatearCelda('España')).toBe('España')
  })
})
