import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { listContexts } from './context-inspector-service'

export function useContextPage(projectId: string | null, enabled = true) {
  const [selection, setSelection] = useState({ projectId, page: 1 })
  const page = selection.projectId === projectId ? selection.page : 1
  const contexts = useQuery({
    queryKey: ['context-page', projectId, page],
    queryFn: () => {
      if (!projectId) throw new Error('请选择项目')
      return listContexts(projectId, page)
    },
    enabled: Boolean(projectId) && enabled,
    // Preserve an in-progress repair form while paging, never across project boundaries.
    placeholderData: (previous, query) => (query?.queryKey[1] === projectId ? previous : undefined),
  })
  return {
    contexts,
    total: contexts.data?.total ?? 0,
    page,
    setPage: (value: number) => setSelection({ projectId, page: value }),
  }
}
