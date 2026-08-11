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
  job_type: AIJobType
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
  return (await apiClient.post<AIJob>('/ai/jobs', input)).data
}

export async function listAIJobs(projectId: string): Promise<Page<AIJob>> {
  return (
    await apiClient.get<Page<AIJob>>('/ai/jobs', {
      params: { project_id: projectId, page: 1, page_size: 50 },
    })
  ).data
}

export async function listAISuggestions(jobId: string): Promise<AISuggestion[]> {
  return (await apiClient.get<AISuggestion[]>(`/ai/jobs/${jobId}/suggestions`)).data
}

export async function reviewAISuggestion(
  suggestionId: string,
  decision: 'accept' | 'reject',
  input: { content?: Record<string, unknown>; note: string },
): Promise<AISuggestion> {
  return (await apiClient.post<AISuggestion>(`/ai/suggestions/${suggestionId}/${decision}`, input))
    .data
}
