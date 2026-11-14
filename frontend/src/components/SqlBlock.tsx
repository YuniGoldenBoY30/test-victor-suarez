import { useEffect, useRef, useState } from 'react'

interface Props {
  sql: string
  etiqueta?: string
}

/** El SQL como un albarán: tira de papel con borde perforado y botón para copiarlo. */
export function SqlBlock({ sql, etiqueta = 'SQL ejecutado' }: Props) {
  const [copiado, setCopiado] = useState(false)
  const temporizador = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(temporizador.current), [])

  async function copiar() {
    try {
      await navigator.clipboard.writeText(sql)
      setCopiado(true)
      window.clearTimeout(temporizador.current)
      temporizador.current = window.setTimeout(() => setCopiado(false), 2000)
    } catch {
      /* portapapeles no disponible: el texto sigue siendo seleccionable */
    }
  }

  return (
    <figure className="albaran">
      <figcaption className="albaran__cabecera">
        <span className="albaran__etiqueta">{etiqueta}</span>
        <button type="button" className="boton boton--texto" onClick={copiar}>
          {copiado ? 'SQL copiado' : 'Copiar SQL'}
        </button>
      </figcaption>
      <pre className="albaran__codigo">
        <code>{sql}</code>
      </pre>
      <span className="visually-hidden" role="status">
        {copiado ? 'SQL copiado al portapapeles' : ''}
      </span>
    </figure>
  )
}
