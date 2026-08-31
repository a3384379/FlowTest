import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { useProjectContext } from '../projects/use-project-context'
import { getContext, listContexts } from './context-inspector-service'

export function useContextInspector() {
  const { projectId } = useProjectContext()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const contexts = useQuery({
    queryKey: ['context-inspector', projectId],
    queryFn: () => listContexts(required(projectId)),
    enabled: Boolean(projectId),
  })
  const items = contexts.data?.items ?? []
  const activeId = items.some((item) => item.id === selectedId)
    ? selectedId
    : (items.at(0)?.id ?? null)
  const detail = useQuery({
    queryKey: ['context-inspector-detail', projectId, activeId],
    queryFn: () => getContext(required(projectId), required(activeId)),
    enabled: Boolean(projectId && activeId),
  })
  return { projectId, contexts, detail, activeId, select: setSelectedId }
}

function required(value: string | null): string {
  if (!value) throw new Error('请选择项目')
  return value
}
