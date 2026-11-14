/**
 * DTO que reflejan el contrato de la API (docs/TRD.md, sección 9).
 * Cualquier cambio en el backend debe reflejarse aquí y en nada más:
 * el resto de la aplicación solo importa estos tipos desde `src/api`.
 */

/** Fila de GET /ventas-por-mes-pais. `mes` es el primer día del mes (YYYY-MM-DD). */
export interface VentaMesPais {
  mes: string
  pais: string
  num_pedidos: number
  total_ventas: number
}

/** Fila de GET /top-clientes. */
export interface TopCliente {
  cliente: string
  num_pedidos: number
  total_comprado: number
}

/** Cuerpo de POST /consulta. */
export interface ConsultaPeticion {
  pregunta: string
}

/** Valor de una celda del resultado: fechas ISO, decimales como número; listas y structs de DuckDB llegan anidados. */
export type ValorCelda = string | number | boolean | null | ValorCelda[] | { [clave: string]: ValorCelda }

/** Respuesta 200 de POST /consulta. */
export interface ConsultaRespuesta {
  pregunta: string
  sql: string
  columnas: string[]
  filas: ValorCelda[][]
}

/** Longitud máxima de la pregunta aceptada por la API. */
export const PREGUNTA_MAX = 500

/** Códigos de error del contrato más los que genera el propio cliente. */
export type CodigoError =
  | 'llm_no_configurado'
  | 'llm_error'
  | 'sql_no_valida'
  | 'error_ejecucion'
  | 'base_datos_no_disponible'
  | 'cuerpo_invalido'
  | 'error_red'
  | 'error_desconocido'

/** Cuerpo de error del backend: {"error", "mensaje", "sql"?}. */
export interface CuerpoError {
  error: string
  mensaje: string
  sql?: string
}
