import { useEffect, useState } from 'react'

const CONSULTA = '(prefers-reduced-motion: reduce)'

function coincide(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia(CONSULTA).matches
    : false
}

/** true si la persona pidió reducir el movimiento. */
export function useMovimientoReducido(): boolean {
  const [reducido, setReducido] = useState(coincide)

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const lista = window.matchMedia(CONSULTA)
    const alCambiar = () => setReducido(lista.matches)
    lista.addEventListener('change', alCambiar)
    return () => lista.removeEventListener('change', alCambiar)
  }, [])

  return reducido
}
