import { useContext, useEffect } from 'react'
import { REQUEST_TARGET_DRAFT_PREFIX, DraftContext } from '../drafts/draft-session'

export default function TargetDraftGuard({
  projectId,
  dirty,
}: {
  projectId: string
  dirty: boolean
}) {
  const session = useContext(DraftContext)
  useEffect(() => {
    const key = `${REQUEST_TARGET_DRAFT_PREFIX}${projectId}`
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
