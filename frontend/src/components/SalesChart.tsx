import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { TooltipContentProps } from 'recharts'
import { formatearCompacto, formatearImporte, mesCorto, mesLargo } from '../lib/format'
import type { PuntoMes } from '../lib/ventas'

export interface SerieGrafico {
  pais: string
  color: string
}

interface Props {
  puntos: readonly PuntoMes[]
  series: readonly SerieGrafico[]
  animado: boolean
}

type FilaGrafico = { mes: string } & Record<string, number | string>

function TooltipVentas({ active, payload, label }: TooltipContentProps) {
  if (!active || !payload || payload.length === 0) return null
  const valorDe = (v: unknown) => (typeof v === 'number' ? v : 0)
  const total = payload.reduce((suma, p) => suma + valorDe(p.value), 0)
  return (
    <div className="grafico-tooltip">
      <p className="grafico-tooltip__mes">{mesLargo(String(label))}</p>
      <ul>
        {[...payload].reverse().map((p) => (
          <li key={String(p.dataKey)}>
            <span className="swatch" style={{ background: p.color }} aria-hidden="true" />
            <span className="grafico-tooltip__pais">{p.name}</span>
            <span className="num">{formatearImporte(valorDe(p.value))}</span>
          </li>
        ))}
      </ul>
      <p className="grafico-tooltip__total">
        <span>Total</span>
        <span className="num">{formatearImporte(total)}</span>
      </p>
    </div>
  )
}

/** Barras apiladas: cada columna es un mes y cada tramo un país. Presentacional. */
export function SalesChart({ puntos, series, animado }: Props) {
  const datos: FilaGrafico[] = puntos.map((p) => ({ mes: p.mes, ...p.totales }))

  return (
    <div className="grafico">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={datos} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} accessibilityLayer>
          <CartesianGrid vertical={false} stroke="var(--linea)" strokeDasharray="3 4" />
          <XAxis
            dataKey="mes"
            tickFormatter={mesCorto}
            tickLine={false}
            axisLine={{ stroke: 'var(--linea-fuerte)' }}
            tick={{ fill: 'var(--tinta-suave)', fontSize: 12 }}
            minTickGap={12}
          />
          <YAxis
            tickFormatter={(v: number) => formatearCompacto(v)}
            tickLine={false}
            axisLine={false}
            width={52}
            tick={{ fill: 'var(--tinta-suave)', fontSize: 12 }}
          />
          <Tooltip content={(props) => <TooltipVentas {...props} />} cursor={{ fill: 'var(--resalte)' }} />
          {series.map((s) => (
            <Bar
              key={s.pais}
              dataKey={s.pais}
              name={s.pais}
              stackId="ventas"
              fill={s.color}
              stroke="var(--superficie)"
              strokeWidth={1}
              isAnimationActive={animado}
              animationDuration={450}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
