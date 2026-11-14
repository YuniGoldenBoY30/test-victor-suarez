import { useCallback, useEffect, useState } from 'react'

export type EstadoCarga<T> =
  | { fase: 'cargando' }
  | { fase: 'error'; error: unknown }
  | { fase: 'listo'; datos: T }

/**
 * Carga datos asíncronos cancelables. Se vuelve a ejecutar cuando cambia `cargar`
 * (memoízala con useCallback) o al llamar a `reintentar`.
 */
export function useCarga<T>(cargar: (signal: AbortSignal) => Promise<T>) {
  const [estado, setEstado] = useState<EstadoCarga<T>>({ fase: 'cargando' })
  const [intento, setIntento] = useState(0)

  useEffect(() => {
    const control = new AbortController()
    setEstado({ fase: 'cargando' })
    cargar(control.signal).then(
      (datos) => {
        if (!control.signal.aborted) setEstado({ fase: 'listo', datos })
      },
      (error: unknown) => {
        if (!control.signal.aborted) setEstado({ fase: 'error', error })
      },
    )
    return () => control.abort()
  }, [cargar, intento])

  const reintentar = useCallback(() => setIntento((n) => n + 1), [])
  return { estado, reintentar }
}
