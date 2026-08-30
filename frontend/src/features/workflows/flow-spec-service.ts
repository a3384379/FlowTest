import {
  apiClient,
  type FlowSpecDocument,
  type FlowSpecApplyResult,
  type FlowSpecChangeSetDetail,
  type FlowSpecChangeSetCursor,
  type FlowSpecCompatibilityResult,
  type FlowSpecDiff,
  type FlowSpecExport,
  type FlowSpecMcpProposalPage,
  type FlowSpecValidationResult,
  type FlowSpecVisualProposal,
  type ExecutionCheckpoint,
  type PreviewBudget,
  type SandboxPreviewApproval,
  type WorkflowExecution,
  type WorkflowExecutionDetail,
} from '../../lib/api'

export async function exportFlowSpec(
  projectId: string,
  workflowId: string,
  version?: number,
): Promise<FlowSpecExport> {
  const response = await apiClient.get<FlowSpecExport>(
    `/projects/${projectId}/flow-specs/workflows/${workflowId}/export`,
    { params: version === undefined ? undefined : { version } },
  )
  return response.data
}

export async function validateFlowSpec(
  projectId: string,
  spec: FlowSpecDocument,
): Promise<{
  fingerprint: string
  spec: FlowSpecDocument
  validation: FlowSpecValidationResult
  compatibility: FlowSpecCompatibilityResult
}> {
  const response = await apiClient.post(`/projects/${projectId}/flow-specs/validate`, { spec })
  return response.data
}

export async function diffFlowSpecs(
  projectId: string,
  before: FlowSpecDocument | null,
  after: FlowSpecDocument,
): Promise<FlowSpecDiff> {
  const response = await apiClient.post<FlowSpecDiff>(`/projects/${projectId}/flow-specs/diff`, {
    before,
    after,
  })
  return response.data
}

export async function importFlowSpec(
  projectId: string,
  spec: FlowSpecDocument,
  workflowId?: string,
  sourceRef?: string,
  mappings?: {
    service_mappings: Record<string, string>
    operation_mappings: Record<string, string>
    operation_version_mappings?: Record<string, number>
  },
): Promise<FlowSpecChangeSetDetail> {
  const response = await apiClient.post<FlowSpecChangeSetDetail>(
    `/projects/${projectId}/flow-specs/imports`,
    {
      spec,
      ...(workflowId ? { workflow_id: workflowId } : {}),
      ...(sourceRef ? { source_ref: sourceRef } : {}),
      ...(mappings ?? {}),
    },
  )
  return response.data
}

export async function reviewFlowSpec(
  projectId: string,
  changeSetId: string,
  accept: boolean,
  note = '',
): Promise<FlowSpecChangeSetDetail> {
  const response = await apiClient.post<FlowSpecChangeSetDetail>(
    `/projects/${projectId}/flow-specs/change-sets/${changeSetId}/review`,
    { accept, note },
  )
  return response.data
}

export async function applyFlowSpec(
  projectId: string,
  changeSetId: string,
): Promise<FlowSpecApplyResult> {
  const response = await apiClient.post<FlowSpecApplyResult>(
    `/projects/${projectId}/flow-specs/change-sets/${changeSetId}/apply`,
  )
  return response.data
}

export async function getMcpFlowProposalPage(
  projectId: string,
  cursor: FlowSpecChangeSetCursor | null,
): Promise<FlowSpecMcpProposalPage> {
  const response = await apiClient.get<FlowSpecMcpProposalPage>(
    `/projects/${projectId}/flow-specs/change-sets/mcp-proposals`,
    {
      params: {
        page_size: 100,
        cursor_created_at: cursor?.created_at,
        cursor_id: cursor?.id,
      },
    },
  )
  return response.data
}

export async function getVisualFlowProposal(
  projectId: string,
  changeSetId: string,
): Promise<FlowSpecVisualProposal> {
  const response = await apiClient.get<FlowSpecVisualProposal>(
    `/projects/${projectId}/flow-specs/change-sets/${changeSetId}/visual-proposal`,
  )
  return response.data
}

export async function createSandboxPreviewApproval(
  projectId: string,
  changeSetId: string,
  environmentId: string,
  budget?: PreviewBudget,
): Promise<SandboxPreviewApproval> {
  const response = await apiClient.post<SandboxPreviewApproval>(
    `/projects/${projectId}/flow-specs/change-sets/${changeSetId}/preview-approvals`,
    {
      environment_id: environmentId,
      ...(budget ? { budget } : {}),
    },
  )
  return response.data
}

export async function executeSandboxPreview(
  projectId: string,
  changeSetId: string,
  environmentId: string,
  approvalId: string,
): Promise<WorkflowExecution> {
  const response = await apiClient.post<{ execution: WorkflowExecution }>(
    `/projects/${projectId}/flow-specs/change-sets/${changeSetId}/preview-executions`,
    { environment_id: environmentId, approval_id: approvalId },
    { headers: { 'Idempotency-Key': crypto.randomUUID() } },
  )
  return response.data.execution
}

export async function getSandboxPreviewExecution(
  projectId: string,
  executionId: string,
): Promise<WorkflowExecutionDetail> {
  return (
    await apiClient.get<WorkflowExecutionDetail>(
      `/projects/${projectId}/workflow-executions/${executionId}`,
    )
  ).data
}

export async function listSandboxPreviewCheckpoints(
  projectId: string,
  executionId: string,
): Promise<ExecutionCheckpoint[]> {
  return (
    await apiClient.get<ExecutionCheckpoint[]>(
      `/projects/${projectId}/workflow-executions/${executionId}/checkpoints`,
    )
  ).data
}
