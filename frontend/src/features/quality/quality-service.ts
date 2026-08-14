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

export type FailureCluster = {
  id: string
  release_risk_id: string
  fingerprint: string
  title: string
  failure_category: string
  error_code: string | null
  node_type: string | null
  occurrence_count: number
  baseline_count: number
  affected_workflow_ids: string[]
  affected_workflow_names: string[]
  sample_execution_ids: string[]
  confidence: number
  regression_percent: number | null
  recommendation: string
  created_at: string
}

export type ReleaseRiskSummary = {
  id: string
  project_id: string
  impact_run_id: string
  title: string
  algorithm_version: string
  window_days: number
  score: number
  quality_score: number
  risk_level: 'low' | 'medium' | 'high' | 'critical'
  fingerprint: string
  created_by_id: string
  created_at: string
}

export type ReleaseRiskDetail = ReleaseRiskSummary & {
  window_started_at: string
  window_ended_at: string
  baseline_started_at: string
  baseline_ended_at: string
  factors: Array<{
    code: string
    label: string
    score: number
    max_score: number
    value: unknown
  }>
  evidence_snapshot: Record<string, unknown>
  quality_trend: Array<{
    date: string
    total: number
    passed: number
    failed: number
    pass_rate: number | null
  }>
  recommended_tests: Array<{
    target_type: string
    target_id: string
    name: string
    version: number | string | null
    priority: 'high' | 'medium'
    reasons: string[]
    change_keys: string[]
  }>
  failure_clusters: FailureCluster[]
}

export type ReleaseRiskInput = {
  impact_run_id: string
  title: string
  window_days: number
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

export async function listReleaseRisks(projectId: string): Promise<Page<ReleaseRiskSummary>> {
  return (
    await apiClient.get<Page<ReleaseRiskSummary>>(`/projects/${projectId}/release-risks`, {
      params: { page: 1, page_size: 100 },
    })
  ).data
}

export async function getReleaseRisk(
  projectId: string,
  riskId: string,
): Promise<ReleaseRiskDetail> {
  return (await apiClient.get<ReleaseRiskDetail>(`/projects/${projectId}/release-risks/${riskId}`))
    .data
}

export async function createReleaseRisk(
  projectId: string,
  input: ReleaseRiskInput,
): Promise<ReleaseRiskDetail> {
  return (await apiClient.post<ReleaseRiskDetail>(`/projects/${projectId}/release-risks`, input))
    .data
}
