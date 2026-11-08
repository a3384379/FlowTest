import { SessionBoundaryError } from '../../lib/auth-client'
import { useAuthStore } from '../auth/auth-store'

/** Capture the caller before Axios schedules asynchronous request preparation. */
export function selfTestCommandConfig(idempotencyKey: string) {
  const snapshot = useAuthStore.getState()
  if (!snapshot.user || snapshot.phase === 'logging-out')
    throw new SessionBoundaryError('登录身份已变化')
  return {
    headers: { 'Idempotency-Key': idempotencyKey },
    authScope: {
      userId: snapshot.user.id,
      organizationId: snapshot.organizationId,
      epoch: snapshot.epoch,
    },
  }
}
