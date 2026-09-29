import { create } from 'zustand'

import { configureAuthSession } from '../../lib/api'
import { AuthSessionCoordinator, type SessionSnapshot } from './auth-session'

type LoginPayload = { email: string; password: string }

type AuthState = SessionSnapshot & {
  initialize: () => Promise<void>
  login: (payload: LoginPayload) => Promise<void>
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>
  logout: () => Promise<void>
  registerRecoveryListeners: () => () => void
}

export const useAuthStore = create<AuthState>((set, get) => {
  const coordinator = new AuthSessionCoordinator({
    read: get,
    write: (patch) => set(patch),
  })
  configureAuthSession(coordinator)
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
    sessionStartedAtMs: null,
    notice: null,
    initialize: () => coordinator.initialize(),
    login: (payload) => coordinator.login(payload),
    changePassword: (currentPassword, newPassword) =>
      coordinator.changePassword(currentPassword, newPassword),
    logout: () => coordinator.logout(),
    registerRecoveryListeners: () => coordinator.registerRecoveryListeners(),
  }
})
