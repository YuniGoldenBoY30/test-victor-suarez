import { useCallback, useEffect, useState } from 'react'

export type PreferenciaTema = 'sistema' | 'claro' | 'oscuro'

const CLAVE = 'tema'

function leerGuardado(): PreferenciaTema {
  try {
    const valor = localStorage.getItem(CLAVE)
    if (valor === 'light') return 'claro'
    if (valor === 'dark') return 'oscuro'
  } catch {
    /* almacenamiento no disponible: se usa el tema del sistema */
  }
  return 'sistema'
}

function aplicar(pref: PreferenciaTema) {
  const raiz = document.documentElement
  if (pref === 'sistema') delete raiz.dataset.theme
  else raiz.dataset.theme = pref === 'claro' ? 'light' : 'dark'
  try {
    if (pref === 'sistema') localStorage.removeItem(CLAVE)
    else localStorage.setItem(CLAVE, pref === 'claro' ? 'light' : 'dark')
  } catch {
    /* sin persistencia */
  }
}

/** Tema claro/oscuro: sigue prefers-color-scheme salvo que se elija uno a mano. */
export function useTema() {
  const [preferencia, setPreferencia] = useState<PreferenciaTema>(leerGuardado)

  useEffect(() => {
    aplicar(preferencia)
  }, [preferencia])

  const elegir = useCallback((pref: PreferenciaTema) => setPreferencia(pref), [])
  return { preferencia, elegir }
}
