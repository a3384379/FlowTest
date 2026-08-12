import { apiClient, type Page } from '../../lib/api'

export type LoadExecutor = 'constant_vus' | 'ramping_vus'

export type PerformanceStage = {
  duration_seconds: number
  target_vus: number
}

export type PerformanceStep = {
  name: string
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE' | 'HEAD' | 'OPTIONS'
  url: string
  headers: Record<string, string>
  body: unknown
  expected_statuses: number[]
  pause_seconds: number
}

export type PerformanceThreshold = {
  metric: string
  aggregation: string
  operator: '<' | '<=' | '>' | '>='
  value: number
  abort_on_fail: boolean
  delay_abort_seconds: number
}

export type PerformanceDefinition = {
  executor: LoadExecutor
  steps: PerformanceStep[]
  thresholds: PerformanceThreshold[]
  vus: number | null
  duration_seconds: number | null
  start_vus: number | null
  stages: PerformanceStage[]
  graceful_stop_seconds: number
}

export type PerformanceScenario = {
  id: string
  project_id: string
  name: string
  description: string
  version: number
  status: 'draft' | 'published'
  target_type: 'rest' | 'http_workflow'
  definition: PerformanceDefinition
  compiled_sha256: string
  published_at: string | null
  created_by_id: string
  created_at: string
  updated_at: string
}

export type PerformanceGateEvaluation = {
  id: string
  quality_gate_id: string
  performance_run_id: string
  status: 'passed' | 'failed'
  metrics: Record<string, unknown>
  violations: string[]
  evaluated_at: string
}

export type PerformanceRun = {
  id: string
  project_id: string
  scenario_id: string
  scenario_version: number
  status: 'queued' | 'running' | 'passed' | 'failed' | 'cancelled'
  definition_snapshot: PerformanceDefinition
  compiled_sha256: string
  summary: {
    http_req_duration_p95_ms?: number | null
    http_reqs_rate?: number | null
    http_reqs_count?: number | null
    http_req_failed_rate?: number | null
    baseline_p95_ms?: number | null
    p95_regression_percent?: number | null
  }
  threshold_results: Array<{ metric: string; expression: string; passed: boolean }>
  baseline_run_id: string | null
  raw_metrics_artifact_id: string | null
  error_code: string | null
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  created_by_id: string
  created_at: string
  updated_at: string
  gate_evaluations: PerformanceGateEvaluation[]
}

export type PerformanceScenarioInput = {
  name: string
  description: string
  definition: PerformanceDefinition
}

export async function listPerformanceScenarios(
  projectId: string,
): Promise<Page<PerformanceScenario>> {
  return (
    await apiClient.get<Page<PerformanceScenario>>(`/projects/${projectId}/performance-scenarios`, {
      params: { page: 1, page_size: 100 },
    })
  ).data
}

export async function createPerformanceScenario(
  projectId: string,
  input: PerformanceScenarioInput,
): Promise<PerformanceScenario> {
  return (
    await apiClient.post<PerformanceScenario>(`/projects/${projectId}/performance-scenarios`, input)
  ).data
}

export async function publishPerformanceScenario(
  projectId: string,
  scenarioId: string,
): Promise<PerformanceScenario> {
  return (
    await apiClient.post<PerformanceScenario>(
      `/projects/${projectId}/performance-scenarios/${scenarioId}/publish`,
    )
  ).data
}

export async function runPerformanceScenario(
  projectId: string,
  scenarioId: string,
): Promise<PerformanceRun> {
  return (
    await apiClient.post<PerformanceRun>(
      `/projects/${projectId}/performance-scenarios/${scenarioId}/runs`,
    )
  ).data
}

export async function listPerformanceRuns(projectId: string): Promise<Page<PerformanceRun>> {
  return (
    await apiClient.get<Page<PerformanceRun>>(`/projects/${projectId}/performance-runs`, {
      params: { page: 1, page_size: 50 },
    })
  ).data
}

export async function getPerformanceRun(projectId: string, runId: string): Promise<PerformanceRun> {
  return (await apiClient.get<PerformanceRun>(`/projects/${projectId}/performance-runs/${runId}`))
    .data
}
