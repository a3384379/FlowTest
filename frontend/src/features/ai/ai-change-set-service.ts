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

export type AIReviewBaseline = {
  target_type: 'test_case' | 'workflow'
  target_id: string
  snapshot_sha256: string
  content: {
    name: string
    description: string
    definition: Record<string, unknown>
    tags?: string[] | null
  }
  current_version: number | null
  draft_revision: number | null
  updated_at: string
  redaction_mode: 'on' | 'off'
  redaction_policy_version: number
}
export type AIChangeSetDetail = AIChangeSetSummary & {
  review_baselines?: AIReviewBaseline[]
  source_snapshot: Record<string, unknown>
  items: AIChangeItem[]
}

export type AIChangeSetInput = {
  project_id: string
  impact_run_id: string
  release_risk_id: string
  title: string
}

export async function listAIChangeSets(
  projectId: string,
  page = 1,
  pageSize = 100,
): Promise<Page<AIChangeSetSummary>> {
  const result = (
    await apiClient.get<Page<AIChangeSetSummary>>('/ai/change-sets', {
      params: { project_id: projectId, page, page_size: pageSize },
    })
  ).data
  if (result.items.some((item) => item.project_id !== projectId))
    throw new Error('变更集目录含有其他项目记录，已停止展示')
  return result
}

export async function getAIChangeSet(changeSetId: string): Promise<AIChangeSetDetail> {
  const result = (
    await apiClient.get<AIChangeSetDetail>(`/ai/change-sets/${encodeURIComponent(changeSetId)}`)
  ).data
  if (result.id !== changeSetId) throw new Error('变更集回执与请求不一致')
  return result
}

export async function createAIChangeSet(input: AIChangeSetInput): Promise<AIChangeSetSummary> {
  const result = (await apiClient.post<AIChangeSetSummary>('/ai/change-sets', input)).data
  if (result.project_id !== input.project_id) throw new Error('生成回执不属于当前项目')
  return result
}

export async function reviewAIChangeItem(
  changeSetId: string,
  itemId: string,
  decision: 'accept' | 'reject',
  input: { content?: Record<string, unknown>; note: string },
): Promise<AIChangeItem> {
  const result = (
    await apiClient.post<AIChangeItem>(
      `/ai/change-sets/${changeSetId}/items/${itemId}/${decision}`,
      input,
    )
  ).data
  if (
    result.id !== itemId ||
    result.review_status !== (decision === 'accept' ? 'accepted' : 'rejected')
  )
    throw new Error('变更项审核回执与请求不一致')
  return result
}
