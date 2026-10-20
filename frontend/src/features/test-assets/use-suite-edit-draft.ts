import { useState } from 'react'
import { useAuthStore } from '../auth/auth-store'
import { useDraftSession } from '../drafts/draft-session'
import type { SuiteFormValues } from './test-asset-view-model'

export function useSuiteEditDraft(
  projectId: string,
  suiteId: string | undefined,
  defaults: Partial<SuiteFormValues>,
) {
  const userId = useAuthStore((state) => state.user?.id) ?? 'anonymous'
  const session = useDraftSession()
  const key = ['suite-editor', window.location.origin, userId, projectId, suiteId ?? 'new']
    .map(encodeURIComponent)
    .join(':')
  const [initial] = useState(() => structuredClone(session.suiteForms.get(key)?.values ?? defaults))
  const [dirty, setDirty] = useState(() => session.suiteForms.has(key))
  function clear() {
    session.suiteForms.delete(key)
    session.markUnsafe(key, false)
    setDirty(false)
  }
  function remember(values: Partial<SuiteFormValues>) {
    if (signature(values) === signature(defaults)) {
      clear()
      return null
    }
    const generation = session.nextGeneration()
    session.suiteForms.set(key, { values: structuredClone(values), generation })
    session.markUnsafe(key, true)
    setDirty(true)
    return generation
  }
  function completeSave(generation: number | null) {
    if ((session.suiteForms.get(key)?.generation ?? null) === generation) clear()
  }
  return { initial, dirty, remember, clear, completeSave }
}

function signature(values: Partial<SuiteFormValues>): string {
  return JSON.stringify({
    name: values.name ?? '',
    description: values.description ?? '',
    folderId: values.folderId ?? null,
    tags: values.tags ?? [],
    caseIds: values.caseIds ?? [],
    memberVersions: Object.entries(values.memberVersions ?? {})
      .filter(([, version]) => version != null)
      .sort(([left], [right]) => left.localeCompare(right)),
  })
}
