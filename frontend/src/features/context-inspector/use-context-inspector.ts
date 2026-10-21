import { useQuery } from '@tanstack/react-query'
import { useContext, useEffect } from 'react'
import { UNSAFE_DataRouterContext, useLocation, useSearchParams } from 'react-router-dom'
import { useProjectContext } from '../projects/use-project-context'
import { getContext } from './context-inspector-service'
import { useContextPage } from './use-context-page'
import {
  clearContextSelection,
  contextPageNumber,
  readContextSelection,
  writeContextNavigation,
  type ContextNavigation,
} from './context-navigation'

export function useContextInspector(initialContextId?: string) {
  const { projectId } = useProjectContext(),
    location = useLocation(),
    router = useContext(UNSAFE_DataRouterContext)
  const [params, setParams] = useSearchParams()
  const page = contextPageNumber(params.get('contextPage'))
  const { contexts } = useContextPage(projectId, true, page)
  const activeId = activeContextId(params, initialContextId, contexts.data?.items)
  const detail = useQuery({
    queryKey: ['context-inspector-detail', projectId, activeId],
    queryFn: () => getContext(required(projectId), required(activeId)),
    enabled: Boolean(projectId && activeId),
  })
  const expectedRevision = params.get('revision')
  const revisionMismatch = Boolean(
    detail.isSuccess && expectedRevision && detail.data.revision_id !== expectedRevision,
  )
  const selection = readContextSelection(params)
  const catalogCurrent = !contexts.isPlaceholderData && contexts.data?.page === page
  useEffect(() => {
    if (!detail.isSuccess || expectedRevision || !activeId) return
    if (!params.has('focus') && !catalogCurrent) return
    if (router && router.router.state.location.key !== location.key) return
    const next = new URLSearchParams(params)
    next.set('focus', activeId)
    next.set('revision', detail.data.revision_id)
    setParams(next, { replace: true })
  }, [
    detail.isSuccess,
    detail.data,
    expectedRevision,
    activeId,
    catalogCurrent,
    router,
    location.key,
    params,
    setParams,
  ])
  function select(id: string) {
    const next = clearContextSelection(params)
    next.set('focus', id)
    const summary = contexts.data?.items.find((item) => item.id === id)
    if (summary) next.set('revision', summary.revision_id)
    setParams(next)
  }
  function navigate(patch: ContextNavigation) {
    if (!detail.isSuccess || revisionMismatch) return
    const next = writeContextNavigation(params, patch)
    next.set('focus', detail.data.id)
    next.set('revision', detail.data.revision_id)
    setParams(next)
  }
  function showCurrentRevision() {
    if (!detail.isSuccess) return
    const next = clearContextSelection(params)
    next.set('focus', detail.data.id)
    next.set('revision', detail.data.revision_id)
    setParams(next)
  }
  function setPage(value: number) {
    const next = new URLSearchParams(params)
    next.set('contextPage', String(value))
    setParams(next)
  }
  return {
    projectId,
    contexts,
    detail,
    activeId,
    select,
    page,
    setPage,
    selection,
    navigate,
    expectedRevision,
    revisionMismatch,
    showCurrentRevision,
  }
}
function required(value: string | null): string {
  if (!value) throw new Error('请选择项目')
  return value
}

function activeContextId(
  params: URLSearchParams,
  initialId: string | undefined,
  items?: { id: string }[],
): string | null {
  return params.get('focus') ?? initialId ?? items?.[0]?.id ?? null
}
