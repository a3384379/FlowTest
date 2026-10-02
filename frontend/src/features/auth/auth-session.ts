import axios from 'axios'

import { authClient, SessionBoundaryError } from '../../lib/auth-client'
import type { User } from '../../lib/api'
import {
  AuthSessionLifecycle,
  matchesIntent,
  parseSessionEvent,
  parseLogoutIntent,
  PENDING_LOGOUT_KEY,
  SESSION_KEY,
  type ClientSession,
  type LogoutIntent,
  type SessionEvent,
} from './auth-session-lifecycle'

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
  sessionId: string | null
  notice: string | null
}

type SessionPort = {
  read: () => SessionSnapshot
  write: (patch: Partial<SessionSnapshot>) => void
}

type TokenCandidate = { token: string; expiresAtMs: number; ttlSeconds: number; epoch: number }
export class AuthSessionCoordinator {
  private refreshTask: { epoch: number; promise: Promise<string> } | null = null
  private initializeTask: { epoch: number; promise: Promise<void> } | null = null
  private candidate: TokenCandidate | null = null
  private readonly lifecycle = new AuthSessionLifecycle()
  private readonly channel: BroadcastChannel | null
  private lastRecoveryCheck = 0

  constructor(private readonly port: SessionPort) {
    this.channel =
      typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel('flowtest-auth-session')
    if (this.channel) {
      this.channel.onmessage = (event: MessageEvent<unknown>) => {
        const message = parseSessionEvent(event.data)
        if (message && matchesIntent(message.intent, this.snapshot().sessionId)) {
          this.invalidate('登录状态已变化，请重新登录。')
        }
      }
    }
  }

  snapshot(): SessionSnapshot {
    return this.port.read()
  }

  initialize(): Promise<void> {
    const snapshot = this.snapshot()
    if (snapshot.initialized && snapshot.phase !== 'temporarily-unavailable') {
      return Promise.resolve()
    }
    if (this.initializeTask?.epoch === snapshot.epoch) return this.initializeTask.promise
    const task = { epoch: snapshot.epoch, promise: this.restore(snapshot.epoch) }
    this.initializeTask = task
    void task.promise.finally(() => {
      if (this.initializeTask === task) this.initializeTask = null
    })
    return task.promise
  }

  private async restore(epoch: number): Promise<void> {
    this.port.write({ initializing: true })
    try {
      const snapshot = this.adoptSession()
      const intent = this.lifecycle.pendingLogout()
      if (matchesIntent(intent, snapshot.sessionId)) {
        await this.restoreLogout(intent!, epoch)
      } else {
        // Refresh owns its error classification; initialization only owns its marker.
        await this.refresh().catch(() => undefined)
      }
    } catch (error) {
      if (this.snapshot().epoch === epoch && !(error instanceof SessionBoundaryError)) {
        this.temporaryFailure()
      }
    } finally {
      if (this.snapshot().epoch === epoch) {
        this.port.write({ initialized: true, initializing: false })
      }
    }
  }

  private async restoreLogout(intent: LogoutIntent, epoch: number): Promise<void> {
    try {
      await this.withBrowserLock(async () => {
        this.assertEpoch(epoch)
        await this.resolvePendingLogout(epoch)
      })
      if (this.snapshot().epoch === epoch) this.invalidate(null)
    } catch (error) {
      if (this.snapshot().epoch !== epoch || error instanceof SessionBoundaryError) return
      if (this.lifecycle.pendingLogout()?.id === intent.id) {
        this.invalidate('本地已退出，但尚未确认服务端会话已注销。')
      }
    }
  }

  async login(payload: { email: string; password: string }): Promise<void> {
    const epoch = this.beginLogin()
    await this.withBrowserLock(async () => {
      const session = await this.prepareLogin(epoch)
      const response = await authClient.post<unknown>('/auth/login', payload)
      this.assertActive(epoch)
      this.publish(tokenCandidate(response.data, epoch), userFromLogin(response.data), session)
    })
  }

  async prepareOIDCLogin(): Promise<void> {
    const epoch = this.beginLogin()
    await this.withBrowserLock(async () => {
      const session = await this.prepareLogin(epoch)
      this.lifecycle.rememberOIDCAttempt(session.id)
    })
  }

  private beginLogin(): number {
    this.invalidate(null)
    return this.snapshot().epoch
  }

  private async prepareLogin(epoch: number): Promise<ClientSession> {
    this.assertEpoch(epoch)
    await this.resolvePendingLogout(epoch)
    this.assertEpoch(epoch)
    const session = this.lifecycle.startSession()
    this.port.write({ sessionId: session.id })
    return session
  }

  private async resolvePendingLogout(epoch: number): Promise<void> {
    const intent = this.lifecycle.pendingLogout()
    const session = this.lifecycle.session()
    if (!matchesIntent(intent, session?.id ?? null)) return
    this.assertEpoch(epoch)
    await authClient.post('/auth/logout')
    this.assertEpoch(epoch)
    this.lifecycle.completeLogout(intent!)
  }

  async ensureFreshAccessToken(): Promise<string> {
    if (!this.snapshot().user) throw new SessionBoundaryError('已退出登录')
    const snapshot = this.adoptSession()
    this.assertActive(snapshot.epoch)
    if (snapshot.token && !nearExpiry(snapshot.expiresAtMs, snapshot.issuedTtlSeconds)) {
      return snapshot.token
    }
    try {
      return await this.refresh()
    } catch (error) {
      if (this.snapshot().epoch !== snapshot.epoch) throw error
      this.assertActive(snapshot.epoch)
      if (
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
    const snapshot = this.adoptSession()
    this.assertActive(snapshot.epoch)
    if (!snapshot.user) throw new SessionBoundaryError('登录身份已变化')
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
    await this.withBrowserLock(async () => {
      this.assertActive(snapshot.epoch)
      await authClient.post(
        '/auth/change-password',
        { current_password: currentPassword, new_password: newPassword },
        { headers: { Authorization: `Bearer ${token}` } },
      )
    })
    if (this.snapshot().epoch !== snapshot.epoch) return
    const intent = this.lifecycle.beginLogout(snapshot.sessionId)
    this.broadcast({ kind: 'password-changed', intent })
    // Password changes revoke refresh sessions; the remaining cookie is cleaned on recovery.
    this.invalidate('密码已修改，请重新登录。')
  }

  async logout(): Promise<void> {
    const snapshot = this.adoptSession()
    const intent = this.lifecycle.beginLogout(snapshot.sessionId)
    this.broadcast({ kind: 'logout-intent', intent })
    const refresh = this.refreshTask?.promise
    this.invalidate(null)
    const epoch = this.snapshot().epoch
    this.port.write({ phase: 'logging-out' })
    try {
      if (refresh) await refresh.catch(() => undefined)
      await this.withBrowserLock(async () => {
        this.assertEpoch(epoch)
        await this.resolvePendingLogout(epoch)
      })
      if (this.snapshot().epoch === epoch) this.port.write({ phase: 'anonymous' })
    } catch (error) {
      if (this.snapshot().epoch !== epoch || error instanceof SessionBoundaryError) return
      this.port.write({
        phase: 'anonymous',
        notice: '本地已退出，但尚未确认服务端会话已注销。',
      })
    }
  }

  registerRecoveryListeners(): () => void {
    const check = () => {
      try {
        const snapshot = this.snapshot()
        if (!snapshot.user) return
        this.assertActive(snapshot.epoch)
        if (Date.now() - this.lastRecoveryCheck < 1000) return
        this.lastRecoveryCheck = Date.now()
        if (nearExpiry(snapshot.expiresAtMs, snapshot.issuedTtlSeconds)) {
          void this.ensureFreshAccessToken().catch(() => undefined)
        }
      } catch (error) {
        if (!(error instanceof SessionBoundaryError)) throw error
      }
    }
    const onVisibility = () => {
      if (document.visibilityState === 'visible') check()
    }
    const onStorage = (event: StorageEvent) => {
      if (event.key === PENDING_LOGOUT_KEY && event.newValue) {
        const intent = parseLogoutIntent(event.newValue)
        if (matchesIntent(intent, this.snapshot().sessionId)) {
          this.invalidate('登录状态已变化，请重新登录。')
          return
        }
      }
      if (
        event.key === PENDING_LOGOUT_KEY ||
        event.key === SESSION_KEY ||
        event.key === 'flowtest:logout-pending:v1' ||
        event.key === null
      ) {
        check()
      }
    }
    window.addEventListener('focus', check)
    window.addEventListener('online', check)
    window.addEventListener('storage', onStorage)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.removeEventListener('focus', check)
      window.removeEventListener('online', check)
      window.removeEventListener('storage', onStorage)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }

  private refresh(): Promise<string> {
    const start = this.adoptSession()
    this.assertActive(start.epoch)
    if (this.refreshTask?.epoch === start.epoch) return this.refreshTask.promise
    const task = { epoch: start.epoch, promise: this.performRefresh(start) }
    this.refreshTask = task
    void task.promise
      .finally(() => {
        if (this.refreshTask === task) this.refreshTask = null
      })
      .catch(() => undefined)
    return task.promise
  }

  private async performRefresh(start: SessionSnapshot): Promise<string> {
    this.port.write({ phase: 'refreshing' })
    try {
      const candidate = await this.obtainCandidate(start.epoch)
      this.assertActive(start.epoch)
      const user = await this.confirmCandidate(candidate, start)
      this.assertActive(start.epoch)
      this.publish(candidate, user, { id: start.sessionId!, userId: user.id })
      if (this.candidate === candidate) this.candidate = null
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
      this.assertActive(epoch)
      try {
        return tokenCandidate((await authClient.post<unknown>('/auth/refresh')).data, epoch)
      } catch (error) {
        this.assertActive(epoch)
        if (!isCode(error, 'REFRESH_ROTATION_CONFLICT')) throw error
        await new Promise((resolve) => window.setTimeout(resolve, 250))
        this.assertActive(epoch)
        return tokenCandidate((await authClient.post<unknown>('/auth/refresh')).data, epoch)
      }
    })
    this.assertActive(epoch)
    this.candidate = refreshed
    return refreshed
  }

  private async confirmCandidate(candidate: TokenCandidate, start: SessionSnapshot): Promise<User> {
    const me = await authClient.get<User>('/auth/me', {
      headers: { Authorization: `Bearer ${candidate.token}` },
    })
    this.assertActive(start.epoch)
    if (start.user && start.user.id !== me.data.id) {
      this.invalidate('账号已变化，请重新登录。')
      throw new SessionBoundaryError('账号已变化，请重新登录')
    }
    return me.data
  }

  private handleRefreshFailure(error: unknown, start: SessionSnapshot): void {
    if (this.snapshot().epoch !== start.epoch || error instanceof SessionBoundaryError) return
    if (isCode(error, 'INVALID_REFRESH_TOKEN') || isCode(error, 'INVALID_ACCESS_TOKEN')) {
      this.invalidate(start.user ? '登录状态已失效，请重新登录。' : null)
    } else {
      this.temporaryFailure()
    }
  }

  private adoptSession(): SessionSnapshot {
    const snapshot = this.snapshot()
    if (snapshot.sessionId) return snapshot
    const session = this.lifecycle.ensureSession(snapshot.user?.id ?? null)
    const attempt = this.lifecycle.oidcAttempt()
    if (attempt && attempt !== session.id) throw new SessionBoundaryError('登录身份已变化')
    this.port.write({ sessionId: session.id })
    return this.snapshot()
  }

  private assertEpoch(epoch: number): void {
    if (this.snapshot().epoch !== epoch) throw new SessionBoundaryError('登录身份已变化')
  }

  private assertActive(epoch: number): void {
    this.assertEpoch(epoch)
    const snapshot = this.snapshot()
    const session = this.lifecycle.session()
    if (matchesIntent(this.lifecycle.pendingLogout(), snapshot.sessionId)) {
      this.invalidate('本地已退出，但尚未确认服务端会话已注销。')
      throw new SessionBoundaryError('已退出登录')
    }
    if (snapshot.phase === 'logging-out' || (session && session.id !== snapshot.sessionId)) {
      this.invalidate('登录状态已变化，请重新登录。')
      throw new SessionBoundaryError('登录身份已变化')
    }
  }

  private publish(candidate: TokenCandidate, user: User, session: ClientSession): void {
    this.assertActive(candidate.epoch)
    const previous = this.snapshot()
    this.lifecycle.confirmUser(session, user.id)
    this.port.write({
      phase: 'authenticated',
      token: candidate.token,
      user,
      lastUserId: user.id,
      expiresAtMs: candidate.expiresAtMs,
      issuedTtlSeconds: candidate.ttlSeconds,
      tokenVersion: previous.tokenVersion + 1,
      sessionStartedAtMs: previous.sessionStartedAtMs ?? Date.now(),
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
      sessionId: null,
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

  private broadcast(event: SessionEvent): void {
    this.channel?.postMessage(event)
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
