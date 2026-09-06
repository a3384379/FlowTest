import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { useProjectContext } from '../projects/use-project-context'
import { getContext } from './context-inspector-service'
import { useContextPage } from './use-context-page'

export function useContextInspector() {
  const { projectId } = useProjectContext()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const { contexts, page, setPage } = useContextPage(projectId)
  const items = contexts.data?.items ?? []
  const activeId = items.some((item) => item.id === selectedId)
    ? selectedId
    : (items.at(0)?.id ?? null)
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
