import {
  apiClient,
  type FailureDiagnosisResponse,
  type FlowSpecDocument,
  type RepairKind,
  type RepairProposalResponse,
} from '../../lib/api'

export async function getFailureDiagnosis(
  projectId: string,
  executionId: string,
): Promise<FailureDiagnosisResponse> {
  return (
    await apiClient.get<FailureDiagnosisResponse>(
      `/projects/${projectId}/workflow-executions/${executionId}/failure-diagnosis`,
    )
  ).data
}

export async function createRepairProposal(
  projectId: string,
  executionId: string,
  input: {
    kind: RepairKind
    proposed_spec: FlowSpecDocument
    expected_target_revision: number
    context_revision_id: string
    rationale: string
    acknowledge_oracle_weakening: boolean
  },
): Promise<RepairProposalResponse> {
  return (
    await apiClient.post<RepairProposalResponse>(
      `/projects/${projectId}/workflow-executions/${executionId}/repair-proposals`,
      input,
      { headers: { 'Idempotency-Key': crypto.randomUUID() } },
    )
  ).data
}
