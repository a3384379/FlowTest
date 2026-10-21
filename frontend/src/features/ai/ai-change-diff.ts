export type ChangeField = { path: string; before: unknown; after: unknown }
export function proposedDraft(
  before: Record<string, unknown>,
  patch: Record<string, unknown>,
): Record<string, unknown> {
  return {
    ...before,
    ...Object.fromEntries(
      Object.entries(patch).filter(([, value]) => value !== null && value !== undefined),
    ),
  }
}
export function changeFields(before: unknown, after: unknown, path = '$'): ChangeField[] {
  if (JSON.stringify(before) === JSON.stringify(after)) return []
  if (!isObject(before) || !isObject(after)) return [{ path, before, after }]
  return [...new Set([...Object.keys(before), ...Object.keys(after)])].flatMap((key) =>
    changeFields(before[key], after[key], `${path}.${key}`),
  )
}
function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}
