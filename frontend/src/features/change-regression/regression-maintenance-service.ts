import { apiClient, type FlowSpecDocument } from '../../lib/api'
import type { ChangeRegressionRun } from './change-regression-service'

export type ContextBinding = {
  context_id: string
  before_revision: number
  after_revision: number
}

export type RegressionMaintenance = {
  schema_version: 's47.4-change-regression-v4'
  impact_run_id: string
  context_diff_ref: string
  knowledge_diff_ref: string
  comparison: ContextBinding & {
    before_revision_id: string
    after_revision_id: string
    difference: {
      before_fingerprint: string
      after_fingerprint: string
      changed: boolean
      evidence: { added: string[]; removed: string[] }
      conflicts: { added: string[]; removed: string[] }
      knowledge: {
        changed: boolean
        nodes: Array<{ node_id: string; changed_fact_names: string[] }>
        edges: {
          added: Array<{ source: string; target: string; relation: string }>
          removed: Array<{ source: string; target: string; relation: string }>
        }
      }
    }
  }
  affected: {
    total_workflows: number
    scanned_workflow_ids: string[]
    analysis_complete: boolean
    affected_workflows: Array<{
      workflow_id: string
      draft_revision: number
      reasons: Array<{
        source_ref: string
        match_strength: string
        knowledge_relation: string | null
      }>
    }>
    diagnostics: Array<{ code: string; workflow_id: string | null }>
  }
  proposals: Array<{
    change_set_id: string
    workflow_id: string
    review_status: 'pending' | 'accepted' | 'rejected'
    applied: boolean
  }>
  review: {
    actor_id: string
    reviewed_at: string
    note: string
    acknowledged_incomplete_analysis: boolean
  } | null
  required_workflows: Array<{
    workflow_id: string
    workflow_version: number
    fingerprint: string
  }>
  preview_counts_as_execution: false
  automatic_apply_allowed: false
}

export type RegressionMaintenancePatch = ContextBinding & {
  impact_run_id: string
  expected_target_revision: number
  kind: 'binding' | 'data' | 'cleanup' | 'contract_drift' | 'oracle'
  proposed_spec: FlowSpecDocument
  rationale: string
  acknowledge_oracle_weakening: boolean
}

function root(projectId: string, runId: string) {
  return `/projects/${projectId}/change-regressions/${runId}/context-maintenance`
}

export async function bindRegressionContext(
  projectId: string,
  runId: string,
  input: ContextBinding,
) {
  return (await apiClient.put<ChangeRegressionRun>(root(projectId, runId), input)).data
}

export async function linkRegressionProposal(
  projectId: string,
  runId: string,
  changeSetId: string,
) {
  return (
    await apiClient.post<ChangeRegressionRun>(`${root(projectId, runId)}/proposals`, {
      change_set_id: changeSetId,
    })
  ).data
}

export async function reviewRegressionMaintenance(
  projectId: string,
  runId: string,
  input: { note: string; acknowledge_incomplete_analysis: boolean },
) {
  return (await apiClient.post<ChangeRegressionRun>(`${root(projectId, runId)}/review`, input)).data
}

export async function createRegressionMaintenance(
  projectId: string,
  runId: string,
  workflowId: string,
  input: RegressionMaintenancePatch,
  idempotencyKey: string,
) {
  return (
    await apiClient.post<ChangeRegressionRun>(
      `${root(projectId, runId)}/workflows/${workflowId}/proposals`,
      input,
      { headers: { 'Idempotency-Key': idempotencyKey } },
    )
  ).data
}
