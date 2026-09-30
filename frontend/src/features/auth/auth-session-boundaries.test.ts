import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createStore } from 'zustand/vanilla'

import { SessionBoundaryError } from '../../lib/auth-client'
import { user } from '../../test/fixtures'
import { server } from '../../test/server'
import { AuthSessionCoordinator, type SessionSnapshot } from './auth-session'
import { AuthSessionLifecycle, PENDING_LOGOUT_KEY, SESSION_KEY } from './auth-session-lifecycle'
import { useAuthStore } from './auth-store'

describe('authentication operation boundaries', () => {
  const receivers = new Set<{ onmessage: ((event: { data: unknown }) => void) | null }>()
  const cleanups: Array<() => void> = []
  let delivery = true
  let lastEvent: unknown

  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    receivers.clear()
    delivery = true
    lastEvent = null
    vi.stubGlobal(
      'BroadcastChannel',
      class {
        onmessage: ((event: { data: unknown }) => void) | null = null
        constructor() {
          receivers.add(this)
        }
        postMessage(data: unknown) {
          lastEvent = data
          if (delivery) {
            for (const receiver of receivers) {
              if (receiver !== this) receiver.onmessage?.({ data })
            }
          }
        }
      },
    )
  })

  afterEach(() => {
    cleanups.splice(0).forEach((cleanup) => cleanup())
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it.each([200, 401, 503])(
    'ignores a late me status %s after same-account login with Web Locks',
    async (status) => {
      serialBrowserLocks()
      const oldMe = deferred()
      const release = deferred()
      server.use(
        http.post('/api/v1/auth/refresh', () => tokenResponse('old-candidate')),
        http.get('/api/v1/auth/me', async () => {
          oldMe.resolve()
          await release.promise
          return status === 200
            ? HttpResponse.json(user)
            : HttpResponse.json({ error: { code: 'INVALID_ACCESS_TOKEN' } }, { status })
        }),
        http.post('/api/v1/auth/login', () => loginResponse('new-token')),
      )
      const { coordinator, store } = session()
      const old = coordinator.ensureFreshAccessToken().catch((error: unknown) => error)
      await oldMe.promise
      await coordinator.login({ email: user.email, password: 'test-password' })
      const current = store.getState()
      release.resolve()
      await old
      expect(store.getState()).toMatchObject({
        epoch: current.epoch,
        sessionId: current.sessionId,
        token: 'new-token',
        user,
        phase: 'authenticated',
        initialized: true,
        initializing: false,
        notice: null,
      })
    },
  )

  it.each([200, 401])(
    'keeps new initialization markers when old finally arrives with status %s',
    async (status) => {
      const oldStarted = deferred()
      const releaseOld = deferred()
      const newStarted = deferred()
      const releaseNew = deferred()
      let refreshes = 0
      server.use(
        http.post('/api/v1/auth/refresh', async () => {
          refreshes += 1
          if (refreshes === 1) {
            oldStarted.resolve()
            await releaseOld.promise
            return status === 200 ? tokenResponse('old-token') : invalidRefresh()
          }
          newStarted.resolve()
          await releaseNew.promise
          return tokenResponse('new-token')
        }),
        http.get('/api/v1/auth/me', () => HttpResponse.json(user)),
      )
      const { coordinator, store } = session(false)
      const old = coordinator.initialize()
      await oldStarted.promise
      store.setState({ epoch: 1, sessionId: null, initializing: false })
      const current = coordinator.initialize()
      await newStarted.promise
      releaseOld.resolve()
      await old
      expect(store.getState()).toMatchObject({ initializing: true, initialized: false, epoch: 1 })
      expect(coordinator.initialize()).toBe(current)
      store.setState({ user, token: 'pending-token' })
      const tokenRequest = coordinator.ensureFreshAccessToken()
      await Promise.resolve()
      expect(refreshes).toBe(2)
      releaseNew.resolve()
      await Promise.all([current, tokenRequest])
      expect(store.getState()).toMatchObject({
        phase: 'authenticated',
        token: 'new-token',
        epoch: 1,
      })
    },
  )

  it('does not send a queued refresh after logout advances the epoch', async () => {
    const requested = deferred()
    const acquired = deferred()
    let locks = 0
    let refreshes = 0
    let logouts = 0
    browserLocks(async (operation) => {
      locks += 1
      if (locks === 1) {
        requested.resolve()
        await acquired.promise
      }
      return operation()
    })
    server.use(
      http.post('/api/v1/auth/refresh', () => {
        refreshes += 1
        return tokenResponse('unexpected')
      }),
      http.post('/api/v1/auth/logout', () => {
        logouts += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const { coordinator, store } = session()
    const refresh = coordinator.ensureFreshAccessToken().catch((error: unknown) => error)
    await requested.promise
    const logout = coordinator.logout()
    acquired.resolve()
    expect(await refresh).toBeInstanceOf(SessionBoundaryError)
    await logout
    expect(refreshes).toBe(0)
    expect(logouts).toBe(1)
    expect(store.getState().phase).toBe('anonymous')
  })

  it.each(['legacy', 'current'])(
    'resolves %s pending logout before password login',
    async (kind) => {
      const lifecycle = new AuthSessionLifecycle()
      const old = lifecycle.startSession(user.id)
      if (kind === 'legacy') localStorage.setItem('flowtest:logout-pending:v1', '1')
      else lifecycle.beginLogout(old.id)
      const calls: string[] = []
      server.use(
        http.post('/api/v1/auth/logout', () => {
          calls.push('logout')
          return new HttpResponse(null, { status: 204 })
        }),
        http.post('/api/v1/auth/login', () => {
          calls.push('login')
          return loginResponse('new-token')
        }),
      )
      const { coordinator, store } = session(false)
      await coordinator.login({ email: user.email, password: 'test-password' })
      expect(calls).toEqual(['logout', 'login'])
      expect(lifecycle.pendingLogout()).toBeNull()
      expect(store.getState()).toMatchObject({ phase: 'authenticated', token: 'new-token' })
      expect(store.getState().sessionId).not.toBe(old.id)
      expect(JSON.parse(localStorage.getItem(SESSION_KEY)!)).toEqual({
        id: store.getState().sessionId,
        userId: user.id,
      })
    },
  )

  it('preserves an unconfirmed logout when OIDC preparation fails', async () => {
    localStorage.setItem('flowtest:logout-pending:v1', '1')
    server.use(http.post('/api/v1/auth/logout', () => HttpResponse.json({}, { status: 503 })))
    const { coordinator, store } = session(false)
    await expect(coordinator.prepareOIDCLogin()).rejects.toMatchObject({
      response: { status: 503 },
    })
    expect(localStorage.getItem('flowtest:logout-pending:v1')).toBe('1')
    expect(sessionStorage.getItem('flowtest:oidc-attempt:v1')).toBeNull()
    expect(store.getState().user).toBeNull()
  })

  it('does not logout a new OIDC cookie after resolving a legacy intent before navigation', async () => {
    localStorage.setItem('flowtest:logout-pending:v1', '1')
    const calls: string[] = []
    server.use(
      http.post('/api/v1/auth/logout', () => {
        calls.push('logout')
        return new HttpResponse(null, { status: 204 })
      }),
      http.post('/api/v1/auth/refresh', () => {
        calls.push('refresh')
        return tokenResponse('oidc-token')
      }),
      http.get('/api/v1/auth/me', () => HttpResponse.json({ ...user, oidc_provider: 'company' })),
    )
    await session(false).coordinator.prepareOIDCLogin()
    const attempt = sessionStorage.getItem('flowtest:oidc-attempt:v1')
    expect(attempt).toBeTruthy()
    const returned = session(false)
    await returned.coordinator.initialize()
    expect(calls).toEqual(['logout', 'refresh'])
    expect(returned.store.getState()).toMatchObject({
      phase: 'authenticated',
      token: 'oidc-token',
      sessionId: attempt,
    })
    expect(sessionStorage.getItem('flowtest:oidc-attempt:v1')).toBeNull()
  })

  it('keeps pending logout blocking restoration when no interactive login was started', async () => {
    localStorage.setItem('flowtest:logout-pending:v1', '1')
    let refreshes = 0
    server.use(
      http.post('/api/v1/auth/logout', () => HttpResponse.json({}, { status: 503 })),
      http.post('/api/v1/auth/refresh', () => {
        refreshes += 1
        return tokenResponse('unexpected')
      }),
    )
    const { coordinator, store } = session(false)
    await coordinator.initialize()
    expect(store.getState()).toMatchObject({ phase: 'anonymous', token: null, user: null })
    expect(store.getState().notice).toContain('尚未确认')
    expect(refreshes).toBe(0)
    expect(localStorage.getItem('flowtest:logout-pending:v1')).toBe('1')
  })

  it.each([204, 503])(
    'stops another open tab as soon as logout is requested, status=%s',
    async (status) => {
      let refreshes = 0
      server.use(
        http.post('/api/v1/auth/logout', () => new HttpResponse(null, { status })),
        http.post('/api/v1/auth/refresh', () => {
          refreshes += 1
          return tokenResponse('unexpected')
        }),
      )
      const first = session()
      const second = session()
      first.store.setState({ expiresAtMs: Date.now() + 900_000 })
      second.store.setState({ expiresAtMs: Date.now() + 900_000 })
      await first.coordinator.ensureFreshAccessToken()
      await second.coordinator.ensureFreshAccessToken()
      const logout = first.coordinator.logout()
      expect(second.store.getState().phase).toBe('anonymous')
      await expect(second.coordinator.ensureFreshAccessToken()).rejects.toBeInstanceOf(
        SessionBoundaryError,
      )
      await logout
      expect(refreshes).toBe(0)
      expect(new AuthSessionLifecycle().pendingLogout() === null).toBe(status === 204)
    },
  )

  it('uses storage events and request preflight without BroadcastChannel', async () => {
    vi.stubGlobal('BroadcastChannel', undefined)
    const { coordinator, store } = session()
    store.setState({ expiresAtMs: Date.now() + 900_000 })
    await coordinator.ensureFreshAccessToken()
    cleanups.push(coordinator.registerRecoveryListeners())
    new AuthSessionLifecycle().beginLogout(store.getState().sessionId)
    window.dispatchEvent(new StorageEvent('storage', { key: PENDING_LOGOUT_KEY }))
    expect(store.getState().phase).toBe('anonymous')
    await expect(coordinator.recoverExpiredAccessToken(1)).rejects.toBeInstanceOf(
      SessionBoundaryError,
    )
  })

  it('handles a logout storage event after the server confirmation already cleared pending', async () => {
    vi.stubGlobal('BroadcastChannel', undefined)
    const { coordinator, store } = session()
    store.setState({ expiresAtMs: Date.now() + 900_000 })
    await coordinator.ensureFreshAccessToken()
    cleanups.push(coordinator.registerRecoveryListeners())
    const lifecycle = new AuthSessionLifecycle()
    const intent = lifecycle.beginLogout(store.getState().sessionId)
    lifecycle.completeLogout(intent)
    window.dispatchEvent(
      new StorageEvent('storage', { key: PENDING_LOGOUT_KEY, newValue: JSON.stringify(intent) }),
    )
    expect(store.getState().phase).toBe('anonymous')
  })

  it('checks stored logout intent again before publishing a refresh result', async () => {
    delivery = false
    const started = deferred()
    const release = deferred()
    server.use(
      http.post('/api/v1/auth/refresh', () => tokenResponse('candidate')),
      http.get('/api/v1/auth/me', async () => {
        started.resolve()
        await release.promise
        return HttpResponse.json(user)
      }),
    )
    const { coordinator, store } = session()
    const refresh = coordinator.ensureFreshAccessToken().catch((error: unknown) => error)
    await started.promise
    new AuthSessionLifecycle().beginLogout(store.getState().sessionId)
    release.resolve()
    expect(await refresh).toBeInstanceOf(SessionBoundaryError)
    expect(store.getState()).toMatchObject({ phase: 'anonymous', token: null })
  })

  it('ignores old logout messages and pending markers after same-account reauthentication', async () => {
    delivery = false
    server.use(
      http.post('/api/v1/auth/logout', () => HttpResponse.json({}, { status: 503 })),
      http.post('/api/v1/auth/login', () => loginResponse('new-token')),
    )
    const { coordinator, store } = session()
    await coordinator.logout()
    const oldIntent = new AuthSessionLifecycle().pendingLogout()!
    server.use(http.post('/api/v1/auth/logout', () => new HttpResponse(null, { status: 204 })))
    await coordinator.login({ email: user.email, password: 'test-password' })
    const epoch = store.getState().epoch
    for (const receiver of receivers) receiver.onmessage?.({ data: lastEvent })
    localStorage.setItem(PENDING_LOGOUT_KEY, JSON.stringify(oldIntent))
    expect(await coordinator.ensureFreshAccessToken()).toBe('new-token')
    expect(store.getState()).toMatchObject({ phase: 'authenticated', token: 'new-token', epoch })
  })

  it('creates non-sensitive generations on HTTP browsers without randomUUID', () => {
    vi.stubGlobal('crypto', { getRandomValues: crypto.getRandomValues.bind(crypto) })
    const lifecycle = new AuthSessionLifecycle()
    const first = lifecycle.startSession(user.id)
    const second = lifecycle.startSession(user.id)
    expect(first.id).toMatch(/^[a-f0-9]{32}$/)
    expect(second.id).not.toBe(first.id)
  })

  it('does not clear a newer pending logout when an older confirmation completes', () => {
    const lifecycle = new AuthSessionLifecycle()
    const session = lifecycle.startSession(user.id)
    const old = lifecycle.beginLogout(session.id)
    const current = lifecycle.beginLogout(session.id)
    lifecycle.completeLogout(old)
    expect(lifecycle.pendingLogout()).toEqual(current)
  })

  it('still calls server logout when storage reads work but quota rejects writes', async () => {
    new AuthSessionLifecycle().startSession(user.id)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('Quota exceeded', 'QuotaExceededError')
    })
    let logouts = 0
    server.use(
      http.post('/api/v1/auth/logout', () => {
        logouts += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const { coordinator, store } = session()
    await coordinator.logout()
    expect(logouts).toBe(1)
    expect(store.getState()).toMatchObject({
      phase: 'anonymous',
      user: null,
      token: null,
      notice: null,
    })
  })

  it('preserves failed in-memory logout intent through a later explicit login when writes are rejected', async () => {
    new AuthSessionLifecycle().startSession(user.id)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('Quota exceeded', 'QuotaExceededError')
    })
    let logouts = 0
    server.use(
      http.post('/api/v1/auth/logout', () => {
        logouts += 1
        return logouts === 1
          ? HttpResponse.json({}, { status: 503 })
          : new HttpResponse(null, { status: 204 })
      }),
      http.post('/api/v1/auth/login', () => loginResponse('new-token')),
    )
    const { coordinator, store } = session()
    await coordinator.logout()
    expect(store.getState().notice).toContain('尚未确认')
    await coordinator.login({ email: user.email, password: 'test-password' })
    expect(logouts).toBe(2)
    expect(store.getState()).toMatchObject({
      phase: 'authenticated',
      user,
      token: 'new-token',
      notice: null,
    })
  })

  it('keeps a pending logout blocking restoration when shared generation metadata was lost', async () => {
    const lifecycle = new AuthSessionLifecycle()
    const old = lifecycle.startSession(user.id)
    lifecycle.beginLogout(old.id)
    localStorage.removeItem(SESSION_KEY)
    server.use(http.post('/api/v1/auth/logout', () => HttpResponse.json({}, { status: 503 })))
    const { coordinator, store } = session(false)
    await coordinator.initialize()
    expect(store.getState()).toMatchObject({ phase: 'anonymous', token: null, user: null })
    expect(lifecycle.pendingLogout()?.sessionId).toBe(old.id)
  })

  it('conservatively blocks unknown pending data instead of restoring a cookie', async () => {
    localStorage.setItem(PENDING_LOGOUT_KEY, '{malformed')
    server.use(http.post('/api/v1/auth/logout', () => HttpResponse.json({}, { status: 503 })))
    const { coordinator, store } = session(false)
    await coordinator.initialize()
    expect(store.getState()).toMatchObject({ phase: 'anonymous', user: null, token: null })
    expect(localStorage.getItem(PENDING_LOGOUT_KEY)).toBe('{malformed')
  })

  it('ends a stale local generation when another tab starts a new login', async () => {
    const { coordinator, store } = session()
    store.setState({ expiresAtMs: Date.now() + 900_000 })
    await coordinator.ensureFreshAccessToken()
    new AuthSessionLifecycle().startSession('another-user')
    await expect(coordinator.ensureFreshAccessToken()).rejects.toBeInstanceOf(SessionBoundaryError)
    expect(store.getState().phase).toBe('anonymous')
  })
})

function session(authenticated = true) {
  const store = createStore<SessionSnapshot>(() => ({
    ...useAuthStore.getState(),
    phase: authenticated ? 'authenticated' : 'initializing',
    initialized: authenticated,
    initializing: false,
    user: authenticated ? user : null,
    token: authenticated ? 'old-token' : null,
    lastUserId: authenticated ? user.id : null,
    epoch: 0,
    tokenVersion: 1,
    organizationId: null,
    sessionId: null,
    sessionStartedAtMs: null,
    expiresAtMs: Date.now() + 1000,
    issuedTtlSeconds: 900,
    notice: null,
  }))
  const coordinator = new AuthSessionCoordinator({ read: store.getState, write: store.setState })
  return { coordinator, store }
}

function deferred() {
  let resolve!: () => void
  const promise = new Promise<void>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function tokenResponse(token: string) {
  return HttpResponse.json({ access_token: token, expires_in: 900 })
}

function loginResponse(token: string) {
  return HttpResponse.json({ access_token: token, expires_in: 900, user })
}

function invalidRefresh() {
  return HttpResponse.json({ error: { code: 'INVALID_REFRESH_TOKEN' } }, { status: 401 })
}

function browserLocks(request: (operation: () => Promise<unknown>) => Promise<unknown>) {
  vi.stubGlobal('isSecureContext', true)
  vi.stubGlobal(
    'navigator',
    Object.assign(Object.create(navigator), {
      locks: {
        request: (_name: string, _options: unknown, operation: () => Promise<unknown>) =>
          request(operation),
      },
    }),
  )
}

function serialBrowserLocks() {
  let tail = Promise.resolve<unknown>(undefined)
  browserLocks((operation) => {
    const pending = tail.then(operation)
    tail = pending.catch(() => undefined)
    return pending
  })
}
