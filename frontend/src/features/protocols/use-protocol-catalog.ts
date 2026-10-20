import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import type { Page } from '../../lib/api'

export function useProtocolCatalog<T>(
  resource: string,
  projectId: string,
  scope: string,
  page: number,
  setPage: (page: number) => void,
  load: (page: number) => Promise<Page<T>>,
  enabled: boolean,
) {
  const query = useQuery({
    queryKey: [resource, projectId, scope, 'catalog', page],
    queryFn: () => load(page),
    enabled,
  })
  return { ...query, page, setPage }
}

type Asset = { id: string; project_id: string }
export function useSelectedProtocolAsset<T extends Asset>(
  projectId: string,
  resource: string,
  id: string | null,
  items: T[],
  read: (id: string) => Promise<T>,
  select: (id: string, replace?: boolean) => void,
  enabled: boolean,
  autoSelect = true,
) {
  const first = items.at(0)
  const resolvedId = enabled ? resolveSelectedId(id, autoSelect, first) : null
  const pageItem = items.find((item) => item.id === resolvedId && item.project_id === projectId)
  const query = useQuery({
    queryKey: [resource, projectId, 'by-id', resolvedId],
    queryFn: () => read(required(resolvedId)),
    initialData: pageItem,
    enabled: enabled && Boolean(resolvedId) && !pageItem,
    staleTime: Infinity,
    retry: false,
  })
  useEffect(() => {
    if (autoSelect && enabled && id === null && first?.project_id === projectId)
      select(first.id, true)
  }, [autoSelect, enabled, first, id, projectId, select])
  return { query, selected: query.isError ? null : (pageItem ?? query.data ?? null) }
}
function required(value: string | null): string {
  if (!value) throw new Error('未选择协议资产版本')
  return value
}

function resolveSelectedId(id: string | null, autoSelect: boolean, first: Asset | undefined) {
  if (id !== null) return id
  return autoSelect ? (first?.id ?? null) : null
}
