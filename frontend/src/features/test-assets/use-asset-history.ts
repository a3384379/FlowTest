import { useQuery } from '@tanstack/react-query'
import { listLatestSuiteRuns, type AssetKind } from './asset-workspace-service'
import { assetRunHistory } from './asset-run-view-model'

export function useAssetHistory(projectId: string | null, suiteIds: string[]) {
  const runs = useQuery({
    queryKey: ['test-suite-latest-runs', projectId, suiteIds],
    queryFn: () => listLatestSuiteRuns(projectId!, suiteIds),
    enabled: Boolean(projectId),
    refetchInterval: (query) =>
      query.state.data?.some(({ detail }) => hasActiveRun(detail.items)) ? 2000 : false,
  })
  return {
    loading: runs.isPending,
    error: runs.error,
    history: (kind: AssetKind, id: string) =>
      assetRunHistory(
        (runs.data ?? []).filter((entry) => entry.suite_id === id).map((entry) => entry.detail),
        kind,
        id,
      ),
    reload: () => runs.refetch(),
  }
}

function hasActiveRun(items: Array<{ status: string }> = []): boolean {
  return items.some((item) => ['queued', 'running'].includes(item.status))
}
