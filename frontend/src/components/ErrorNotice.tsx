import type { ErrorPresentado } from '../lib/mensajesError'
import { SqlBlock } from './SqlBlock'

interface Props {
  error: ErrorPresentado
  onReintentar?: () => void
}

/** Aviso de error presentacional. `role="alert"` lo anuncia a los lectores de pantalla. */
export function ErrorNotice({ error, onReintentar }: Props) {
  return (
    <div className="aviso-error" role="alert" data-codigo={error.codigo}>
      <h3 className="aviso-error__titulo">{error.titulo}</h3>
      <p className="aviso-error__ayuda">{error.ayuda}</p>
      {error.detalle && (
        <p className="aviso-error__detalle">
          <span className="visually-hidden">Mensaje del servidor: </span>
          {error.detalle}
        </p>
      )}
      {error.sql && <SqlBlock sql={error.sql} etiqueta="SQL rechazado" />}
      {error.reintentable && onReintentar && (
        <button type="button" className="boton boton--secundario" onClick={onReintentar}>
          Reintentar
        </button>
      )}
    </div>
  )
}
