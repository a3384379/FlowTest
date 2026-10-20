import { useState } from 'react'
import { useDraftSession } from '../drafts/draft-session'
import type { ProtocolRequestDraft } from './protocol-request-draft'

export function useProtocolRequestDraft<T extends ProtocolRequestDraft>(key: string, initial: T) {
  const session = useDraftSession()
  const [draft, setDraft] = useState<T>(() => {
    const saved = session.protocolRequests.get(key)
    return saved?.mode === initial.mode ? (saved as T) : initial
  })
  function patch(values: Partial<T>) {
    const next = { ...draft, ...values }
    setDraft(next)
    session.protocolRequests.set(key, next)
    session.markUnsafe(`protocol-request:${key}`, true)
  }
  function reset() {
    setDraft(initial)
    session.protocolRequests.delete(key)
    session.markUnsafe(`protocol-request:${key}`, false)
  }
  return { draft, patch, reset }
}
