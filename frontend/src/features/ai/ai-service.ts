import { apiClient, type Page } from '../../lib/api'

export type AIJobType =
  'schema_cases' | 'assertion_suggestions' | 'workflow_draft' | 'failure_analysis'

export type AIStatus = {
  enabled: boolean
  model: string | null
  sample_sharing_enabled: boolean
}

export type AIJob = {
  id: string
  project_id: string
  job_type: AIJobType | 'change_set'
  status: 'pending' | 'running' | 'completed' | 'failed'
  input_sha256: string
  prompt_template_version: string
  model_name: string
  sample_included: boolean
  token_usage: Record<string, number>
  error_code: string | null
  error_message: string | null
  created_by_id: string
  created_at: string
  updated_at: string
  started_at?: string | null
  completed_at?: string | null
  redaction_mode?: 'on' | 'off' | null
  redaction_policy_version?: number | null
}

export type AISuggestion = {
  id: string
  job_id: string
  position: number
  suggestion_type: 'test_case' | 'assertion' | 'workflow' | 'failure_analysis'
  title: string
  content: Record<string, unknown>
  review_status: 'pending' | 'accepted' | 'rejected'
  review_note: string
  accepted_resource_type: string | null
  accepted_resource_id: string | null
  created_at: string
  updated_at: string
  reviewed_by_id?: string | null
  reviewed_at?: string | null
}

export type AIJobInput = {
  project_id: string
  job_type: AIJobType
  schema_document?: Record<string, unknown>
  metadata: Record<string, unknown>
  sample?: unknown
}

export async function getAIStatus(projectId: string): Promise<AIStatus> {
  return (await apiClient.get<AIStatus>('/ai/status', { params: { project_id: projectId } })).data
}

export async function updateAISettings(
  projectId: string,
  sampleSharingEnabled: boolean,
): Promise<AIStatus> {
  return (
    await apiClient.put<AIStatus>(`/ai/projects/${projectId}/settings`, {
      sample_sharing_enabled: sampleSharingEnabled,
    })
  ).data
}

export async function createAIJob(input: AIJobInput): Promise<AIJob> {
  const job = (await apiClient.post<AIJob>('/ai/jobs', input)).data
  if (job.project_id !== input.project_id) throw new Error('AI 任务项目身份不匹配')
  return job
}

export async function listAIJobs(projectId: string, page = 1, pageSize = 50): Promise<Page<AIJob>> {
  return (
    await apiClient.get<Page<AIJob>>('/ai/jobs', {
      params: { project_id: projectId, page, page_size: pageSize },
    })
  ).data
}

export async function getAIJob(projectId: string, jobId: string): Promise<AIJob> {
  const job = (await apiClient.get<AIJob>(`/ai/jobs/${jobId}`)).data
  if (job.id !== jobId || job.project_id !== projectId) throw new Error('AI 任务项目或ID身份不匹配')
  return job
}

export async function listAISuggestions(jobId: string): Promise<AISuggestion[]> {
  const suggestions = (await apiClient.get<AISuggestion[]>(`/ai/jobs/${jobId}/suggestions`)).data
  if (suggestions.some((item) => item.job_id !== jobId)) throw new Error('AI 建议任务身份不匹配')
  return suggestions
}

export async function reviewAISuggestion(
  suggestionId: string,
  decision: 'accept' | 'reject',
  input: { content?: Record<string, unknown>; note: string },
  jobId: string,
): Promise<AISuggestion> {
  const result = (
    await apiClient.post<AISuggestion>(`/ai/suggestions/${suggestionId}/${decision}`, input)
  ).data
  if (result.id !== suggestionId || result.job_id !== jobId)
    throw new Error('AI 审核响应身份不匹配')
  return result
}

export type AISourceKind = 'api' | 'schema' | 'execution'
export type AISourceSummary = {
  id: string
  kind: AISourceKind
  name: string
  version: number | null
  protocol: string | null
  status: string | null
  created_at: string
}
export type AIPublicSourceMetadata = {
  source_kind: AISourceKind
  source_id: string
  name: string
  version: number | null
  protocol: string | null
  method: string | null
  path: string | null
  status: string | null
  workflow_id: string | null
  workflow_version_id: string | null
  error_code: string | null
  error_message: string | null
  content_fingerprint: string | null
  started_at: string | null
  completed_at: string | null
}
export type AIPublicSource = {
  project_id: string
  metadata: AIPublicSourceMetadata
  schema_document: Record<string, unknown> | null
  notices: string[]
}
export async function listAISources(
  projectId: string,
  kind: AISourceKind,
  page: number,
  search: string,
): Promise<Page<AISourceSummary>> {
  return (
    await apiClient.get<Page<AISourceSummary>>(`/ai/projects/${projectId}/sources`, {
      params: { kind, page, page_size: 20, search },
    })
  ).data
}
export async function getAISource(
  projectId: string,
  kind: AISourceKind,
  id: string,
  version?: number,
): Promise<AIPublicSource> {
  const source = (
    await apiClient.get<AIPublicSource>(
      `/ai/projects/${projectId}/sources/${kind}/${encodeURIComponent(id)}`,
      { params: { version } },
    )
  ).data
  if (
    source.project_id !== projectId ||
    source.metadata.source_kind !== kind ||
    source.metadata.source_id !== id
  )
    throw new Error('AI 来源项目或身份不匹配')
  if (version !== undefined && source.metadata.version !== version)
    throw new Error('AI 来源版本不匹配')
  return source
}
