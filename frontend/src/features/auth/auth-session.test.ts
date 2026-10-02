import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'

import { apiClient, setOrganizationId } from '../../lib/api'
import { server } from '../../test/server'
import { user } from '../../test/fixtures'
import { useAuthStore } from './auth-store'

const expiredAccess = {
  error: { code: 'ACCESS_TOKEN_EXPIRED', message: '访问令牌已过期' },
}
const invalidRefresh = {
  error: { code: 'INVALID_REFRESH_TOKEN', message: '登录状态已失效' },
}

describe('auth session recovery', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    setOrganizationId(null)
    useAuthStore.setState({
      phase: 'initializing',
      sessionId: null,
      initialized: false,
      initializing: false,
      token: null,
      user: null,
      lastUserId: null,
      expiresAtMs: null,
      issuedTtlSeconds: null,
      epoch: 0,
      tokenVersion: 0,
      sessionStartedAtMs: null,
      notice: null,
    })
  })

  it('refreshes before sending a protected request near expiry', async () => {
    let refreshes = 0
    let authorization = ''
    server.use(
      http.post('/api/v1/auth/refresh', () => {
        refreshes += 1
        return HttpResponse.json({ access_token: 'fresh-token', expires_in: 900 })
      }),
      http.get('/api/v1/auth/me', () => HttpResponse.json(user)),
      http.get('/api/v1/projects', ({ request }) => {
        authorization = request.headers.get('Authorization') ?? ''
        return HttpResponse.json({ items: [] })
      }),
    )
    signedInNearExpiry()
    await apiClient.get('/projects')
    expect(refreshes).toBe(1)
    expect(authorization).toBe('Bearer fresh-token')
  })

  it('retries an expired platform request once and coalesces 20 concurrent refreshes', async () => {
    let refreshes = 0
    let oldRequests = 0
    let newRequests = 0
    let releaseOldRequests: (() => void) | undefined
    const allOldRequests = new Promise<void>((resolve) => {
      releaseOldRequests = resolve
    })
    server.use(
      http.post('/api/v1/auth/refresh', () => {
        refreshes += 1
        return HttpResponse.json({ access_token: 'fresh-token', expires_in: 900 })
      }),
      http.get('/api/v1/auth/me', () => HttpResponse.json(user)),
      http.get('/api/v1/projects', async ({ request }) => {
        if (request.headers.get('Authorization') === 'Bearer old-token') {
          oldRequests += 1
          if (oldRequests === 20) releaseOldRequests?.()
          await allOldRequests
          return HttpResponse.json(expiredAccess, { status: 401 })
        }
        newRequests += 1
        return HttpResponse.json({ items: [] })
      }),
    )
    signedIn()
    const responses = await Promise.all(
      Array.from({ length: 20 }, () => apiClient.get('/projects')),
    )
    expect(responses).toHaveLength(20)
    expect(oldRequests).toBe(20)
    expect(newRequests).toBe(20)
    expect(refreshes).toBe(1)
  })

  it('keeps a candidate token when me is temporarily unavailable', async () => {
    let refreshes = 0
    let meCalls = 0
    server.use(
      http.post('/api/v1/auth/refresh', () => {
        refreshes += 1
        return HttpResponse.json({ access_token: 'candidate-token', expires_in: 900 })
      }),
      http.get('/api/v1/auth/me', () => {
        meCalls += 1
        return meCalls === 1 ? HttpResponse.json({}, { status: 503 }) : HttpResponse.json(user)
      }),
    )
    await useAuthStore.getState().initialize()
    expect(useAuthStore.getState().phase).toBe('temporarily-unavailable')
    await useAuthStore.getState().initialize()
    expect(useAuthStore.getState().token).toBe('candidate-token')
    expect(refreshes).toBe(1)
  })

  it('ends a definitely invalid session once without treating a 403 as expiry', async () => {
    let refreshes = 0
    server.use(
      http.post('/api/v1/auth/refresh', () => {
        refreshes += 1
        return HttpResponse.json(invalidRefresh, { status: 401 })
      }),
      http.get('/api/v1/projects', () => HttpResponse.json({}, { status: 403 })),
    )
    signedIn()
    await expect(apiClient.get('/projects')).rejects.toMatchObject({ response: { status: 403 } })
    expect(refreshes).toBe(0)
    signedInNearExpiry()
    await expect(apiClient.get('/projects')).rejects.toMatchObject({ response: { status: 401 } })
    expect(useAuthStore.getState().phase).toBe('anonymous')
    expect(useAuthStore.getState().notice).toContain('重新登录')
    expect(refreshes).toBe(1)
  })

  it('requires reauthentication for an invalid access token without refreshing', async () => {
    let refreshes = 0
    server.use(
      http.post('/api/v1/auth/refresh', () => {
        refreshes += 1
        return HttpResponse.json({ access_token: 'fresh-token', expires_in: 900 })
      }),
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ error: { code: 'INVALID_ACCESS_TOKEN' } }, { status: 401 }),
      ),
    )
    signedIn()
    await expect(apiClient.get('/projects')).rejects.toMatchObject({ response: { status: 401 } })
    expect(refreshes).toBe(0)
    expect(useAuthStore.getState().phase).toBe('anonymous')
  })

  it('keeps the current user during a temporary refresh failure', async () => {
    server.use(http.post('/api/v1/auth/refresh', () => HttpResponse.json({}, { status: 503 })))
    signedInNearExpiry()
    await expect(apiClient.get('/projects')).rejects.toMatchObject({ response: { status: 503 } })
    expect(useAuthStore.getState()).toMatchObject({
      phase: 'temporarily-unavailable',
      token: 'old-token',
      user,
    })
  })

  it('does not replay a form body after an expired-token response', async () => {
    let refreshes = 0
    let writes = 0
    server.use(
      http.post('/api/v1/auth/refresh', () => {
        refreshes += 1
        return HttpResponse.json({ access_token: 'fresh-token', expires_in: 900 })
      }),
      http.post('/api/v1/projects', () => {
        writes += 1
        return HttpResponse.json(expiredAccess, { status: 401 })
      }),
    )
    signedIn()
    const body = new FormData()
    body.append('name', 'example')
    await expect(apiClient.post('/projects', body)).rejects.toMatchObject({
      response: { status: 401 },
    })
    expect(writes).toBe(1)
    expect(refreshes).toBe(0)
  })

  it('stops after one replay when the retried request also reports expiry', async () => {
    let refreshes = 0
    let reads = 0
    server.use(
      http.post('/api/v1/auth/refresh', () => {
        refreshes += 1
        return HttpResponse.json({ access_token: 'fresh-token', expires_in: 900 })
      }),
      http.get('/api/v1/auth/me', () => HttpResponse.json(user)),
      http.get('/api/v1/projects', () => {
        reads += 1
        return HttpResponse.json(expiredAccess, { status: 401 })
      }),
    )
    signedIn()
    await expect(apiClient.get('/projects')).rejects.toMatchObject({ response: { status: 401 } })
    expect(reads).toBe(2)
    expect(refreshes).toBe(1)
  })

  it('reuses a newer token for a late expired response', async () => {
    let refreshes = 0
    let replacementReads = 0
    let releaseOld: (() => void) | undefined
    let oldRequestStarted: (() => void) | undefined
    const waiting = new Promise<void>((resolve) => {
      releaseOld = resolve
    })
    const started = new Promise<void>((resolve) => {
      oldRequestStarted = resolve
    })
    server.use(
      http.post('/api/v1/auth/refresh', () => {
        refreshes += 1
        return HttpResponse.json({ access_token: 'unexpected-token', expires_in: 900 })
      }),
      http.get('/api/v1/projects', async ({ request }) => {
        if (request.headers.get('Authorization') === 'Bearer old-token') {
          oldRequestStarted?.()
          await waiting
          return HttpResponse.json(expiredAccess, { status: 401 })
        }
        replacementReads += 1
        expect(request.headers.get('Authorization')).toBe('Bearer replacement-token')
        return HttpResponse.json({ items: [] })
      }),
    )
    signedIn()
    const pending = apiClient.get('/projects')
    await started
    useAuthStore.setState({ token: 'replacement-token', tokenVersion: 2 })
    releaseOld?.()
    await pending
    expect(replacementReads).toBe(1)
    expect(refreshes).toBe(0)
  })

  it('rejects a late response after the organization changes', async () => {
    let release: (() => void) | undefined
    let requestStarted: (() => void) | undefined
    const waiting = new Promise<void>((resolve) => {
      release = resolve
    })
    const started = new Promise<void>((resolve) => {
      requestStarted = resolve
    })
    server.use(
      http.get('/api/v1/projects', async () => {
        requestStarted?.()
        await waiting
        return HttpResponse.json({ items: [] })
      }),
    )
    signedIn()
    setOrganizationId('organization-a')
    const pending = apiClient.get('/projects')
    await started
    setOrganizationId('organization-b')
    release?.()
    await expect(pending).rejects.toThrow('登录身份已变化')
    setOrganizationId(null)
  })

  it.each(['refresh', 'me'])('keeps a new login when an old %s failure arrives', async (stage) => {
    const started = deferred()
    const release = deferred()
    const nextUser = { ...user, id: 'new-user', email: 'new@example.com' }
    server.use(
      http.post('/api/v1/auth/refresh', async () => {
        if (stage === 'refresh') {
          started.resolve()
          await release.promise
          return HttpResponse.json(invalidRefresh, { status: 401 })
        }
        return HttpResponse.json({ access_token: 'old-candidate', expires_in: 900 })
      }),
      http.get('/api/v1/auth/me', async () => {
        started.resolve()
        await release.promise
        return HttpResponse.json({ error: { code: 'INVALID_ACCESS_TOKEN' } }, { status: 401 })
      }),
      http.post('/api/v1/auth/login', () =>
        HttpResponse.json({ access_token: 'new-token', expires_in: 900, user: nextUser }),
      ),
    )
    signedInNearExpiry()
    const oldRequest = useAuthStore
      .getState()
      .requestAccessToken()
      .catch((error: unknown) => error)
    await started.promise
    useAuthStore.setState({ epoch: useAuthStore.getState().epoch + 1, user: null, token: null })
    await useAuthStore.getState().login({ email: nextUser.email, password: 'test-password' })
    const newEpoch = useAuthStore.getState().epoch
    release.resolve()
    await oldRequest
    expect(useAuthStore.getState()).toMatchObject({
      phase: 'authenticated',
      user: nextUser,
      token: 'new-token',
      epoch: newEpoch,
      notice: null,
    })
  })

  it('classifies an invalid initialization candidate once as anonymous', async () => {
    server.use(
      http.post('/api/v1/auth/refresh', () =>
        HttpResponse.json({ access_token: 'invalid-candidate', expires_in: 900 }),
      ),
      http.get('/api/v1/auth/me', () =>
        HttpResponse.json({ error: { code: 'INVALID_ACCESS_TOKEN' } }, { status: 401 }),
      ),
    )
    const epoch = useAuthStore.getState().epoch
    await useAuthStore.getState().initialize()
    expect(useAuthStore.getState()).toMatchObject({
      phase: 'anonymous',
      token: null,
      user: null,
      epoch: epoch + 1,
    })
  })

  it.each(['account', 'organization'])(
    'does not replay an expired request across a changed %s',
    async (boundary) => {
      const started = deferred()
      const release = deferred()
      let refreshes = 0
      let requests = 0
      server.use(
        http.get('/api/v1/projects', async () => {
          requests += 1
          started.resolve()
          await release.promise
          return HttpResponse.json(expiredAccess, { status: 401 })
        }),
        http.post('/api/v1/auth/refresh', () => {
          refreshes += 1
          return HttpResponse.json({ access_token: 'unexpected', expires_in: 900 })
        }),
        http.post('/api/v1/auth/login', () =>
          HttpResponse.json({
            access_token: 'new-token',
            expires_in: 900,
            user: { ...user, id: 'new-user' },
          }),
        ),
      )
      signedIn()
      const request = apiClient.get('/projects').catch((error: unknown) => error)
      await started.promise
      if (boundary === 'account')
        await useAuthStore.getState().login({ email: 'new@example.com', password: 'test-password' })
      else setOrganizationId('new-organization')
      release.resolve()
      await request
      expect(refreshes).toBe(0)
      expect(requests).toBe(1)
    },
  )

  it('rejects a token response without a valid TTL', async () => {
    server.use(
      http.post('/api/v1/auth/login', () =>
        HttpResponse.json({ access_token: 'missing-ttl', user }),
      ),
    )
    await expect(
      useAuthStore.getState().login({ email: user.email, password: 'test-password' }),
    ).rejects.toThrow('认证响应缺少有效令牌期限')
    expect(useAuthStore.getState().token).toBeNull()
  })
})

function signedIn() {
  useAuthStore.setState({
    phase: 'authenticated',
    initialized: true,
    token: 'old-token',
    user,
    lastUserId: user.id,
    expiresAtMs: Date.now() + 900_000,
    issuedTtlSeconds: 900,
    tokenVersion: 1,
  })
}

function signedInNearExpiry() {
  signedIn()
  useAuthStore.setState({ expiresAtMs: Date.now() + 1000 })
}

function deferred() {
  let resolve!: () => void
  const promise = new Promise<void>((done) => {
    resolve = done
  })
  return { promise, resolve }
}
