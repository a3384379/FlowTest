import type { WorkflowDefinition, WorkflowNode } from '../../lib/api'

export type EditorSelection = {
  nodeIds: readonly string[]
  edgeIds: readonly string[]
  primary: { kind: 'node' | 'edge'; id: string } | null
}
export type EditDiagnostic = {
  code: string
  severity: 'error' | 'warning'
  message: string
  nodeId?: string
  edgeId?: string
}
export type GraphEditResult =
  | { kind: 'unchanged' }
  | { kind: 'blocked'; diagnostics: readonly EditDiagnostic[] }
  | { kind: 'changed'; definition: WorkflowDefinition; diagnostics: readonly EditDiagnostic[] }
export type NodePositionUpdate = { id: string; position: WorkflowNode['position'] }
export type GraphConnectionInput = {
  sourceId: string
  targetId: string
  branch: 'true' | 'false' | null
  edgeId: string
}
export function emptySelection(): EditorSelection {
  return { nodeIds: [], edgeIds: [], primary: null }
}
export function jsonEqual(left: unknown, right: unknown): boolean {
  if (left === right) return true
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object') return false
  if (Array.isArray(left) !== Array.isArray(right)) return false
  const a = Object.entries(left).filter(([, value]) => value !== undefined)
  const b = Object.entries(right).filter(([, value]) => value !== undefined)
  if (a.length !== b.length) return false
  const values = new Map(b)
  return a.every(([key, value]) => values.has(key) && jsonEqual(value, values.get(key)))
}
