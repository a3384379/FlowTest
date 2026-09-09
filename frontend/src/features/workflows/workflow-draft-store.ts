import type { WorkflowDefinition } from '../../lib/api'

export const WORKFLOW_DRAFT_SCHEMA_VERSION = 1

export type WorkflowDraftKey = {
  serverInstance: string
  userId: string
  projectId: string
  workflowId: string
}

export type WorkflowDraftRecord = {
  schemaVersion: typeof WORKFLOW_DRAFT_SCHEMA_VERSION
  resourceKey: WorkflowDraftKey
  baseRevision: number
  editVersion: number
  updatedAt: string
  content: WorkflowDefinition
}

export type DraftStorageResult = { ok: true } | { ok: false; error: string }

const STORAGE_PREFIX = 'flowtest:workflow-draft:v1:'
export const WORKFLOW_DRAFT_EVENT = 'flowtest:workflow-draft'

export function workflowDraftKey(
  userId: string,
  projectId: string,
  workflowId: string,
  serverInstance = currentServerInstance(),
): WorkflowDraftKey {
  return { serverInstance, userId, projectId, workflowId }
}

export function readWorkflowDraft(key: WorkflowDraftKey): WorkflowDraftRecord | null {
  const storage = browserStorage()
  if (!storage) return null
  try {
    const raw = storage.getItem(storageKey(key))
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (!isDraftRecord(parsed, key)) {
      storage.removeItem(storageKey(key))
      return null
    }
    return parsed
  } catch {
    return null
  }
}

export function writeWorkflowDraft(
  key: WorkflowDraftKey,
  content: WorkflowDefinition,
  baseRevision: number,
  editVersion: number,
): DraftStorageResult {
  const storage = browserStorage()
  if (!storage) return { ok: false, error: '当前浏览器不支持本地草稿保存' }
  const record: WorkflowDraftRecord = {
    schemaVersion: WORKFLOW_DRAFT_SCHEMA_VERSION,
    resourceKey: key,
    baseRevision,
    editVersion,
    updatedAt: new Date().toISOString(),
    content,
  }
  try {
    storage.setItem(storageKey(key), JSON.stringify(record))
    notifyDraftChange()
    return { ok: true }
  } catch {
    return { ok: false, error: '本地保存失败，已保留当前内存编辑内容' }
  }
}

export function removeWorkflowDraft(key: WorkflowDraftKey): DraftStorageResult {
  const storage = browserStorage()
  if (!storage) return { ok: false, error: '当前浏览器不支持本地草稿保存' }
  try {
    storage.removeItem(storageKey(key))
    notifyDraftChange()
    return { ok: true }
  } catch {
    return { ok: false, error: '本地草稿清理失败' }
  }
}

export function clearWorkflowDrafts(userId: string): DraftStorageResult {
  const storage = browserStorage()
  if (!storage) return { ok: false, error: '当前浏览器不支持本地草稿保存' }
  try {
    const keys: string[] = []
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index)
      if (key?.startsWith(STORAGE_PREFIX) && key.includes(`:${encodePart(userId)}:`)) {
        keys.push(key)
      }
    }
    keys.forEach((key) => storage.removeItem(key))
    notifyDraftChange()
    return { ok: true }
  } catch {
    return { ok: false, error: '本地草稿清理失败' }
  }
}

function storageKey(key: WorkflowDraftKey): string {
  return `${STORAGE_PREFIX}${[key.serverInstance, key.userId, key.projectId, key.workflowId]
    .map(encodePart)
    .join(':')}`
}

function encodePart(value: string): string {
  return encodeURIComponent(value)
}

function currentServerInstance(): string {
  return typeof window === 'undefined' ? 'default' : window.location.origin || 'default'
}

function browserStorage(): Storage | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage
  } catch {
    return null
  }
}

function notifyDraftChange(): void {
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(WORKFLOW_DRAFT_EVENT))
}

function isDraftRecord(value: unknown, key: WorkflowDraftKey): value is WorkflowDraftRecord {
  if (!isRecord(value)) return false
  return (
    hasCurrentSchema(value) &&
    hasResourceKey(value, key) &&
    hasRevisionMetadata(value) &&
    typeof value.updatedAt === 'string' &&
    isWorkflowDefinition(value.content)
  )
}

function hasCurrentSchema(value: Record<string, unknown>): boolean {
  return value.schemaVersion === WORKFLOW_DRAFT_SCHEMA_VERSION
}

function hasResourceKey(value: Record<string, unknown>, key: WorkflowDraftKey): boolean {
  return isRecord(value.resourceKey) && JSON.stringify(value.resourceKey) === JSON.stringify(key)
}

function hasRevisionMetadata(value: Record<string, unknown>): boolean {
  return isPositiveInteger(value.baseRevision) && isPositiveInteger(value.editVersion)
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1
}

function isWorkflowDefinition(value: unknown): boolean {
  return isRecord(value) && Array.isArray(value.nodes) && Array.isArray(value.edges)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
