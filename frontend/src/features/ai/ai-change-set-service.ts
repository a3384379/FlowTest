import { apiClient, type Page } from '../../lib/api'

export type AIChangeItem = {
  id: string
  position: number
  item_type: 'test_case' | 'workflow' | 'assertion'
  action: 'create' | 'update'
  title: string
  target_resource_id: string | null
  target_snapshot_sha256: string | null
  proposed_content: Record<string, unknown>
  review_status: 'pending' | 'accepted' | 'rejected'
  review_note: string
  reviewed_by_id: string | null
  reviewed_at: string | null
  materialized_resource_type: string | null
  materialized_resource_id: string | null
  created_at: string
  updated_at: string
}

export type AIChangeSetSummary = {
  id: string
  project_id: string
  impact_run_id: string
  release_risk_id: string
  ai_job_id: string
  title: string
  status: 'generating' | 'draft' | 'partially_reviewed' | 'accepted' | 'rejected' | 'failed'
  source_fingerprint: string
  created_by_id: string
  created_at: string
  updated_at: string
}

export type AIChangeSetDetail = AIChangeSetSummary & {
  source_snapshot: Record<string, unknown>
  items: AIChangeItem[]
}

export type AIChangeSetInput = {
  project_id: string
  impact_run_id: string
  release_risk_id: string
  title: string
}

export async function listAIChangeSets(projectId: string): Promise<Page<AIChangeSetSummary>> {
  return (
    await apiClient.get<Page<AIChangeSetSummary>>('/ai/change-sets', {
      params: { project_id: projectId, page: 1, page_size: 100 },
    })
  ).data
}

export async function getAIChangeSet(changeSetId: string): Promise<AIChangeSetDetail> {
  return (await apiClient.get<AIChangeSetDetail>(`/ai/change-sets/${changeSetId}`)).data
}

export async function createAIChangeSet(input: AIChangeSetInput): Promise<AIChangeSetSummary> {
  return (await apiClient.post<AIChangeSetSummary>('/ai/change-sets', input)).data
}

export async function reviewAIChangeItem(
  changeSetId: string,
  itemId: string,
  decision: 'accept' | 'reject',
  input: { content?: Record<string, unknown>; note: string },
): Promise<AIChangeItem> {
  return (
    await apiClient.post<AIChangeItem>(
      `/ai/change-sets/${changeSetId}/items/${itemId}/${decision}`,
      input,
    )
  ).data
}
