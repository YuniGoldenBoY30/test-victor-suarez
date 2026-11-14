import { describe, expect, it } from 'vitest'

// Guardia estática: falla si se introducen APIs de DOM inseguras o un uso indebido
// del almacenamiento web. Lee el código fuente como texto (sin node:fs).
const fuentes = import.meta.glob<string>(['/src/**/*.{ts,tsx}', '!/src/**/*.test.{ts,tsx}'], {
  query: '?raw',
  import: 'default',
  eager: true,
})
const index = import.meta.glob<string>('/index.html', { query: '?raw', import: 'default', eager: true })
const tema = import.meta.glob<string>('/public/tema.js', { query: '?raw', import: 'default', eager: true })

/** Quita comentarios para no dar falsos positivos con texto explicativo. */
function sinComentarios(codigo: string): string {
  return codigo.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`])\/\/.*$/gm, '$1')
}

const PROHIBIDOS: ReadonlyArray<[string, RegExp]> = [
  ['innerHTML', /\binnerHTML\b/],
  ['outerHTML', /\bouterHTML\b/],
  ['insertAdjacentHTML', /\binsertAdjacentHTML\b/],
  ['dangerouslySetInnerHTML', /\bdangerouslySetInnerHTML\b/],
  ['document.write', /\bdocument\s*\.\s*write(ln)?\s*\(/],
  ['eval', /\beval\s*\(/],
  ['new Function', /\bnew\s+Function\s*\(/],
  ['setTimeout/setInterval con cadena', /\bset(Timeout|Interval)\s*\(\s*['"`]/],
  ['sessionStorage', /\bsessionStorage\b/],
  ['document.cookie', /\bdocument\s*\.\s*cookie\b/],
]

const ACCESO_LOCAL = /\blocalStorage\s*\.\s*(\w+)\s*\(\s*([^,)]*)/g

describe('guardia de seguridad del código fuente', () => {
  const archivos = Object.entries(fuentes)

  it('encuentra el código fuente a revisar', () => {
    expect(archivos.length).toBeGreaterThan(5)
  })

  it.each(PROHIBIDOS)('no usa %s', (_nombre, patron) => {
    const infractores = archivos.filter(([, codigo]) => patron.test(sinComentarios(codigo))).map(([ruta]) => ruta)
    expect(infractores).toEqual([])
  })

  it('solo usa localStorage con la clave "tema"', () => {
    for (const [ruta, codigo] of archivos) {
      const limpio = sinComentarios(codigo)
      if (/\blocalStorage\b(?!\s*\.\s*(get|set|remove)Item\b)/.test(limpio)) {
        throw new Error(`${ruta}: localStorage solo puede usarse con getItem/setItem/removeItem`)
      }
      for (const [, metodo, clave] of limpio.matchAll(ACCESO_LOCAL)) {
        const nombre = (clave ?? '').trim()
        const esLiteral = nombre === "'tema'"
        const esConstante = /^[A-Z_]+$/.test(nombre) && new RegExp(`const\\s+${nombre}\\s*=\\s*'tema'`).test(limpio)
        expect(esLiteral || esConstante, `${ruta}: localStorage.${metodo}(${nombre}) debe usar la clave 'tema'`).toBe(true)
      }
    }
  })

  it('no guarda tokens ni credenciales en el almacenamiento', () => {
    const infractores = archivos
      .filter(([, codigo]) =>
        /(localStorage|sessionStorage)[^\n]*(token|jwt|password|secret|authorization)/i.test(codigo),
      )
      .map(([ruta]) => ruta)
    expect(infractores).toEqual([])
  })
})

describe('index.html y script del tema', () => {
  const html = Object.values(index)[0] ?? ''
  const script = Object.values(tema)[0] ?? ''

  it('no tiene scripts en línea y carga el tema desde un archivo externo', () => {
    const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)]
    expect(scripts.length).toBeGreaterThan(0)
    for (const [, atributos, contenido] of scripts) {
      expect(atributos).toMatch(/\bsrc=/)
      expect((contenido ?? '').trim()).toBe('')
    }
    expect(html).toContain('src="/tema.js"')
    expect(html).not.toMatch(/\son\w+\s*=/i)
  })

  it('tema.js solo toca la clave "tema" y no usa APIs inseguras', () => {
    expect(script).not.toBe('')
    const claves = [...sinComentarios(script).matchAll(ACCESO_LOCAL)].map((m) => (m[2] ?? '').trim())
    expect(claves.length).toBeGreaterThan(0)
    expect(new Set(claves)).toEqual(new Set(["'tema'"]))
    for (const [, patron] of PROHIBIDOS) expect(patron.test(sinComentarios(script))).toBe(false)
  })
})
