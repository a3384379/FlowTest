import { apiClient } from '../../lib/api'

export type MCPChangeItem = {
  id: string
  position: number
  item_type: 'test_design' | 'test_case' | 'test_plan_update'
  action: 'create' | 'update'
  title: string
  proposed_content: Record<string, unknown>
  review_status: 'pending' | 'accepted' | 'rejected'
  review_note: string
  reviewed_by_id: string | null
  reviewed_at: string | null
  materialized_resource_type: string | null
  materialized_resource_id: string | null
}

export type MCPChangeSet = {
  id: string
  project_id: string
  title: string
  status: 'draft' | 'partially_reviewed' | 'accepted' | 'rejected'
  source_type: 'mcp'
  source_ref: string | null
  actor_type: string
  source_fingerprint: string
  created_by_id: string
  created_at: string
  updated_at: string
  applied_at: string | null
  governance: {
    confidence: number
    risk_level: 'low' | 'medium' | 'high' | 'critical'
    requires_review: boolean
    manual_approval_required: boolean
    reason_codes: string[]
  }
  approval: {
    id: string
    decision: string
    approved_by_id: string
    approved_at: string
  } | null
  items: MCPChangeItem[]
}

type MCPChangeSetEnvelope = {
  data: MCPChangeSet
  warnings: string[]
  trace_id: string
}

export async function getMCPChangeSet(changeSetId: string): Promise<MCPChangeSetEnvelope> {
  return (await apiClient.get<MCPChangeSetEnvelope>(`/mcp/write/change-sets/${changeSetId}`)).data
}

export async function approveMCPChangeSet(
  changeSetId: string,
  note: string,
): Promise<MCPChangeSetEnvelope> {
  return (
    await apiClient.post<MCPChangeSetEnvelope>(`/mcp/write/change-sets/${changeSetId}/approve`, {
      note,
    })
  ).data
}

export async function reviewMCPChangeItem(
  changeSetId: string,
  itemId: string,
  decision: 'accept' | 'reject',
  approvalId: string | null,
): Promise<MCPChangeSetEnvelope> {
  return (
    await apiClient.post<MCPChangeSetEnvelope>(
      `/mcp/write/change-sets/${changeSetId}/items/${itemId}/${decision}`,
      {
        note: '前端人工审核',
        ...(decision === 'accept' && approvalId ? { approval_id: approvalId } : {}),
      },
    )
  ).data
}
