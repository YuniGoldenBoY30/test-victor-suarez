import { QuestionPanel } from './components/QuestionPanel'
import { SalesPanel } from './components/SalesPanel'
import { ThemeToggle } from './components/ThemeToggle'
import { TopClientsPanel } from './components/TopClientsPanel'
import { useTema } from './hooks/useTema'

export function App() {
  const { preferencia, elegir } = useTema()

  return (
    <>
      <a className="salto" href="#contenido">
        Saltar al contenido
      </a>
      <header className="cabecera">
        <div className="contenedor cabecera__interior">
          <p className="marca">
            <span className="marca__sello" aria-hidden="true">
              P
            </span>
            Pedidos
          </p>
          <ThemeToggle valor={preferencia} onCambio={elegir} />
        </div>
      </header>

      <main id="contenido" className="contenedor principal" tabIndex={-1}>
        <QuestionPanel />
        <div className="tablero">
          <SalesPanel />
          <TopClientsPanel />
        </div>
      </main>

      <footer className="pie contenedor">
        <p>Los importes se muestran sin moneda, tal como están en los datos. Los pedidos cancelados no cuentan como ventas.</p>
      </footer>
    </>
  )
}
