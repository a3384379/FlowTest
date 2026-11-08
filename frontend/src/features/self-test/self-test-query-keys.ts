import { useMemo } from 'react'
import { useAuthStore } from '../auth/auth-store'

export type SelfTestIdentity = {
  userId: string | null
  organizationId: string | null
  projectId: string | null
  epoch: number
}
export function selfTestScope(identity: SelfTestIdentity) {
  return [
    'self-test',
    identity.userId,
    identity.organizationId,
    identity.epoch,
    identity.projectId,
  ] as const
}
export function selfTestIdentityIsCurrent(identity: SelfTestIdentity): boolean {
  const current = useAuthStore.getState()
  return (
    current.user?.id === identity.userId &&
    current.organizationId === identity.organizationId &&
    current.epoch === identity.epoch &&
    current.phase !== 'logging-out'
  )
}
export function useSelfTestIdentity(projectId: string | null): SelfTestIdentity {
  const userId = useAuthStore((state) => state.user?.id ?? null)
  const organizationId = useAuthStore((state) => state.organizationId)
  const epoch = useAuthStore((state) => state.epoch)
  return useMemo(
    () => ({ userId, organizationId, epoch, projectId }),
    [userId, organizationId, epoch, projectId],
  )
}
export const selfTestKeys = {
  templates: (scope: SelfTestIdentity) => [...selfTestScope(scope), 'templates'] as const,
  bindings: (scope: SelfTestIdentity) => [...selfTestScope(scope), 'bindings'] as const,
  installation: (scope: SelfTestIdentity, id: string | null) =>
    [...selfTestScope(scope), 'installation', id] as const,
  runs: (scope: SelfTestIdentity, id: string | null, cursor: string | null) =>
    [...selfTestScope(scope), 'runs', id, cursor] as const,
  batch: (scope: SelfTestIdentity, id: string | null) =>
    [...selfTestScope(scope), 'batch', id] as const,
  generation: (scope: SelfTestIdentity, id: string | null) =>
    [...selfTestScope(scope), 'generation', id] as const,
  scenarios: (
    scope: SelfTestIdentity,
    id: string | null,
    filters: { page: number; category: string; verification: string; scenarioId: string | null },
  ) => [...selfTestScope(scope), 'scenarios', id, filters] as const,
  relation: (
    scope: SelfTestIdentity,
    batch: string,
    scenario: string | undefined,
    execution: string,
  ) => [...selfTestScope(scope), 'relation', batch, scenario, execution] as const,
}
