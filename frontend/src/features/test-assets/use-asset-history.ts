import { useQueries, useQuery } from '@tanstack/react-query'
import { getAssetRun, listRecentAssetRuns, type AssetKind } from './asset-workspace-service'
import { assetRunHistory } from './asset-run-view-model'

export function useAssetHistory(projectId: string | null) {
  const runs = useQuery({
    queryKey: ['asset-recent-runs', projectId],
    queryFn: () => listRecentAssetRuns(projectId!),
    enabled: Boolean(projectId),
    refetchInterval: (query) => (hasActiveRun(query.state.data?.items) ? 1000 : false),
  })
  const details = useQueries({
    queries: (runs.data?.items ?? []).map((run) => ({
      queryKey: ['test-plan-run-detail', projectId, run.id],
      queryFn: () => getAssetRun(projectId!, run.id),
      staleTime: 10_000,
      refetchInterval: (query: { state: { data?: Awaited<ReturnType<typeof getAssetRun>> } }) =>
        hasActiveRun(query.state.data ? [query.state.data.run] : []) ? 1000 : false,
    })),
  })
  const records = details.flatMap((query) => (query.data ? [query.data] : []))
  return {
    total: runs.data?.total,
    count: records.length,
    loading: runs.isPending || details.some((query) => query.isPending),
    error: runs.error ?? details.find((query) => query.error)?.error,
    history: (kind: AssetKind, id: string) => assetRunHistory(records, kind, id),
    reload: () => Promise.all([runs.refetch(), ...details.map((query) => query.refetch())]),
  }
}

function hasActiveRun(items: Array<{ status: string }> = []): boolean {
  return items.some((item) => ['queued', 'running'].includes(item.status))
}
