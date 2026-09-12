import { createContext, useContext, useState } from 'react'
import type { WorkbenchFields } from '../api-console/APIWorkbench'
import type { WorkflowDraftEdit } from '../workflows/use-workflows'

type ApiDraft = {
  fields: WorkbenchFields
  generation: number
  storageError: boolean
  baseVersion: number
}
export class DraftSession {
  readonly apis = new Map<string, ApiDraft>()
  readonly workflows = new Map<
    string,
    {
      drafts: Map<string, WorkflowDraftEdit>
      generations: Map<string, number>
      storageErrors: Map<string, string>
    }
  >()
  readonly unsafe = new Set<string>()
  private revision = 0
  private generation = 0
  private readonly listeners = new Set<() => void>()
  nextGeneration() {
    return ++this.generation
  }
  workflowScope(key: string) {
    let scope = this.workflows.get(key)
    if (!scope) {
      scope = { drafts: new Map(), generations: new Map(), storageErrors: new Map() }
      this.workflows.set(key, scope)
    }
    return scope
  }
  markUnsafe(key: string, unsafe: boolean) {
    if (this.unsafe.has(key) === unsafe) return
    if (unsafe) this.unsafe.add(key)
    else this.unsafe.delete(key)
    this.revision += 1
    this.listeners.forEach((listener) => listener())
  }
  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }
  snapshot = () => this.revision
}
export const DraftContext = createContext<DraftSession | null>(null)
export function useDraftSession() {
  const provided = useContext(DraftContext)
  const [local] = useState(() => new DraftSession())
  return provided ?? local
}
