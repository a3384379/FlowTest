import { useQuery } from '@tanstack/react-query'
import type { SelfTestBatch } from './self-test-contract'
import { getSelfTestInsights } from './self-test-service'
import { selfTestScope, useSelfTestIdentity } from './self-test-query-keys'
export function useSelfTestInsights(projectId: string, batch: SelfTestBatch) {
  const identity = useSelfTestIdentity(projectId)
  return useQuery({
    queryKey: [...selfTestScope(identity), 'insights', batch.id, batch.revision],
    queryFn: async ({ signal }) => {
      const result = await getSelfTestInsights(projectId, batch.id, signal)
      if (
        result.manifest_digest !== batch.manifest_digest ||
        result.scope !== batch.verification_scope
      )
        throw new Error('统计来源或范围与冻结清单不符，请刷新批次。')
      return result
    },
    enabled: Boolean(identity.userId),
    refetchInterval: (query) =>
      !query.state.error &&
      query.state.dataUpdateCount < 300 &&
      !batch.sealed_at &&
      !['completed', 'cancelled', 'expired'].includes(batch.phase)
        ? 2000
        : false,
  })
}
