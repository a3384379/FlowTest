import type { BulkDraft } from '../../features/api-console/use-bulk-draft'
import { createContext, useContext } from 'react'
import type { WorkflowNode } from '../../lib/api'
import type { BodyEditorFields } from '../../features/api-console/body-edit'
import type { KeyValueField } from '../../features/api-console/bulk-edit'
import type { ApiVersion } from '../../lib/api'

export type RequestEditorFields = BodyEditorFields & {
  query_parameters: ApiVersion['query_parameters']
  headers: KeyValueField[]
}
export type RequestModes = {
  params: 'inherit' | 'custom'
  headers: 'inherit' | 'custom'
  body: 'inherit' | 'custom'
}
export type WorkflowRequestEditorDraft = {
  identity: WorkflowRequestIdentity
  fields: RequestEditorFields
  modes: RequestModes
  customDrafts: Partial<Record<keyof RequestModes, Partial<RequestEditorFields>>>
  activeTab: string
  bulkDrafts?: Record<string, BulkDraft>
}
export type WorkflowRequestIdentity = {
  projectId: string
  nodeId: string
  apiDefinitionId: string
  apiVersion: number
}
export type RawFieldDraft = { text: string; error: string | null }
export type WorkflowNodeEditKind = 'node' | 'edges'
export type WorkflowNodeEditorDraft = {
  nodeId: string
  baseNode: WorkflowNode
  draftNode: WorkflowNode
  generation: number
  dirty: boolean
  rawFields: Record<string, RawFieldDraft>
  activeTab: string
  requestDraft: WorkflowRequestEditorDraft | null
  requestDirty: boolean
}
export type NodeEditContextValue = {
  draft: WorkflowNodeEditorDraft
  setRaw: (key: string, value: RawFieldDraft) => void
  setRequest: (value: WorkflowRequestEditorDraft, dirty?: boolean) => void
  isRequestCurrent: (identity: WorkflowRequestIdentity) => boolean
  apply: (replacement?: WorkflowNode) => boolean
  registerRequestApply: (apply: (() => Promise<boolean>) | null) => void
}
export const NodeEditContext = createContext<NodeEditContextValue | null>(null)
export function useNodeEditContext() {
  return useContext(NodeEditContext)
}
