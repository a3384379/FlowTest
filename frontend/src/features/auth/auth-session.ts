import axios from 'axios'

import { authClient, SessionBoundaryError } from '../../lib/auth-client'
import type { User } from '../../lib/api'

export type SessionPhase =
  | 'initializing'
  | 'anonymous'
  | 'authenticated'
  | 'refreshing'
  | 'temporarily-unavailable'
  | 'logging-out'

export type SessionSnapshot = {
  phase: SessionPhase
  initialized: boolean
  initializing: boolean
  token: string | null
  user: User | null
  lastUserId: string | null
  expiresAtMs: number | null
  issuedTtlSeconds: number | null
  epoch: number
  tokenVersion: number
  organizationId: string | null
  sessionStartedAtMs: number | null
  notice: string | null
}

type SessionPort = {
  read: () => SessionSnapshot
  write: (patch: Partial<SessionSnapshot>) => void
}

type TokenCandidate = { token: string; expiresAtMs: number; ttlSeconds: number; epoch: number }
type SessionEvent = {
  kind: 'logout' | 'password-changed' | 'refresh-done'
  userId: string
  atMs: number
}

const PENDING_LOGOUT_KEY = 'flowtest:logout-pending:v1'

export class AuthSessionCoordinator {
  private refreshTask: Promise<string> | null = null
  private initializeTask: Promise<void> | null = null
  private candidate: TokenCandidate | null = null
  private channel: BroadcastChannel | null = null
  private lastRecoveryCheck = 0

  constructor(private readonly port: SessionPort) {
    if (typeof BroadcastChannel !== 'undefined') {
      this.channel = new BroadcastChannel('flowtest-auth-session')
      this.channel.onmessage = (event: MessageEvent<SessionEvent>) => {
        const message = event.data
        if (
          (message.kind === 'logout' || message.kind === 'password-changed') &&
          this.snapshot().user?.id === message.userId &&
          message.atMs >= (this.snapshot().sessionStartedAtMs ?? 0)
        ) {
          this.invalidate('登录状态已变化，请重新登录')
        }
      }
    }
  }

  snapshot(): SessionSnapshot {
    return this.port.read()
  }

  initialize(): Promise<void> {
    if (this.snapshot().initialized && this.snapshot().phase !== 'temporarily-unavailable') {
      return Promise.resolve()
    }
    if (this.initializeTask) return this.initializeTask
    const task = this.restore()
    this.initializeTask = task
    void task
      .finally(() => {
        if (this.initializeTask === task) this.initializeTask = null
      })
      .catch(() => undefined)
    return task
  }

  private async restore(): Promise<void> {
    this.port.write({ initializing: true })
    try {
      if (pendingLogout()) {
        await this.withBrowserLock(() => authClient.post('/auth/logout'))
        setPendingLogout(false)
        this.port.write({ phase: 'anonymous', initialized: true, initializing: false })
        return
      }
      await this.refresh()
    } catch (error) {
      if (isCode(error, 'INVALID_REFRESH_TOKEN')) {
        if (this.snapshot().phase !== 'anonymous') this.invalidate(null)
      } else {
        this.temporaryFailure()
      }
    } finally {
      this.port.write({ initialized: true, initializing: false })
    }
  }

  async login(payload: { email: string; password: string }): Promise<void> {
    const startEpoch = this.snapshot().epoch + 1
    this.candidate = null
    this.port.write({ epoch: startEpoch, organizationId: null })
    const response = await this.withBrowserLock(() =>
      authClient.post<unknown>('/auth/login', payload),
    )
    const candidate = tokenCandidate(response.data, startEpoch)
    const user = userFromLogin(response.data)
    if (this.snapshot().epoch !== startEpoch) throw new SessionBoundaryError('登录身份已变化')
    this.publish(candidate, user)
    setPendingLogout(false)
  }

  async ensureFreshAccessToken(): Promise<string> {
    const snapshot = this.snapshot()
    if (snapshot.phase === 'logging-out') throw new SessionBoundaryError('正在退出登录')
    if (snapshot.token && !nearExpiry(snapshot.expiresAtMs, snapshot.issuedTtlSeconds)) {
      return snapshot.token
    }
    try {
      return await this.refresh()
    } catch (error) {
      if (
        this.snapshot().epoch === snapshot.epoch &&
        this.snapshot().phase === 'temporarily-unavailable' &&
        snapshot.token &&
        snapshot.expiresAtMs &&
        snapshot.expiresAtMs > Date.now() + 2000
      ) {
        return snapshot.token
      }
      throw error
    }
  }

  async recoverExpiredAccessToken(usedVersion: number | undefined): Promise<string> {
    const snapshot = this.snapshot()
    if (snapshot.phase === 'logging-out' || !snapshot.user) {
      throw new SessionBoundaryError('登录身份已变化')
    }
    if (snapshot.token && usedVersion !== snapshot.tokenVersion) return snapshot.token
    return this.refresh()
  }

  rejectInvalidAccessToken(usedVersion: number | undefined): void {
    const snapshot = this.snapshot()
    if (snapshot.user && snapshot.tokenVersion === usedVersion) {
      this.invalidate('登录状态已失效，请重新登录。')
    }
  }

  async changePassword(currentPassword: string, newPassword: string): Promise<void> {
    const token = await this.ensureFreshAccessToken()
    const snapshot = this.snapshot()
    await this.withBrowserLock(() =>
      authClient.post(
        '/auth/change-password',
        { current_password: currentPassword, new_password: newPassword },
        { headers: { Authorization: `Bearer ${token}` } },
      ),
    )
    if (this.snapshot().epoch !== snapshot.epoch) return
    if (snapshot.user) {
      this.channel?.postMessage({
        kind: 'password-changed',
        userId: snapshot.user.id,
        atMs: Date.now(),
      } satisfies SessionEvent)
    }
    this.invalidate('密码已修改，请重新登录。')
  }

  async logout(): Promise<void> {
    const snapshot = this.snapshot()
    setPendingLogout(true)
    this.port.write({ phase: 'logging-out', epoch: snapshot.epoch + 1 })
    try {
      if (this.refreshTask) {
        try {
          await this.refreshTask
        } catch {
          // The pending refresh has finished; logout must still revoke the current cookie.
        }
      }
      await this.withBrowserLock(() => authClient.post('/auth/logout'))
      setPendingLogout(false)
      if (snapshot.user) {
        this.channel?.postMessage({
          kind: 'logout',
          userId: snapshot.user.id,
          atMs: Date.now(),
        } satisfies SessionEvent)
      }
      this.invalidate(null)
    } catch {
      this.invalidate('本地已退出，但尚未确认服务端会话已注销。')
    }
  }

  registerRecoveryListeners(): () => void {
    const check = () => {
      if (Date.now() - this.lastRecoveryCheck < 1000) return
      this.lastRecoveryCheck = Date.now()
      const snapshot = this.snapshot()
      if (snapshot.phase === 'logging-out' || !snapshot.user) return
      if (nearExpiry(snapshot.expiresAtMs, snapshot.issuedTtlSeconds)) {
        void this.ensureFreshAccessToken().catch(() => undefined)
      }
    }
    const onVisibility = () => {
      if (document.visibilityState === 'visible') check()
    }
    window.addEventListener('focus', check)
    window.addEventListener('online', check)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.removeEventListener('focus', check)
      window.removeEventListener('online', check)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }

  private refresh(): Promise<string> {
    if (this.refreshTask) return this.refreshTask
    const task = this.performRefresh()
    this.refreshTask = task
    void task
      .finally(() => {
        if (this.refreshTask === task) this.refreshTask = null
      })
      .catch(() => undefined)
    return task
  }

  private async performRefresh(): Promise<string> {
    const start = this.snapshot()
    this.port.write({ phase: 'refreshing' })
    try {
      const candidate = await this.obtainCandidate(start.epoch)
      const user = await this.confirmCandidate(candidate, start)
      this.publish(candidate, user)
      this.candidate = null
      this.channel?.postMessage({
        kind: 'refresh-done',
        userId: user.id,
        atMs: Date.now(),
      } satisfies SessionEvent)
      return candidate.token
    } catch (error) {
      this.handleRefreshFailure(error, start)
      throw error
    }
  }

  private async obtainCandidate(epoch: number): Promise<TokenCandidate> {
    const candidate = this.candidate
    if (candidate && candidate.epoch === epoch && candidate.expiresAtMs > Date.now()) {
      return candidate
    }
    const refreshed = await this.withBrowserLock(async () => {
      try {
        return tokenCandidate((await authClient.post<unknown>('/auth/refresh')).data, epoch)
      } catch (error) {
        if (!isCode(error, 'REFRESH_ROTATION_CONFLICT')) throw error
        await new Promise((resolve) => window.setTimeout(resolve, 250))
        return tokenCandidate((await authClient.post<unknown>('/auth/refresh')).data, epoch)
      }
    })
    this.candidate = refreshed
    return refreshed
  }

  private async confirmCandidate(candidate: TokenCandidate, start: SessionSnapshot): Promise<User> {
    const me = await authClient.get<User>('/auth/me', {
      headers: { Authorization: `Bearer ${candidate.token}` },
    })
    if (this.snapshot().epoch !== start.epoch) throw new SessionBoundaryError('登录身份已变化')
    if (start.user && start.user.id !== me.data.id) {
      this.invalidate('账号已变化，请重新登录。')
      throw new SessionBoundaryError('账号已变化，请重新登录')
    }
    return me.data
  }

  private handleRefreshFailure(error: unknown, start: SessionSnapshot): void {
    if (isCode(error, 'INVALID_REFRESH_TOKEN') || isCode(error, 'INVALID_ACCESS_TOKEN')) {
      this.invalidate(start.user ? '登录状态已失效，请重新登录。' : null)
    } else if (this.snapshot().epoch === start.epoch) {
      this.temporaryFailure()
    }
  }

  private publish(candidate: TokenCandidate, user: User): void {
    const previous = this.snapshot()
    this.port.write({
      phase: 'authenticated',
      token: candidate.token,
      user,
      lastUserId: user.id,
      expiresAtMs: candidate.expiresAtMs,
      issuedTtlSeconds: candidate.ttlSeconds,
      tokenVersion: previous.tokenVersion + 1,
      sessionStartedAtMs: previous.user?.id === user.id ? previous.sessionStartedAtMs : Date.now(),
      initialized: true,
      initializing: false,
      notice: null,
    })
  }

  private invalidate(notice: string | null): void {
    const snapshot = this.snapshot()
    this.candidate = null
    this.port.write({
      phase: 'anonymous',
      token: null,
      user: null,
      lastUserId: snapshot.user?.id ?? snapshot.lastUserId,
      expiresAtMs: null,
      issuedTtlSeconds: null,
      sessionStartedAtMs: null,
      organizationId: null,
      epoch: snapshot.epoch + 1,
      initialized: true,
      initializing: false,
      notice,
    })
  }

  private temporaryFailure(): void {
    this.port.write({
      phase: 'temporarily-unavailable',
      initialized: true,
      initializing: false,
      notice: '认证服务暂时不可用，本次操作未完成，请稍后重试。',
    })
  }

  private async withBrowserLock<T>(operation: () => Promise<T>): Promise<T> {
    if (typeof navigator === 'undefined' || !window.isSecureContext || !navigator.locks) {
      return operation()
    }
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 35_000)
    try {
      return await navigator.locks.request(
        'flowtest-auth-session',
        { mode: 'exclusive', signal: controller.signal },
        operation,
      )
    } finally {
      window.clearTimeout(timeout)
    }
  }
}

function tokenCandidate(value: unknown, epoch: number): TokenCandidate {
  if (!value || typeof value !== 'object') throw new Error('认证响应格式错误')
  const response = value as { access_token?: unknown; expires_in?: unknown }
  if (
    typeof response.access_token !== 'string' ||
    !response.access_token ||
    typeof response.expires_in !== 'number' ||
    !Number.isFinite(response.expires_in) ||
    response.expires_in <= 0
  ) {
    throw new Error('认证响应缺少有效令牌期限')
  }
  return {
    token: response.access_token,
    expiresAtMs: Date.now() + response.expires_in * 1000,
    ttlSeconds: response.expires_in,
    epoch,
  }
}

function userFromLogin(value: unknown): User {
  if (!value || typeof value !== 'object' || !('user' in value)) {
    throw new Error('登录响应缺少用户信息')
  }
  const user = value.user as User
  if (!user || typeof user.id !== 'string') throw new Error('登录响应缺少用户信息')
  return user
}

function nearExpiry(expiresAtMs: number | null, ttlSeconds: number | null): boolean {
  if (!expiresAtMs || !ttlSeconds) return true
  return expiresAtMs - Date.now() <= Math.min(60_000, ttlSeconds * 100)
}

function isCode(error: unknown, code: string): boolean {
  return axios.isAxiosError(error) && error.response?.data?.error?.code === code
}

function pendingLogout(): boolean {
  try {
    return localStorage.getItem(PENDING_LOGOUT_KEY) === '1'
  } catch {
    return false
  }
}

function setPendingLogout(pending: boolean): void {
  try {
    if (pending) localStorage.setItem(PENDING_LOGOUT_KEY, '1')
    else localStorage.removeItem(PENDING_LOGOUT_KEY)
  } catch {
    // Browsers can disable local storage. The current page still blocks restoration.
  }
}
