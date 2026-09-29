import { useAuthStore } from '../features/auth/auth-store'
import type { User } from '../lib/api'

export function authenticateTestUser(user: User): void {
  useAuthStore.setState({
    phase: 'authenticated',
    initialized: true,
    token: 'test-token',
    user,
    lastUserId: user.id,
    expiresAtMs: Date.now() + 900_000,
    issuedTtlSeconds: 900,
    notice: null,
  })
}
