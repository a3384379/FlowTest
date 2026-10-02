export type ClientSession = { id: string; userId: string | null }
export type LogoutIntent = { id: string; sessionId: string | null }
export type SessionEvent = {
  kind: 'logout-intent' | 'password-changed'
  intent: LogoutIntent
}

export const SESSION_KEY = 'flowtest:auth-session:v1'
export const PENDING_LOGOUT_KEY = 'flowtest:logout-pending:v2'
const LEGACY_LOGOUT_KEY = 'flowtest:logout-pending:v1'
const OIDC_ATTEMPT_KEY = 'flowtest:oidc-attempt:v1'

// Only non-sensitive browser generations and operation IDs are persisted here.
export class AuthSessionLifecycle {
  private memorySession: ClientSession | null = null
  private memoryIntent: LogoutIntent | null = null
  private sessionWriteFailed = false
  private intentWriteFailed = false

  session(): ClientSession | null {
    if (this.sessionWriteFailed) return this.memorySession
    const raw = readStorage(SESSION_KEY)
    return raw === undefined ? this.memorySession : parseSession(raw)
  }

  ensureSession(userId: string | null): ClientSession {
    const current = this.session()
    if (current) return current
    const pending = this.pendingLogout()
    if (pending?.sessionId) {
      const session = { id: pending.sessionId, userId }
      this.saveSession(session)
      return session
    }
    return this.startSession(userId)
  }

  startSession(userId: string | null = null): ClientSession {
    const session = {
      id: Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) =>
        byte.toString(16).padStart(2, '0'),
      ).join(''),
      userId,
    }
    this.saveSession(session)
    return session
  }

  confirmUser(session: ClientSession, userId: string): void {
    this.saveSession({ ...session, userId })
    if (readStorage(OIDC_ATTEMPT_KEY, true) === session.id) {
      writeStorage(OIDC_ATTEMPT_KEY, null, true)
    }
  }

  rememberOIDCAttempt(sessionId: string): void {
    writeStorage(OIDC_ATTEMPT_KEY, sessionId, true)
  }

  oidcAttempt(): string | null {
    return readStorage(OIDC_ATTEMPT_KEY, true) ?? null
  }

  pendingLogout(): LogoutIntent | null {
    if (this.intentWriteFailed && this.memoryIntent) return this.memoryIntent
    const raw = readStorage(PENDING_LOGOUT_KEY)
    if (raw === undefined) return this.memoryIntent
    if (raw !== null) return parseLogoutIntent(raw) ?? { id: 'unrecognized', sessionId: null }
    return readStorage(LEGACY_LOGOUT_KEY) === '1' ? { id: 'legacy', sessionId: null } : null
  }

  beginLogout(sessionId: string | null): LogoutIntent {
    const intent = {
      id: Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) =>
        byte.toString(16).padStart(2, '0'),
      ).join(''),
      sessionId,
    }
    this.memoryIntent = intent
    this.intentWriteFailed = !writeStorage(PENDING_LOGOUT_KEY, JSON.stringify(intent))
    return intent
  }

  completeLogout(intent: LogoutIntent): void {
    if (this.pendingLogout()?.id !== intent.id) return
    this.memoryIntent = null
    const removed = writeStorage(PENDING_LOGOUT_KEY, null)
    const legacyRemoved = writeStorage(LEGACY_LOGOUT_KEY, null)
    this.intentWriteFailed = !removed || !legacyRemoved
  }

  private saveSession(session: ClientSession): void {
    this.memorySession = session
    this.sessionWriteFailed = !writeStorage(SESSION_KEY, JSON.stringify(session))
  }
}

export function matchesIntent(intent: LogoutIntent | null, sessionId: string | null): boolean {
  return intent !== null && (intent.sessionId === null || intent.sessionId === sessionId)
}

export function parseSessionEvent(value: unknown): SessionEvent | null {
  if (!value || typeof value !== 'object') return null
  const event = value as Partial<SessionEvent>
  if (event.kind !== 'logout-intent' && event.kind !== 'password-changed') return null
  return validIntent(event.intent) ? (event as SessionEvent) : null
}

function parseSession(raw: string | null): ClientSession | null {
  const value = parseJSON(raw) as Partial<ClientSession> | null
  if (!value || typeof value.id !== 'string') return null
  if (value.userId !== null && typeof value.userId !== 'string') return null
  return { id: value.id, userId: value.userId }
}

export function parseLogoutIntent(raw: string): LogoutIntent | null {
  const value: unknown = parseJSON(raw)
  return validIntent(value) ? value : null
}

function validIntent(value: unknown): value is LogoutIntent {
  if (!value || typeof value !== 'object') return false
  const intent = value as Partial<LogoutIntent>
  return (
    typeof intent.id === 'string' &&
    (intent.sessionId === null || typeof intent.sessionId === 'string')
  )
}

function parseJSON(raw: string | null): unknown {
  if (raw === null) return null
  try {
    return JSON.parse(raw) as unknown
  } catch {
    // Unrecognized pending data is conservatively treated as an unconfirmed logout.
    return null
  }
}

function readStorage(key: string, perTab = false): string | null | undefined {
  try {
    return (perTab ? sessionStorage : localStorage).getItem(key)
  } catch {
    // A disabled storage backend falls back to this coordinator's in-memory state.
    return undefined
  }
}

function writeStorage(key: string, value: string | null, perTab = false): boolean {
  try {
    const storage = perTab ? sessionStorage : localStorage
    if (value === null) storage.removeItem(key)
    else storage.setItem(key, value)
    return true
  } catch {
    // Callers retain their current-page intent when storage rejects writes.
    return false
  }
}
