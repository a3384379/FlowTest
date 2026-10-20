import { useContext, useEffect } from 'react'
import { DRAFT_DISCARD_PREFIX, DraftContext } from '../drafts/draft-session'

export default function TargetDraftGuard({
  projectId,
  dirty,
}: {
  projectId: string
  dirty: boolean
}) {
  const session = useContext(DraftContext)
  useEffect(() => {
    const key = `${DRAFT_DISCARD_PREFIX}request-target:${projectId}`
    session?.markUnsafe(key, dirty)
    return () => session?.markUnsafe(key, false)
  }, [session, projectId, dirty])
  useEffect(() => {
    if (!dirty || session) return
    const block = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', block)
    return () => window.removeEventListener('beforeunload', block)
  }, [dirty, session])
  return null
}
