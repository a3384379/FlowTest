import { apiClient, type Page } from '../../lib/api'

export type ReleasePolicyInput = {
  name: string
  enabled: boolean
  quality_gate_id: string | null
  require_quality_gate: boolean
  require_contract_compatibility: boolean
  require_impact_evidence: boolean
  min_impact_coverage_percent: number
  require_release_risk: boolean
  max_release_risk_score: number
  require_performance_evidence: boolean
  require_runner_evidence: boolean
}

export type ReleasePolicy = ReleasePolicyInput & {
  id: string
  project_id: string
  created_by_id: string
  created_at: string
  updated_at: string
}

export type ReleaseDecisionInput = {
  release_policy_id: string
  candidate_ref: string
  test_plan_run_id?: string
  deployment_check_id?: string
  impact_run_id?: string
  release_risk_id?: string
  performance_run_id?: string
  runner_task_id?: string
}

export type ReleaseReason = {
  code: string
  evidence_type:
    'quality_gate' | 'contract_compatibility' | 'impact' | 'release_risk' | 'performance' | 'runner'
  status: 'passed' | 'blocked'
  message: string
  actual: unknown
  expected: unknown
}

export type ReleasePolicySnapshot = Omit<ReleasePolicyInput, 'enabled' | 'quality_gate_id'> & {
  snapshot_version: string
  policy_id: string
  quality_gate_id: string | null
  policy_updated_at: string
}

type QualityGateEvidence = {
  test_plan_run_id: string
  quality_gate_id: string
  run_status: string
  status: string
  quality_summary: unknown
  metrics: unknown
  violations: unknown
  evaluated_at: string | null
}

type ContractEvidence = {
  check_id: string
  provider_service_id: string
  provider_version: string
  decision: string
  evidence: unknown
  checked_at: string
}

type ImpactEvidence = {
  run_id: string
  status: string
  source_ref: string
  source_fingerprint: string
  change_count: number
  summary: unknown
  coverage_percent: number | null
  total_changes: number | null
  covered_changes: number | null
  gaps: unknown
  created_at: string
}

type ReleaseRiskEvidence = {
  risk_id: string
  impact_run_id: string
  algorithm_version: string
  score: number
  quality_score: number
  risk_level: string
  factors: unknown
  evidence: unknown
  fingerprint: string
  created_at: string
}

type PerformanceEvidence = {
  run_id: string
  scenario_id: string
  scenario_version: number
  status: string
  summary: unknown
  threshold_results: unknown
  gate_statuses: string[]
  gate_evaluations: Array<{
    id: string
    quality_gate_id: string
    status: string
    metrics: unknown
    violations: unknown
    evaluated_at: string
  }>
  completed_at: string | null
}

type RunnerEvidence = {
  task_id: string
  execution_id: string
  status: string
  attempts: number
  fencing_token: number
  completed_lease_count: number
  leases: Array<{
    id: string
    runner_id: string
    fencing_token: number
    status: string
    completed_at: string | null
  }>
  completed_at: string | null
}

export type ReleaseEvidenceSnapshot = {
  snapshot_version: string
  quality_gate: QualityGateEvidence | null
  contract_compatibility: ContractEvidence | null
  impact: ImpactEvidence | null
  release_risk: ReleaseRiskEvidence | null
  performance: PerformanceEvidence | null
  runner: RunnerEvidence | null
}

export type ReleaseDecision = {
  id: string
  project_id: string
  release_policy_id: string
  candidate_ref: string
  status: 'pass' | 'block'
  policy_snapshot: ReleasePolicySnapshot
  evidence_snapshot: ReleaseEvidenceSnapshot
  reasons: ReleaseReason[]
  fingerprint: string
  test_plan_run_id: string | null
  deployment_check_id: string | null
  impact_run_id: string | null
  release_risk_id: string | null
  performance_run_id: string | null
  runner_task_id: string | null
  created_by_id: string
  created_at: string
}

export async function listReleasePolicies(projectId: string): Promise<ReleasePolicy[]> {
  return (await apiClient.get<ReleasePolicy[]>(`/projects/${projectId}/release-policies`)).data
}

export async function createReleasePolicy(
  projectId: string,
  input: ReleasePolicyInput,
): Promise<ReleasePolicy> {
  return (await apiClient.post<ReleasePolicy>(`/projects/${projectId}/release-policies`, input))
    .data
}

export async function listReleaseDecisions(projectId: string): Promise<Page<ReleaseDecision>> {
  return (
    await apiClient.get<Page<ReleaseDecision>>(`/projects/${projectId}/release-decisions`, {
      params: { page: 1, page_size: 100 },
    })
  ).data
}

export async function createReleaseDecision(
  projectId: string,
  input: ReleaseDecisionInput,
): Promise<ReleaseDecision> {
  return (await apiClient.post<ReleaseDecision>(`/projects/${projectId}/release-decisions`, input))
    .data
}
