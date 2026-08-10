import { apiClient, type Page, type TestPlanRun } from '../../lib/api'

export type QualityGateInput = {
  name: string
  enabled: boolean
  min_pass_rate: number
  max_failed: number
  max_flaky: number
  max_duration_regression_percent: number
  require_no_breaking_changes: boolean
}

export type QualityGate = QualityGateInput & {
  id: string
  project_id: string
  created_by_id: string
  created_at: string
  updated_at: string
}

export type FlakyRecord = {
  id: string
  project_id: string
  target_type: string
  target_id: string
  target_version: number
  total_runs: number
  passed_runs: number
  failed_runs: number
  transitions: number
  flaky_score: number
  quarantined: boolean
  last_status: string | null
  last_run_id: string | null
  last_run_at: string | null
  updated_at: string
}

export async function listQualityGates(projectId: string): Promise<QualityGate[]> {
  return (await apiClient.get<QualityGate[]>(`/projects/${projectId}/quality-gates`)).data
}

export async function createQualityGate(
  projectId: string,
  input: QualityGateInput,
): Promise<QualityGate> {
  return (await apiClient.post<QualityGate>(`/projects/${projectId}/quality-gates`, input)).data
}

export async function listFlakyTests(projectId: string): Promise<Page<FlakyRecord>> {
  return (
    await apiClient.get<Page<FlakyRecord>>(`/projects/${projectId}/flaky-tests`, {
      params: { page: 1, page_size: 100 },
    })
  ).data
}

export async function setFlakyQuarantine(
  projectId: string,
  recordId: string,
  quarantined: boolean,
): Promise<FlakyRecord> {
  return (
    await apiClient.put<FlakyRecord>(`/projects/${projectId}/flaky-tests/${recordId}/quarantine`, {
      quarantined,
    })
  ).data
}

export async function listQualityRuns(projectId: string): Promise<Page<TestPlanRun>> {
  return (
    await apiClient.get<Page<TestPlanRun>>(`/projects/${projectId}/test-plan-runs`, {
      params: { page: 1, page_size: 20 },
    })
  ).data
}

export async function downloadJunit(projectId: string, runId: string): Promise<Blob> {
  const response = await apiClient.get<string>(
    `/projects/${projectId}/test-plan-runs/${runId}/junit.xml`,
    { responseType: 'text' },
  )
  return new Blob([response.data], { type: 'application/xml' })
}
