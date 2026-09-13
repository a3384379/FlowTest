export type WorkflowLayoutPreferences = {
  inspectorWidth: number
  listWidth: number
  requestWidth: number
  listCollapsed: boolean | null
}
export function workflowLayoutKey(userId?: string | null, projectId?: string | null): string {
  return `flowtest:workflow-layout:v1:${[window.location.origin, userId ?? 'anonymous', projectId ?? 'embedded'].map(encodeURIComponent).join(':')}`
}
function defaults(): WorkflowLayoutPreferences {
  return { inspectorWidth: 400, listWidth: 220, requestWidth: 760, listCollapsed: null }
}
export function readLayoutPreferences(key: string): WorkflowLayoutPreferences {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(key) ?? '{}')
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return defaults()
    const value = raw as Record<string, unknown>
    return {
      inspectorWidth: dimension(value.inspectorWidth, 400, 320, 640),
      listWidth: dimension(value.listWidth, 220, 180, 320),
      requestWidth: dimension(value.requestWidth, 760, 480, 4096),
      listCollapsed: typeof value.listCollapsed === 'boolean' ? value.listCollapsed : null,
    }
  } catch {
    return defaults()
  }
}
function dimension(value: unknown, fallback: number, min: number, max: number): number {
  return typeof value === 'number' && Number.isFinite(value)
    ? Math.max(min, Math.min(max, value))
    : fallback
}
export function writeLayoutPreferences(
  key: string,
  patch: Partial<WorkflowLayoutPreferences>,
): boolean {
  try {
    localStorage.setItem(key, JSON.stringify({ ...readLayoutPreferences(key), ...patch }))
    return true
  } catch {
    return false
  }
}
