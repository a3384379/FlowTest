import { useRef, useState } from 'react'
import { useDraftSession } from '../drafts/draft-session'
import type { ProtocolRequestDraft } from './protocol-request-draft'

export function useProtocolRequestDraft<T extends ProtocolRequestDraft>(key: string, initial: T) {
  const session = useDraftSession()
  const [draft, setDraft] = useState<T>(() => {
    const saved = session.protocolRequests.get(key)
    return saved?.mode === initial.mode ? (saved as T) : initial
  })
  const current = useRef(draft)
  function patch(values: Partial<T> | ((value: T) => Partial<T>)) {
    const changes = typeof values === 'function' ? values(current.current) : values
    const next = { ...current.current, ...changes }
    current.current = next
    setDraft(next)
    session.protocolRequests.set(key, next)
    session.markUnsafe(`protocol-request:${key}`, true)
  }
  function reset() {
    current.current = initial
    setDraft(initial)
    session.protocolRequests.delete(key)
    session.markUnsafe(`protocol-request:${key}`, false)
  }
  return { draft, patch, reset }
}
