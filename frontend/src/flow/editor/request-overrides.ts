import type { ApiVersion } from '../../lib/api'

type SectionEdit<T> = { mode: 'inherit' } | { mode: 'custom'; value: T }
export type RequestSectionEdits = {
  params: SectionEdit<ApiVersion['query_parameters']>
  headers: SectionEdit<Record<string, string>>
  body: SectionEdit<{ kind: ApiVersion['body_kind']; value: unknown }>
}
export function applyOwnedRequestSections(
  original: unknown,
  edits: RequestSectionEdits,
): Record<string, unknown> {
  const next = isRecord(original) ? structuredClone(original) : {}
  applySection(next, 'query_parameters', edits.params)
  applySection(next, 'headers', edits.headers)
  applySection(next, 'body', edits.body)
  return next
}
function applySection<T>(target: Record<string, unknown>, key: string, edit: SectionEdit<T>): void {
  if (edit.mode === 'inherit') delete target[key]
  else target[key] = structuredClone(edit.value)
}
export function extraRequestPolicies(original: unknown): string[] {
  if (!isRecord(original)) return []
  return Object.keys(original).filter(
    (key) => !['query_parameters', 'headers', 'body'].includes(key),
  )
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
