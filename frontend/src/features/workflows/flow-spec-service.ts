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
