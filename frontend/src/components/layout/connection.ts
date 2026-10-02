import { type HealthResponse } from '@/lib/api'

export type ConnectionState = 'connecting' | 'connected' | 'degraded' | 'offline'

interface HealthQueryLike {
  data: HealthResponse | undefined
  isPending: boolean
  isError: boolean
}

/** Map the health query onto the four states the connection indicator shows. */
export function connectionStateFrom(query: HealthQueryLike): ConnectionState {
  if (query.isError) return 'offline'
  if (query.isPending || !query.data) return 'connecting'
  return query.data.status.toLowerCase() === 'ok' ? 'connected' : 'degraded'
}
