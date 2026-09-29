import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { useAuthStore } from '../features/auth/auth-store'
import { user } from '../test/fixtures'
import { server } from '../test/server'
import {
  apiClient,
  apiErrorMessage,
  createPlatformApiClient,
  shouldSkipAutomaticQueryRetry,
  type PlatformAuthPort,
} from './api'

describe('platform request scope', () => {
  it('binds each client to its injected authentication owner', async () => {
    server.use(
      http.get('/api/v1/projects', ({ request }) =>
        HttpResponse.json({ authorization: request.headers.get('Authorization') }),
      ),
    )
    const first = createPlatformApiClient(authPort('first-user', 'first-token'))
    const second = createPlatformApiClient(authPort('second-user', 'second-token'))
    expect((await first.get('/projects')).data.authorization).toBe('Bearer first-token')
    expect((await second.get('/projects')).data.authorization).toBe('Bearer second-token')
    expect((await first.get('/projects')).data.authorization).toBe('Bearer first-token')
  })

  it('rejects absolute and protocol-relative URLs before attaching a platform token', async () => {
    await expect(apiClient.get('//external.example/collect')).rejects.toThrow(
      '平台请求不允许使用外部地址',
    )
    await expect(apiClient.get('HTTPS://external.example/collect')).rejects.toThrow(
      '平台请求不允许使用外部地址',
    )
  })

  it('does not automatically retry a rate-limited platform request', () => {
    expect(shouldSkipAutomaticQueryRetry({ isAxiosError: true, response: { status: 429 } })).toBe(
      true,
    )
  })
})

function authPort(userId: string, token: string): PlatformAuthPort {
  const snapshot = {
    ...useAuthStore.getState(),
    phase: 'authenticated' as const,
    initialized: true,
    token,
    user: { ...user, id: userId },
    organizationId: null,
    expiresAtMs: Date.now() + 900_000,
    issuedTtlSeconds: 900,
  }
  return {
    snapshot: () => snapshot,
    ensureFreshAccessToken: async () => token,
    recoverExpiredAccessToken: async () => token,
    rejectInvalidAccessToken: () => undefined,
  }
}

describe('apiErrorMessage', () => {
  it('uses the structured backend message', () => {
    expect(
      apiErrorMessage({
        isAxiosError: true,
        message: 'Request failed',
        response: { data: { error: { message: '项目不存在' } } },
      }),
    ).toBe('项目不存在')
  })

  it('falls back for ordinary and unknown errors', () => {
    expect(apiErrorMessage({ isAxiosError: true, message: 'request timeout' })).toBe(
      'request timeout',
    )
    expect(apiErrorMessage(new Error('network unavailable'))).toBe('network unavailable')
    expect(apiErrorMessage(null)).toBe('请求失败，请稍后重试')
  })
})
