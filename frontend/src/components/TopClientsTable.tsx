import type { TopCliente } from '../api'
import { formatearEntero, formatearImporte } from '../lib/format'

interface Props {
  clientes: readonly TopCliente[]
}

/** Tabla presentacional del top 10: orden descendente tal como llega de la API. */
export function TopClientsTable({ clientes }: Props) {
  if (clientes.length === 0) {
    return <p className="vacio">Todavía no hay clientes con pedidos para clasificar.</p>
  }
  const maximo = Math.max(...clientes.map((c) => c.total_comprado), 0)

  return (
    <div className="tabla-scroll" role="region" aria-label="Top 10 de clientes" tabIndex={0}>
      <table className="tabla tabla--ranking">
        <caption className="visually-hidden">Clientes ordenados por importe total comprado, de mayor a menor</caption>
        <thead>
          <tr>
            <th scope="col" className="num puesto">
              <span aria-hidden="true">N.º</span>
              <span className="visually-hidden">Puesto</span>
            </th>
            <th scope="col">Cliente</th>
            <th scope="col" className="num">
              Pedidos
            </th>
            <th scope="col" className="num">
              Total comprado
            </th>
          </tr>
        </thead>
        <tbody>
          {clientes.map((c, i) => (
            <tr key={c.cliente}>
              <td className="num puesto">{i + 1}</td>
              <th scope="row" className="cliente">
                {c.cliente}
              </th>
              <td className="num">{formatearEntero(c.num_pedidos)}</td>
              <td className="num total">
                <span className="total__valor">{formatearImporte(c.total_comprado)}</span>
                <span
                  className="total__barra"
                  aria-hidden="true"
                  style={{ width: `${maximo > 0 ? (c.total_comprado / maximo) * 100 : 0}%` }}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
