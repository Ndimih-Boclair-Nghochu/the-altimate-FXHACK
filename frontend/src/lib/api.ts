import { queryOptions, useQuery } from '@tanstack/react-query'

/**
 * Typed client for the Altimate FX backend.
 *
 * All requests go to the same origin under `/api` (proxied to the backend by
 * Vite in development and by nginx in production), so cookies flow with
 * `credentials: 'include'` and no secrets ever live in the frontend.
 */

export const API_BASE = '/api'

/* -------------------------------------------------------------------------- */
/* Errors                                                                     */
/* -------------------------------------------------------------------------- */

export type ApiErrorCode =
  | 'network_error'
  | 'http_error'
  | 'invalid_response'
  | 'unauthorized'
  | 'forbidden'
  | 'not_found'
  | 'validation_error'
  | 'server_error'
  | (string & {})

export class ApiError extends Error {
  override readonly name = 'ApiError'
  /** HTTP status, or 0 when the request never reached the server. */
  readonly status: number
  readonly code: ApiErrorCode
  /** Parsed error body (if any), for field-level validation messages. */
  readonly details: unknown

  constructor(init: { status: number; code: ApiErrorCode; message: string; details?: unknown }) {
    super(init.message)
    this.status = init.status
    this.code = init.code
    this.details = init.details
  }

  get isNetworkError(): boolean {
    return this.status === 0
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function codeForStatus(status: number): ApiErrorCode {
  if (status === 401) return 'unauthorized'
  if (status === 403) return 'forbidden'
  if (status === 404) return 'not_found'
  if (status === 422) return 'validation_error'
  if (status >= 500) return 'server_error'
  return 'http_error'
}

/**
 * Pull a human-readable message out of common error shapes:
 * FastAPI `{detail: string | [{msg}]}`, `{message}`, or `{error: {code, message}}`.
 */
function describeErrorBody(body: unknown): { message?: string; code?: string } {
  if (!isRecord(body)) return {}
  const { detail, message, error, code } = body
  if (typeof detail === 'string') return { message: detail }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (isRecord(item) && typeof item.msg === 'string' ? item.msg : null))
      .filter((msg): msg is string => msg !== null)
    if (messages.length > 0) return { message: messages.join('; ') }
  }
  if (isRecord(error)) {
    return {
      message: typeof error.message === 'string' ? error.message : undefined,
      code: typeof error.code === 'string' ? error.code : undefined,
    }
  }
  return {
    message: typeof message === 'string' ? message : undefined,
    code: typeof code === 'string' ? code : undefined,
  }
}

async function readJson(response: Response): Promise<unknown> {
  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.includes('application/json')) return undefined
  try {
    return (await response.json()) as unknown
  } catch {
    return undefined
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  const body = await readJson(response)
  const described = describeErrorBody(body)
  return new ApiError({
    status: response.status,
    code: described.code ?? codeForStatus(response.status),
    message: described.message ?? `Request failed with status ${response.status}`,
    details: body,
  })
}

/* -------------------------------------------------------------------------- */
/* Fetch wrapper                                                              */
/* -------------------------------------------------------------------------- */

type QueryValue = string | number | boolean | null | undefined

export interface ApiRequestOptions extends Omit<RequestInit, 'body' | 'credentials'> {
  /** JSON-serialisable body (FormData is passed through untouched). */
  body?: unknown
  /** Query-string parameters; null/undefined values are dropped. */
  query?: Record<string, QueryValue>
}

export function buildApiUrl(path: string, query?: Record<string, QueryValue>): string {
  const normalized = path.startsWith('/') ? path : `/${path}`
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== null && value !== undefined) params.append(key, String(value))
  }
  const search = params.toString()
  return `${API_BASE}${normalized}${search ? `?${search}` : ''}`
}

/**
 * Fetch JSON from the backend. Resolves with the parsed body typed as `T`
 * (callers that need runtime guarantees should validate, as `fetchHealth` does)
 * and rejects with a typed `ApiError` for network failures and non-2xx replies.
 * Aborts (e.g. from React Query cancellation) are re-thrown unchanged.
 */
export async function apiFetch<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const { body, query, headers: initHeaders, ...init } = options
  const headers = new Headers(initHeaders)
  headers.set('Accept', 'application/json')

  let requestBody: BodyInit | undefined
  if (body instanceof FormData) {
    requestBody = body
  } else if (body !== undefined) {
    headers.set('Content-Type', 'application/json')
    requestBody = JSON.stringify(body)
  }

  let response: Response
  try {
    response = await fetch(buildApiUrl(path, query), {
      ...init,
      headers,
      body: requestBody,
      credentials: 'include',
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError({
      status: 0,
      code: 'network_error',
      message: 'Unable to reach the Altimate FX server.',
      details: error,
    })
  }

  if (!response.ok) throw await toApiError(response)
  if (response.status === 204) return undefined as T

  const data = await readJson(response)
  if (data === undefined) {
    throw new ApiError({
      status: response.status,
      code: 'invalid_response',
      message: 'The server returned a response that is not valid JSON.',
    })
  }
  return data as T
}

export const api = {
  get: <T>(path: string, options?: Omit<ApiRequestOptions, 'method' | 'body'>) =>
    apiFetch<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, body?: unknown, options?: Omit<ApiRequestOptions, 'method' | 'body'>) =>
    apiFetch<T>(path, { ...options, method: 'POST', body }),
  put: <T>(path: string, body?: unknown, options?: Omit<ApiRequestOptions, 'method' | 'body'>) =>
    apiFetch<T>(path, { ...options, method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown, options?: Omit<ApiRequestOptions, 'method' | 'body'>) =>
    apiFetch<T>(path, { ...options, method: 'PATCH', body }),
  delete: <T>(path: string, options?: Omit<ApiRequestOptions, 'method' | 'body'>) =>
    apiFetch<T>(path, { ...options, method: 'DELETE' }),
}

/* -------------------------------------------------------------------------- */
/* Health                                                                     */
/* -------------------------------------------------------------------------- */

export const TRADING_MODES = ['paper', 'practice', 'live'] as const
export type TradingMode = (typeof TRADING_MODES)[number]

export function isTradingMode(value: unknown): value is TradingMode {
  return typeof value === 'string' && (TRADING_MODES as readonly string[]).includes(value)
}

/** `GET /api/health` */
export interface HealthResponse {
  status: string
  version: string
  mode: TradingMode
}

/**
 * Validate the health payload at runtime. The trading mode drives safety-critical
 * UI (the LIVE badge), so an unexpected value is treated as an error rather than
 * being silently displayed.
 */
export function parseHealth(data: unknown): HealthResponse {
  if (
    isRecord(data) &&
    typeof data.status === 'string' &&
    typeof data.version === 'string' &&
    isTradingMode(data.mode)
  ) {
    return { status: data.status, version: data.version, mode: data.mode }
  }
  throw new ApiError({
    status: 200,
    code: 'invalid_response',
    message: 'Unexpected health response from the server.',
    details: data,
  })
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return parseHealth(await api.get<unknown>('/health', { signal }))
}

export const HEALTH_POLL_INTERVAL_MS = 15_000

export const healthQueryOptions = queryOptions({
  queryKey: ['health'] as const,
  queryFn: ({ signal }) => fetchHealth(signal),
  refetchInterval: HEALTH_POLL_INTERVAL_MS,
  refetchIntervalInBackground: false,
  staleTime: 10_000,
  retry: 1,
})

/** Polls backend health; drives the connection indicator and trading-mode badge. */
export function useHealthQuery() {
  return useQuery(healthQueryOptions)
}
