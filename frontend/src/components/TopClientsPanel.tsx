import { obtenerTopClientes } from '../api'
import { useCarga } from '../hooks/useCarga'
import { presentarError } from '../lib/mensajesError'
import { ErrorNotice } from './ErrorNotice'
import { TopClientsTable } from './TopClientsTable'

/** Contenedor del top 10: carga, errores y estado vacío. */
export function TopClientsPanel() {
  const { estado, reintentar } = useCarga(obtenerTopClientes)

  return (
    <section className="panel panel--clientes" aria-labelledby="titulo-clientes">
      <div className="panel__cabecera">
        <h2 id="titulo-clientes" className="panel__titulo">
          Top 10 clientes
        </h2>
      </div>
      <p className="nota nota--arriba">Por importe total comprado, sin contar pedidos cancelados.</p>

      {estado.fase === 'cargando' && (
        <div className="esqueleto esqueleto--tabla" role="status" aria-label="Cargando clientes" aria-busy="true">
          <span className="visually-hidden">Cargando clientes…</span>
        </div>
      )}
      {estado.fase === 'error' && <ErrorNotice error={presentarError(estado.error)} onReintentar={reintentar} />}
      {estado.fase === 'listo' && <TopClientsTable clientes={estado.datos} />}
    </section>
  )
}
