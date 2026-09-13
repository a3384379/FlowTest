import { createContext, useContext, useRef, useState } from 'react'
export type BulkDraft = { text: string | null; errors: string[] }
export const BulkDraftContext = createContext<{
  drafts: Readonly<Record<string, BulkDraft>>
  onChange: (key: string, value: BulkDraft) => void
} | null>(null)
export function useBulkDraft(key: string) {
  const persistence = useContext(BulkDraftContext)
  const [draft, setDraft] = useState<BulkDraft>(
    () => persistence?.drafts[key] ?? { text: null, errors: [] },
  )
  const latest = useRef(draft)
  function update(patch: Partial<BulkDraft>) {
    const next = { ...latest.current, ...patch }
    latest.current = next
    setDraft(next)
    persistence?.onChange(key, next)
  }
  return {
    bulkText: draft.text,
    bulkErrors: draft.errors,
    setBulkText: (text: string | null) => update({ text }),
    setBulkErrors: (errors: string[]) => update({ errors }),
  }
}
