import { useQuery } from '@tanstack/react-query'

import { useRouteScopedSelection } from '../../lib/use-route-scoped-state'
import { useProjectContext } from '../projects/use-project-context'
import { getContext } from './context-inspector-service'
import { useContextPage } from './use-context-page'

export function useContextInspector(initialContextId?: string) {
  const { projectId } = useProjectContext()
  const [selectedId, setSelectedId] = useRouteScopedSelection(projectId, initialContextId ?? null)
  const { contexts, page, setPage } = useContextPage(projectId)
  const items = contexts.data?.items ?? []
  const activeId = selectedId ?? items.at(0)?.id ?? null
  const detail = useQuery({
    queryKey: ['context-inspector-detail', projectId, activeId],
    queryFn: () => getContext(required(projectId), required(activeId)),
    enabled: Boolean(projectId && activeId),
  })
  return { projectId, contexts, detail, activeId, select: setSelectedId, page, setPage }
}

function required(value: string | null): string {
  if (!value) throw new Error('请选择项目')
  return value
}
