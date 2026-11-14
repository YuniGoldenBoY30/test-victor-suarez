import type { PreferenciaTema } from '../hooks/useTema'

const OPCIONES: { valor: PreferenciaTema; etiqueta: string }[] = [
  { valor: 'sistema', etiqueta: 'Sistema' },
  { valor: 'claro', etiqueta: 'Claro' },
  { valor: 'oscuro', etiqueta: 'Oscuro' },
]

interface Props {
  valor: PreferenciaTema
  onCambio: (valor: PreferenciaTema) => void
}

/** Selector de tema como grupo de radios: teclado con flechas, estado anunciado. */
export function ThemeToggle({ valor, onCambio }: Props) {
  return (
    <fieldset className="tema">
      <legend className="visually-hidden">Tema de color</legend>
      {OPCIONES.map((o) => (
        <label key={o.valor} className="tema__opcion">
          <input
            type="radio"
            name="tema"
            value={o.valor}
            checked={valor === o.valor}
            onChange={() => onCambio(o.valor)}
          />
          <span>{o.etiqueta}</span>
        </label>
      ))}
    </fieldset>
  )
}
