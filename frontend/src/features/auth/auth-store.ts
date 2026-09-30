import { create } from 'zustand'

import { AuthSessionCoordinator, type SessionSnapshot } from './auth-session'

type LoginPayload = { email: string; password: string }

type AuthState = SessionSnapshot & {
  initialize: () => Promise<void>
  login: (payload: LoginPayload) => Promise<void>
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>
  logout: () => Promise<void>
  prepareOIDCLogin: () => Promise<void>
  registerRecoveryListeners: () => () => void
  requestAccessToken: () => Promise<string>
  recoverExpiredAccessToken: (usedVersion: number | undefined) => Promise<string>
  rejectInvalidAccessToken: (usedVersion: number | undefined) => void
}

export const useAuthStore = create<AuthState>((set, get) => {
  const coordinator = new AuthSessionCoordinator({
    read: get,
    write: (patch) => set(patch),
  })
  return {
    phase: 'initializing',
    initialized: false,
    initializing: false,
    token: null,
    user: null,
    lastUserId: null,
    expiresAtMs: null,
    issuedTtlSeconds: null,
    epoch: 0,
    tokenVersion: 0,
    organizationId: null,
    sessionStartedAtMs: null,
    sessionId: null,
    notice: null,
    initialize: () => coordinator.initialize(),
    login: (payload) => coordinator.login(payload),
    changePassword: (currentPassword, newPassword) =>
      coordinator.changePassword(currentPassword, newPassword),
    logout: () => coordinator.logout(),
    prepareOIDCLogin: () => coordinator.prepareOIDCLogin(),
    registerRecoveryListeners: () => coordinator.registerRecoveryListeners(),
    requestAccessToken: () => coordinator.ensureFreshAccessToken(),
    recoverExpiredAccessToken: (usedVersion) => coordinator.recoverExpiredAccessToken(usedVersion),
    rejectInvalidAccessToken: (usedVersion) => coordinator.rejectInvalidAccessToken(usedVersion),
  }
})
