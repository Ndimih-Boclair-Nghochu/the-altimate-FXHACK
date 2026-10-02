import { describe, expect, it, vi } from 'vitest'

import { jsonResponse } from '@/test/utils'

import { api, ApiError, apiFetch, buildApiUrl, fetchHealth, parseHealth } from './api'

describe('buildApiUrl', () => {
  it('prefixes /api and encodes query parameters, dropping empty ones', () => {
    expect(buildApiUrl('health')).toBe('/api/health')
    expect(buildApiUrl('/trades', { limit: 50, instrument: 'EUR_USD', cursor: undefined })).toBe(
      '/api/trades?limit=50&instrument=EUR_USD',
    )
  })
})

describe('apiFetch', () => {
  it('sends credentials and JSON headers, and parses JSON', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(jsonResponse({ ok: true })))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.post<{ ok: boolean }>('/things', { a: 1 })).resolves.toEqual({ ok: true })

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/things')
    expect(init.method).toBe('POST')
    expect(init.credentials).toBe('include')
    expect(init.body).toBe('{"a":1}')
    const headers = new Headers(init.headers)
    expect(headers.get('Content-Type')).toBe('application/json')
    expect(headers.get('Accept')).toBe('application/json')
  })

  it('turns FastAPI error bodies into a typed ApiError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(jsonResponse({ detail: 'Not authenticated' }, 401))),
    )

    const error = await apiFetch('/secure').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      status: 401,
      code: 'unauthorized',
      message: 'Not authenticated',
    })
  })

  it('joins validation error messages', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          jsonResponse({ detail: [{ msg: 'field required' }, { msg: 'must be > 0' }] }, 422),
        ),
      ),
    )
    await expect(apiFetch('/orders')).rejects.toMatchObject({
      code: 'validation_error',
      message: 'field required; must be > 0',
    })
  })

  it('reports network failures as status 0', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))),
    )
    const error = await apiFetch('/health').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).isNetworkError).toBe(true)
    expect((error as ApiError).code).toBe('network_error')
  })

  it('rethrows aborts untouched', async () => {
    const abort = new DOMException('Aborted', 'AbortError')
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(abort)),
    )
    await expect(apiFetch('/health')).rejects.toBe(abort)
  })

  it('rejects non-JSON success responses', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response('<html>', { status: 200 }))),
    )
    await expect(apiFetch('/health')).rejects.toMatchObject({ code: 'invalid_response' })
  })

  it('returns undefined for 204 No Content', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response(null, { status: 204 }))),
    )
    await expect(apiFetch('/thing', { method: 'DELETE' })).resolves.toBeUndefined()
  })
})

describe('health', () => {
  it('parses a valid health payload', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(jsonResponse({ status: 'ok', version: '0.1.0', mode: 'practice' })),
      ),
    )
    await expect(fetchHealth()).resolves.toEqual({
      status: 'ok',
      version: '0.1.0',
      mode: 'practice',
    })
  })

  it('rejects an unknown trading mode instead of displaying it', () => {
    expect(() => parseHealth({ status: 'ok', version: '1', mode: 'yolo' })).toThrow(ApiError)
    expect(() => parseHealth(null)).toThrow(ApiError)
  })
})
