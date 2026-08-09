import { create } from 'zustand'

import { apiClient, setAccessToken, type User } from '../../lib/api'

type LoginPayload = { email: string; password: string }

type AuthState = {
  initialized: boolean
  initializing: boolean
  token: string | null
  user: User | null
  initialize: () => Promise<void>
  login: (payload: LoginPayload) => Promise<void>
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>
  logout: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set, get) => ({
  initialized: false,
  initializing: false,
  token: null,
  user: null,
  initialize: async () => {
    if (get().initialized || get().initializing) return
    set({ initializing: true })
    try {
      const refreshed = await apiClient.post<{ access_token: string }>('/auth/refresh')
      setAccessToken(refreshed.data.access_token)
      const currentUser = await apiClient.get<User>('/auth/me')
      set({ token: refreshed.data.access_token, user: currentUser.data })
    } catch {
      setAccessToken(null)
      set({ token: null, user: null })
    } finally {
      set({ initialized: true, initializing: false })
    }
  },
  login: async (payload) => {
    const response = await apiClient.post<{
      access_token: string
      user: User
    }>('/auth/login', payload)
    setAccessToken(response.data.access_token)
    set({
      token: response.data.access_token,
      user: response.data.user,
      initialized: true,
      initializing: false,
    })
  },
  changePassword: async (currentPassword, newPassword) => {
    await apiClient.post('/auth/change-password', {
      current_password: currentPassword,
      new_password: newPassword,
    })
    const user = get().user
    if (user) set({ user: { ...user, requires_password_change: false } })
  },
  logout: async () => {
    try {
      await apiClient.post('/auth/logout')
    } finally {
      setAccessToken(null)
      set({ token: null, user: null, initialized: true })
    }
  },
}))
