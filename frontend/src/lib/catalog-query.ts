import { useQuery, type UseQueryOptions } from '@tanstack/react-query'
import type { Page } from './api'
import { useRouteScopedState } from './use-route-scoped-state'

export function useCatalogQuery<T>(
  resource: string,
  projectId: string | null,
  load: (page: number) => Promise<Page<T>>,
  enabled = true,
  scope = '',
  options: Pick<UseQueryOptions<Page<T>>, 'refetchInterval'> = {},
) {
  const [page, setPage] = useRouteScopedState(projectId, `${resource}:${scope}`, 1)
  const query = useQuery({
    queryKey: [resource, projectId, 'catalog', scope, page],
    queryFn: () => load(page),
    enabled: Boolean(projectId && enabled),
    ...options,
  })
  return { ...query, page, setPage }
}
