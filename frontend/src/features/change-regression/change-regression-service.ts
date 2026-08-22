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
  selection_summary: Record<string, unknown>
  missing_tests: MissingTestProposal[]
  evidence: Record<string, unknown>
  failure_triage: Record<string, unknown>
  approved_by_id: string | null
  approved_at: string | null
  stages: ChangeRegressionStage[]
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
