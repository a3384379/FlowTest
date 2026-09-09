export const WORKFLOW_TAB_SCHEMA_VERSION = 1

export type WorkflowTabKey = {
  serverInstance: string
  userId: string
  projectId: string
}

export type WorkflowTabRecord = {
  schemaVersion: typeof WORKFLOW_TAB_SCHEMA_VERSION
  resourceKey: WorkflowTabKey
  workflowIds: string[]
  activeWorkflowId: string | null
}

export type WorkflowTabStorageResult = { ok: true } | { ok: false; error: string }

const STORAGE_PREFIX = 'flowtest:workflow-tabs:v1:'

export function workflowTabKey(
  userId: string,
  projectId: string,
  serverInstance = currentServerInstance(),
): WorkflowTabKey {
  return { serverInstance, userId, projectId }
}

export function readWorkflowTabs(key: WorkflowTabKey): WorkflowTabRecord | null {
  const storage = sessionStorageOrNull()
  if (!storage) return null
  try {
    const raw = storage.getItem(storageKey(key))
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (!isTabRecord(parsed, key)) {
      storage.removeItem(storageKey(key))
      return null
    }
    return parsed
  } catch {
    return null
  }
}

export function writeWorkflowTabs(
  key: WorkflowTabKey,
  workflowIds: string[],
  activeWorkflowId: string | null,
): WorkflowTabStorageResult {
  const storage = sessionStorageOrNull()
  if (!storage) return { ok: false, error: '当前浏览器不支持工作区页签保存' }
  const normalized = [...new Set(workflowIds.filter((id) => typeof id === 'string' && id))]
  const record: WorkflowTabRecord = {
    schemaVersion: WORKFLOW_TAB_SCHEMA_VERSION,
    resourceKey: key,
    workflowIds: normalized,
    activeWorkflowId:
      activeWorkflowId && normalized.includes(activeWorkflowId) ? activeWorkflowId : null,
  }
  try {
    storage.setItem(storageKey(key), JSON.stringify(record))
    return { ok: true }
  } catch {
    return { ok: false, error: '工作区页签保存失败，当前页签仍保留在内存中' }
  }
}

export function removeWorkflowTabs(key: WorkflowTabKey): WorkflowTabStorageResult {
  const storage = sessionStorageOrNull()
  if (!storage) return { ok: false, error: '当前浏览器不支持工作区页签保存' }
  try {
    storage.removeItem(storageKey(key))
    return { ok: true }
  } catch {
    return { ok: false, error: '工作区页签清理失败' }
  }
}

function storageKey(key: WorkflowTabKey): string {
  return `${STORAGE_PREFIX}${[key.serverInstance, key.userId, key.projectId]
    .map(encodePart)
    .join(':')}`
}

function encodePart(value: string): string {
  return encodeURIComponent(value)
}

function currentServerInstance(): string {
  return typeof window === 'undefined' ? 'default' : window.location.origin || 'default'
}

function sessionStorageOrNull(): Storage | null {
  if (typeof window === 'undefined') return null
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

function isTabRecord(value: unknown, key: WorkflowTabKey): value is WorkflowTabRecord {
  if (!isRecord(value)) return false
  return (
    value.schemaVersion === WORKFLOW_TAB_SCHEMA_VERSION &&
    isRecord(value.resourceKey) &&
    JSON.stringify(value.resourceKey) === JSON.stringify(key) &&
    Array.isArray(value.workflowIds) &&
    value.workflowIds.every((id) => typeof id === 'string' && id.length > 0) &&
    (value.activeWorkflowId === null || typeof value.activeWorkflowId === 'string')
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
