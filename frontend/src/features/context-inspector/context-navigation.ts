import type {
  ContextConflict,
  ContextEvidenceItem,
  EvidenceProviderType,
} from './context-inspector-service'
export type ContextPanel = 'overview' | 'conflicts' | 'evidence' | 'knowledge' | 'proposals'
export type ContextNavigation = {
  panel?: ContextPanel
  evidence?: string | null
  knowledge?: string | null
  conflict?: string | null
  providerType?: EvidenceProviderType | null
  certainty?: string | null
  warnings?: string | null
  sourceEvidence?: string | null
}
export type ContextSelection = {
  panel: ContextPanel
  evidence: string | null
  knowledge: string | null
  conflict: string | null
  providerType: string | null
  certainty: string | null
  warnings: string | null
  sourceEvidence: string | null
}
const panels: readonly string[] = ['overview', 'conflicts', 'evidence', 'knowledge', 'proposals']
export function readContextSelection(params: URLSearchParams): ContextSelection {
  const panel = params.get('panel')
  return {
    panel: panels.includes(panel ?? '') ? (panel as ContextPanel) : 'overview',
    evidence: params.get('evidence') || null,
    knowledge: params.get('knowledge') || null,
    conflict: params.get('conflict') || null,
    providerType: params.get('providerType') || null,
    certainty: params.get('certainty') || null,
    warnings: params.get('warnings') || null,
    sourceEvidence: params.get('sourceEvidence') || null,
  }
}
export function writeContextNavigation(
  current: URLSearchParams,
  patch: ContextNavigation,
): URLSearchParams {
  const next = new URLSearchParams(current)
  for (const [key, value] of Object.entries(patch)) {
    if (value === null) next.delete(key)
    else if (value !== undefined) next.set(key, value)
  }
  return next
}
export function clearContextSelection(current: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(current)
  for (const key of [
    'revision',
    'panel',
    'evidence',
    'knowledge',
    'conflict',
    'providerType',
    'certainty',
    'warnings',
    'sourceEvidence',
  ])
    next.delete(key)
  return next
}
export function evidenceReference(
  ref: string,
  items: ContextEvidenceItem[],
): ContextEvidenceItem | null {
  const matches = items.filter((item) =>
    [item.id, item.fingerprint, `evidence://context/${item.fingerprint}`].includes(ref),
  )
  return matches.length === 1 ? matches[0] : null
}
export function selectedConflict(
  conflicts: ContextConflict[],
  index: string | null,
): ContextConflict | null {
  if (index === null || !/^(0|[1-9]\d*)$/.test(index)) return null
  const value = Number(index)
  return Number.isSafeInteger(value) ? (conflicts[value] ?? null) : null
}
export function contextPageNumber(raw: string | null): number {
  if (!raw || !/^[1-9]\d*$/.test(raw)) return 1
  const value = Number(raw)
  return Number.isSafeInteger(value) ? value : 1
}
