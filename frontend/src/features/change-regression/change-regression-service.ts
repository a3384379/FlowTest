import { apiClient, type Page, type TestPlan } from '../../lib/api'
import type { ReleasePolicy } from '../release-gate/release-gate-service'

export type ChangeRegressionStatus =
  | 'review_required'
  | 'approved'
  | 'queued'
  | 'running'
  | 'evidence_ready'
  | 'passed'
  | 'blocked'
  | 'failed'

export type ChangeRegressionInput = {
  title: string
  source_ref: string
  candidate_ref: string
  git_diff?: string
  openapi_diffs: Array<{ baseline_run_id: string; current_run_id: string }>
  schema_diffs: Array<{ baseline_artifact_id: string; current_artifact_id: string }>
  test_plan_id: string
  release_policy_id: string
  release_risk_id?: string
  deployment_check_id?: string
  generate_missing_tests: boolean
}

export type ChangeRegressionStage = {
  id: string
  sequence: number
  stage: string
  status: string
  details: Record<string, unknown>
  actor_id: string | null
  created_at: string
}

export type MissingTestProposal = {
  item_id: string
  title: string
  proposed_content: Record<string, unknown>
  review_status: 'pending' | 'accepted' | 'rejected'
  review_note: string
  materialized_resource_type: string | null
  materialized_resource_id: string | null
}

export type SemanticCoverageScope = {
  change_key: string
  operation: {
    api_definition_id: string | null
    api_version: number | null
    portable_operation_ref: string
    service_key: string
    method: string
    normalized_path: string
    contract_fingerprint: string
  } | null
  target: {
    location: 'path' | 'query' | 'header' | 'cookie' | 'body'
    field_path: string[]
    constraint: string
    before: unknown
    after: unknown
  } | null
  project_known_coverage: 'covered' | 'missing'
  current_test_plan_coverage: 'covered' | 'missing'
  project_known_values: string[]
  current_test_plan_values: string[]
  project_missing_values: string[]
  current_test_plan_missing_values: string[]
  oracle_sources: Array<{ source_type: string; source_ref: string }>
  requires_review: boolean
}

export type SemanticCoverageStatus =
  | 'COVERED'
  | 'PARTIAL'
  | 'MISSING'
  | 'WAIVED'
  | 'UNKNOWN'
  | 'VERSION_MISMATCH'
  | 'CONTRACT_MISMATCH'

export type SemanticGapWaiver = {
  id: string
  gap_key: string
  revision: number
  supersedes_waiver_id: string | null
  reason: string
  approved_by_id: string
  approved_at: string
  expires_at: string | null
  operation_identity: Record<string, unknown>
  semantic_requirement: Record<string, unknown>
  requirement_fingerprint: string
  active: boolean
}

export type CurrentPlanGap = {
  change_key: string
  gap_key: string
  operation: SemanticCoverageScope['operation']
  target: SemanticCoverageScope['target']
  semantic_requirement: {
    semantic_value?: string
    expected_category?: string
    oracle_set_fingerprint?: string
  }
  requirement_fingerprint: string
  coverage_status: SemanticCoverageStatus
  project_known_coverage: SemanticCoverageStatus
  current_test_plan_coverage: SemanticCoverageStatus
  oracle_reachability: Array<
    | 'direct_oracle'
    | 'unconditional_assert'
    | 'conditional_assert'
    | 'disconnected_assert'
    | 'unknown_graph'
  >
  recommended_existing_assets: Array<{
    target_type: 'workflow' | 'test_case'
    target_id: string
  }>
  waiver: {
    id: string
    revision: number
    supersedes_waiver_id: string | null
    reason: string
    approved_by: string
    approved_at: string
    expires_at: string | null
  } | null
}

export type ChangeRegressionSelectionSummary = Record<string, unknown> & {
  asset_coverage_gap_count?: number
  impact_selected_asset_count?: number
  semantic_coverage_scopes?: SemanticCoverageScope[]
  current_plan_recommendations?: Array<Record<string, unknown>>
  current_plan_gaps?: CurrentPlanGap[]
  asset_mapping_gap_count?: number
  project_semantic_gap_count?: number
  current_test_plan_semantic_gap_count?: number
  waived_current_plan_gap_count?: number
  unresolved_current_plan_gap_count?: number
  operation_regenerations?: Array<{
    change_key: string
    item_id: string
    status: 'regenerated' | 'superseded'
    old_design_fingerprint: string
    design_fingerprint: string
    contract_fingerprint: string
    scenario_count: number
    oracle_count: number
  }>
}

export type FailureTriageResult = {
  algorithm_version: 's47-failure-triage-v2'
  primary_classification: string
  secondary_candidates: string[]
  confidence: number
  reason_codes: string[]
  affected_service: string | null
  endpoint_variant?: string | null
  affected_operation: string | null
  evidence_refs: string[]
  retry_signal: boolean
  recommended_action: string
  recommended_regression: string[]
}

export type ChangeRegressionSummary = {
  id: string
  project_id: string
  title: string
  source_ref: string
  source_fingerprint: string
  candidate_ref: string
  status: ChangeRegressionStatus
  impact_run_id: string
  test_plan_id: string
  test_plan_run_id: string | null
  release_policy_id: string
  change_set_id: string | null
  release_decision_id: string | null
  selected_asset_count: number
  missing_test_count: number
  created_by_id: string
  created_at: string
  updated_at: string
}

export type ChangeRegressionRun = Omit<
  ChangeRegressionSummary,
  'selected_asset_count' | 'missing_test_count'
> & {
  release_risk_id: string | null
  deployment_check_id: string | null
  selected_assets: Array<Record<string, unknown>>
  selection_summary: ChangeRegressionSelectionSummary
  missing_tests: MissingTestProposal[]
  evidence: Record<string, unknown>
  failure_triage: FailureTriageResult | Record<string, unknown>
  semantic_gap_waivers: SemanticGapWaiver[]
  approved_by_id: string | null
  approved_at: string | null
  stages: ChangeRegressionStage[]
}

export async function addProjectKnownTestToCurrentPlan(
  projectId: string,
  runId: string,
  input: {
    gap_key: string
    item: {
      target_type: 'workflow' | 'case'
      target_id: string
      environment_id?: string
    }
  },
): Promise<ChangeRegressionRun> {
  return (
    await apiClient.post<ChangeRegressionRun>(
      '/projects/' + projectId + '/change-regressions/' + runId + '/add-project-known-test',
      input,
    )
  ).data
}

export async function waiveSemanticGap(
  projectId: string,
  runId: string,
  input: { gap_key: string; reason: string; expires_at?: string },
): Promise<ChangeRegressionRun> {
  return (
    await apiClient.post<ChangeRegressionRun>(
      '/projects/' + projectId + '/change-regressions/' + runId + '/semantic-gap-waivers',
      input,
    )
  ).data
}

export async function selectChangeRegressionOperation(
  projectId: string,
  runId: string,
  input: { change_key: string; api_definition_id: string; api_version: number },
): Promise<ChangeRegressionRun> {
  return (
    await apiClient.post<ChangeRegressionRun>(
      '/projects/' + projectId + '/change-regressions/' + runId + '/operation-selection',
      input,
    )
  ).data
}

export async function listChangeRegressions(
  projectId: string,
): Promise<Page<ChangeRegressionSummary>> {
  return (
    await apiClient.get<Page<ChangeRegressionSummary>>(
      '/projects/' + projectId + '/change-regressions',
      { params: { page: 1, page_size: 100 } },
    )
  ).data
}

export async function getChangeRegression(
  projectId: string,
  runId: string,
): Promise<ChangeRegressionRun> {
  return (
    await apiClient.get<ChangeRegressionRun>(
      '/projects/' + projectId + '/change-regressions/' + runId,
    )
  ).data
}

export async function createChangeRegression(
  projectId: string,
  input: ChangeRegressionInput,
): Promise<ChangeRegressionRun> {
  return (
    await apiClient.post<ChangeRegressionRun>(
      '/projects/' + projectId + '/change-regressions',
      input,
    )
  ).data
}

export async function reviewMissingTest(
  projectId: string,
  runId: string,
  itemId: string,
  decision: 'accept' | 'reject',
  note: string,
): Promise<ChangeRegressionRun> {
  return (
    await apiClient.post<ChangeRegressionRun>(
      '/projects/' +
        projectId +
        '/change-regressions/' +
        runId +
        '/change-set-items/' +
        itemId +
        '/' +
        decision,
      { note },
    )
  ).data
}

export async function approveChangeRegression(
  projectId: string,
  runId: string,
  note: string,
): Promise<ChangeRegressionRun> {
  return (
    await apiClient.post<ChangeRegressionRun>(
      '/projects/' + projectId + '/change-regressions/' + runId + '/approve',
      { note },
    )
  ).data
}

export async function executeChangeRegression(
  projectId: string,
  runId: string,
): Promise<ChangeRegressionRun> {
  return (
    await apiClient.post<ChangeRegressionRun>(
      '/projects/' + projectId + '/change-regressions/' + runId + '/execute',
    )
  ).data
}

export async function evaluateChangeRegressionRelease(
  projectId: string,
  runId: string,
): Promise<ChangeRegressionRun> {
  return (
    await apiClient.post<ChangeRegressionRun>(
      '/projects/' + projectId + '/change-regressions/' + runId + '/release-gate',
    )
  ).data
}

export async function listChangeRegressionPlans(projectId: string): Promise<Page<TestPlan>> {
  return (
    await apiClient.get<Page<TestPlan>>('/projects/' + projectId + '/test-plans', {
      params: { page: 1, page_size: 100 },
    })
  ).data
}

export async function listChangeRegressionPolicies(projectId: string): Promise<ReleasePolicy[]> {
  return (await apiClient.get<ReleasePolicy[]>('/projects/' + projectId + '/release-policies')).data
}
