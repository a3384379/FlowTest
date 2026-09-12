import { useEffect, useMemo, useRef, useState } from 'react'

import {
  readWorkflowDraft,
  removeWorkflowDraft,
  workflowDraftKey,
  WORKFLOW_DRAFT_EVENT,
  type DraftStorageResult,
} from './workflow-draft-store'
import {
  readWorkflowTabs,
  removeWorkflowTabs,
  workflowTabKey,
  writeWorkflowTabs,
  type WorkflowTabKey,
} from './workflow-tab-store'

export type WorkflowTabCloseRequest = {
  ids: string[]
  dirtyIds: string[]
}

type WorkflowTabHookInput = {
  userId: string | undefined
  projectId: string | null
  workflowIds: string[]
  activeWorkflowId: string | null
  hasExplicitFocus: boolean
  selectWorkflow: (workflowId: string | null) => void
  saveWorkflowDraft: (workflowId: string) => Promise<void>
  discardWorkflowDraft?: (workflowId: string) => DraftStorageResult
  memoryDraftIds?: string[]
  searchParams: URLSearchParams
  setSearchParams: (params: URLSearchParams, options?: { replace?: boolean }) => void
}

export function useWorkflowTabs(input: WorkflowTabHookInput) {
  const storageKey = useMemo(
    () => (input.userId && input.projectId ? workflowTabKey(input.userId, input.projectId) : null),
    [input.projectId, input.userId],
  )
  const storageIdentity = storageKey ? JSON.stringify(storageKey) : null
  const [loadedStorageIdentity, setLoadedStorageIdentity] = useState<string | null>(null)
  const [workflowIds, setWorkflowIds] = useState<string[]>([])
  const [restoredActiveWorkflowId, setRestoredActiveWorkflowId] = useState<string | null>(null)
  const [storageError, setStorageError] = useState<string | null>(null)
  const [pendingClose, setPendingClose] = useState<WorkflowTabCloseRequest | null>(null)
  const [closingTabs, setClosingTabs] = useState(false)
  const [, setDraftRevision] = useState(0)
  const previousStorageKeyRef = useRef<WorkflowTabKey | null>(null)
  const cleanupErrorRef = useRef<string | null>(null)
  const storageReady = Boolean(storageIdentity && loadedStorageIdentity === storageIdentity)

  useEffect(() => {
    const refreshDrafts = () => setDraftRevision((revision) => revision + 1)
    window.addEventListener(WORKFLOW_DRAFT_EVENT, refreshDrafts)
    window.addEventListener('storage', refreshDrafts)
    return () => {
      window.removeEventListener(WORKFLOW_DRAFT_EVENT, refreshDrafts)
      window.removeEventListener('storage', refreshDrafts)
    }
  }, [])

  useEffect(() => {
    const previous = previousStorageKeyRef.current
    if (previous && (!storageKey || previous.userId !== storageKey.userId)) {
      const result = removeWorkflowTabs(previous)
      cleanupErrorRef.current = result.ok ? null : result.error
      if (!result.ok) setStorageError(result.error)
    }
    previousStorageKeyRef.current = storageKey
  }, [storageKey])

  useEffect(() => {
    let active = true
    queueMicrotask(() => {
      if (!active) return
      if (!storageKey || !storageIdentity) {
        setWorkflowIds([])
        setRestoredActiveWorkflowId(null)
        setLoadedStorageIdentity(null)
        setStorageError(cleanupErrorRef.current)
        return
      }
      const stored = readWorkflowTabs(storageKey)
      setWorkflowIds(stored?.workflowIds ?? [])
      setRestoredActiveWorkflowId(stored?.activeWorkflowId ?? null)
      setLoadedStorageIdentity(storageIdentity)
      setStorageError(cleanupErrorRef.current)
    })
    return () => {
      active = false
    }
  }, [storageIdentity, storageKey])

  useEffect(() => {
    if (
      !storageReady ||
      input.hasExplicitFocus ||
      !restoredActiveWorkflowId ||
      input.activeWorkflowId === restoredActiveWorkflowId ||
      !input.workflowIds.includes(restoredActiveWorkflowId)
    ) {
      return
    }
    queueMicrotask(() => input.selectWorkflow(restoredActiveWorkflowId))
  }, [
    input.activeWorkflowId,
    input.hasExplicitFocus,
    input.selectWorkflow,
    input.workflowIds,
    input,
    restoredActiveWorkflowId,
    storageReady,
  ])

  useEffect(() => {
    if (!storageReady) return
    const available = new Set(input.workflowIds)
    const selected = input.activeWorkflowId
    const valid = workflowIds.filter((id) => available.has(id))
    const next = selected && available.has(selected) ? uniqueIds([...valid, selected]) : valid
    if (sameIds(next, workflowIds)) return
    queueMicrotask(() => setWorkflowIds(next))
  }, [input.activeWorkflowId, input.workflowIds, storageReady, workflowIds])

  useEffect(() => {
    if (!storageReady || !storageKey) return
    const result = writeWorkflowTabs(storageKey, workflowIds, input.activeWorkflowId)
    queueMicrotask(() => setStorageError(result.ok ? cleanupErrorRef.current : result.error))
  }, [input.activeWorkflowId, storageKey, storageReady, workflowIds])

  const memoryDraftIds = new Set(input.memoryDraftIds ?? [])
  const dirtyIds = workflowIds.filter((workflowId) =>
    Boolean(
      memoryDraftIds.has(workflowId) ||
      (input.userId &&
        input.projectId &&
        readWorkflowDraft(workflowDraftKey(input.userId, input.projectId, workflowId))),
    ),
  )

  function activateWorkflow(workflowId: string) {
    setWorkflowIds((current) => uniqueIds([...current, workflowId]))
    input.selectWorkflow(workflowId)
    const next = new URLSearchParams(input.searchParams)
    next.set('focus', workflowId)
    input.setSearchParams(next, { replace: true })
  }

  function requestCloseTabs(targetWorkflowIds: string[]) {
    const ids = uniqueIds(targetWorkflowIds).filter((id) => workflowIds.includes(id))
    if (!ids.length) return
    const dirty = ids.filter((id) => dirtyIds.includes(id))
    if (dirty.length) {
      setPendingClose({ ids, dirtyIds: dirty })
      return
    }
    finalizeCloseTabs(ids)
  }

  function finalizeCloseTabs(targetWorkflowIds: string[]) {
    const nextIds = workflowIds.filter((id) => !targetWorkflowIds.includes(id))
    setWorkflowIds(nextIds)
    if (!input.activeWorkflowId || !targetWorkflowIds.includes(input.activeWorkflowId)) return
    const nextActive = nextIds[0] ?? null
    if (nextActive) {
      activateWorkflow(nextActive)
      return
    }
    input.selectWorkflow(null)
    const next = new URLSearchParams(input.searchParams)
    next.delete('focus')
    input.setSearchParams(next, { replace: true })
  }

  async function resolvePendingClose(action: 'save' | 'discard') {
    if (!pendingClose) return
    setClosingTabs(true)
    try {
      if (action === 'save') {
        for (const workflowId of pendingClose.dirtyIds) {
          await input.saveWorkflowDraft(workflowId)
        }
      } else {
        for (const workflowId of pendingClose.dirtyIds) {
          const removed = discardDraft(input, workflowId)
          if (!removed.ok) {
            setStorageError(removed.error)
            return
          }
        }
      }
      const ids = pendingClose.ids
      setPendingClose(null)
      finalizeCloseTabs(ids)
    } catch {
      // The mutation already rendered the API error; keep the confirmation open.
    } finally {
      setClosingTabs(false)
    }
  }

  return {
    workflowIds,
    dirtyIds,
    storageError,
    pendingClose,
    closingTabs,
    activateWorkflow,
    requestCloseTabs,
    resolvePendingClose,
    cancelPendingClose: () => setPendingClose(null),
  }
}

function discardDraft(input: WorkflowTabHookInput, workflowId: string): DraftStorageResult {
  if (input.discardWorkflowDraft) return input.discardWorkflowDraft(workflowId)
  if (!input.userId || !input.projectId) return { ok: true }
  return removeWorkflowDraft(workflowDraftKey(input.userId, input.projectId, workflowId))
}

function uniqueIds(ids: string[]): string[] {
  return [...new Set(ids)]
}

function sameIds(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index])
}
