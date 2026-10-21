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

export type FlakySummary = {
  project_id: string
  scope: 'project_cumulative'
  asset_total: number
  record_total: number
  flaky_total: number
  flaky_version_total: number
  quarantined_total: number
  quarantined_version_total: number
  oldest_updated_at: string | null
  latest_updated_at: string | null
  observed_at: string
}

type FlakyRecordLocator = {
  targetType: string | null
  targetId: string | null
  version: string | null
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

export async function listFlakyTests(
  projectId: string,
  page = 1,
  pageSize = 100,
): Promise<Page<FlakyRecord>> {
  return (
    await apiClient.get<Page<FlakyRecord>>(`/projects/${projectId}/flaky-tests`, {
      params: { page, page_size: pageSize },
    })
  ).data
}

export async function getFlakySummary(projectId: string): Promise<FlakySummary> {
  const summary = (await apiClient.get<FlakySummary>(`/projects/${projectId}/flaky-tests/summary`))
    .data
  if (summary.project_id !== projectId || summary.scope !== 'project_cumulative')
    throw new Error('Flaky 汇总不属于当前项目或统计范围')
  return summary
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

export async function getFlakyRecord(
  projectId: string,
  recordId: string,
  locator?: FlakyRecordLocator,
): Promise<FlakyRecord> {
  const expected = validatedFlakyLocator(locator)
  const record = (
    await apiClient.get<FlakyRecord>(`/projects/${projectId}/flaky-tests/${recordId}`)
  ).data
  if (record.id !== recordId || record.project_id !== projectId)
    throw new Error('Flaky 记录不属于当前项目或记录')
  if (
    expected &&
    (record.target_type !== expected.targetType ||
      record.target_id !== expected.targetId ||
      record.target_version !== expected.version)
  )
    throw new Error('Flaky 记录与链接中的资产或版本不一致')
  return record
}

function validatedFlakyLocator(locator?: FlakyRecordLocator) {
  if (
    !locator ||
    [locator.targetType, locator.targetId, locator.version].every((value) => value === null)
  )
    return null
  if (
    !locator.targetType?.trim() ||
    !locator.targetId?.trim() ||
    !/^[1-9]\d*$/.test(locator.version ?? '') ||
    !Number.isSafeInteger(Number(locator.version))
  )
    throw new Error('Flaky 链接的资产和版本定位不完整或无效')
  return {
    targetType: locator.targetType,
    targetId: locator.targetId,
    version: Number(locator.version),
  }
}

export async function listQualityRuns(
  projectId: string,
  page = 1,
  pageSize = 20,
): Promise<Page<TestPlanRun>> {
  return (
    await apiClient.get<Page<TestPlanRun>>(`/projects/${projectId}/test-plan-runs`, {
      params: { page, page_size: pageSize },
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

export async function listReleaseRisks(
  projectId: string,
  page = 1,
  pageSize = 100,
): Promise<Page<ReleaseRiskSummary>> {
  return (
    await apiClient.get<Page<ReleaseRiskSummary>>(`/projects/${projectId}/release-risks`, {
      params: { page, page_size: pageSize },
    })
  ).data
}

export async function getReleaseRisk(
  projectId: string,
  riskId: string,
): Promise<ReleaseRiskDetail> {
  const risk = (
    await apiClient.get<ReleaseRiskDetail>(`/projects/${projectId}/release-risks/${riskId}`)
  ).data
  if (risk.id !== riskId || risk.project_id !== projectId)
    throw new Error('风险快照不属于当前项目或记录')
  return risk
}

export async function createReleaseRisk(
  projectId: string,
  input: ReleaseRiskInput,
): Promise<ReleaseRiskDetail> {
  return (await apiClient.post<ReleaseRiskDetail>(`/projects/${projectId}/release-risks`, input))
    .data
}
