import {
  apiClient,
  type ApiDetail,
  type ApiDefinition,
  type Artifact,
  type Environment,
  type ExecutionCheckpoint,
  type Page,
  type Project,
  type Workflow,
  type WorkflowDefinition,
  type WorkflowDebugResult,
  type WorkflowExecution,
  type WorkflowExecutionDetail,
  type WorkflowControlRecordDetail,
  type WorkflowControlRecordSummary,
  type WorkflowVersion,
  type WorkflowVersionDiff,
} from '../../lib/api'
import { buildWorkflowTemplate, type WorkflowTemplateKind } from './workflow-templates'
import { getApiDetail } from '../api-console/api-service'

export async function listProjects(): Promise<Page<Project>> {
  const response = await apiClient.get<Page<Project>>('/projects', {
    params: { page: 1, page_size: 100 },
  })
  return response.data
}

export async function listEnvironments(projectId: string): Promise<Environment[]> {
  const response = await apiClient.get<Environment[]>(`/projects/${projectId}/environments`)
  return response.data
}

export async function listApis(
  projectId: string,
  options: { page?: number; pageSize?: number; search?: string; method?: ApiMethod } = {},
): Promise<Page<ApiDefinition>> {
  const response = await apiClient.get<Page<ApiDefinition>>(`/projects/${projectId}/apis`, {
    params: {
      page: options.page ?? 1,
      page_size: options.pageSize ?? 50,
      ...(options.search?.trim() ? { search: options.search.trim() } : {}),
      ...(options.method ? { method: options.method } : {}),
    },
  })
  return response.data
}

type ApiMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

export type NativeWorkflowDocument = {
  format_version: 'flowtest-workflow-native-v1'
  name: string
  description: string
  definition: WorkflowDefinition
}

export async function listArtifacts(projectId: string): Promise<Page<Artifact>> {
  const response = await apiClient.get<Page<Artifact>>(`/projects/${projectId}/files`, {
    params: { page: 1, page_size: 100 },
  })
  return response.data
}

export async function listWorkflows(projectId: string): Promise<Page<Workflow>> {
  const response = await apiClient.get<Page<Workflow>>(`/projects/${projectId}/workflows`, {
    params: { page: 1, page_size: 100 },
  })
  return response.data
}

export async function getWorkflow(projectId: string, workflowId: string): Promise<Workflow> {
  const response = await apiClient.get<Workflow>(`/projects/${projectId}/workflows/${workflowId}`)
  return response.data
}

export async function createWorkflow(
  projectId: string,
  input: {
    name: string
    description: string
    apiId: string
    apiVersion?: number
    submitApiId?: string
    submitApiVersion?: number
    template?: WorkflowTemplateKind
  },
): Promise<Workflow> {
  const pollingApis =
    input.template === 'async_poll' ? await validatePollingApis(projectId, input) : null
  const response = await apiClient.post<Workflow>(`/projects/${projectId}/workflows`, {
    name: input.name,
    description: input.description,
    definition: buildWorkflowTemplate(
      linearWorkflow(input.apiId, pollingApis?.poll.version.version ?? input.apiVersion),
      input.template,
      pollingApis
        ? {
            submitApiId: pollingApis.submit.definition.id,
            submitApiVersion: pollingApis.submit.version.version,
          }
        : {},
    ),
  })
  return response.data
}

async function validatePollingApis(
  projectId: string,
  input: {
    apiId: string
    apiVersion?: number
    submitApiId?: string
    submitApiVersion?: number
  },
): Promise<{ submit: ApiDetail; poll: ApiDetail }> {
  if (!input.submitApiId || input.submitApiId === input.apiId) {
    throw new Error('异步轮询模板需要分别选择提交接口和状态查询接口')
  }
  const [submit, poll] = await Promise.all([
    getApiDetail(projectId, input.submitApiId, input.submitApiVersion),
    getApiDetail(projectId, input.apiId, input.apiVersion),
  ])
  if (submit.version.method !== 'POST') throw new Error('提交任务接口必须使用 POST 方法')
  if (poll.version.method !== 'GET') throw new Error('状态轮询接口必须使用只读 GET 方法')
  return { submit, poll }
}

export async function exportNativeWorkflow(
  projectId: string,
  workflowId: string,
): Promise<NativeWorkflowDocument> {
  const response = await apiClient.get<NativeWorkflowDocument>(
    `/projects/${projectId}/workflows/${workflowId}/native-export`,
  )
  return response.data
}

export async function importNativeWorkflow(
  projectId: string,
  document: NativeWorkflowDocument,
): Promise<Workflow> {
  const response = await apiClient.post<Workflow>(
    `/projects/${projectId}/workflows/native-import`,
    document,
  )
  return response.data
}

export async function updateWorkflowDraft(
  projectId: string,
  workflow: Workflow,
  definition: WorkflowDefinition,
  expectedRevision = workflow.draft_revision,
): Promise<Workflow> {
  const response = await apiClient.patch<Workflow>(
    `/projects/${projectId}/workflows/${workflow.id}`,
    { expected_revision: expectedRevision, definition },
  )
  return response.data
}

export async function deleteWorkflow(projectId: string, workflowId: string): Promise<void> {
  await apiClient.delete(`/projects/${projectId}/workflows/${workflowId}`)
}

export async function publishWorkflow(
  projectId: string,
  workflowId: string,
): Promise<WorkflowVersion> {
  const response = await apiClient.post<WorkflowVersion>(
    `/projects/${projectId}/workflows/${workflowId}/versions`,
  )
  return response.data
}

export async function diffWorkflowVersions(
  projectId: string,
  workflowId: string,
  fromVersion: number,
  toVersion: number,
): Promise<WorkflowVersionDiff> {
  const response = await apiClient.get<WorkflowVersionDiff>(
    `/projects/${projectId}/workflows/${workflowId}/versions/${fromVersion}/diff/${toVersion}`,
  )
  return response.data
}

export async function debugWorkflow(
  projectId: string,
  workflowId: string,
  environmentId: string,
  version: number,
  breakpointNodeId: string,
): Promise<WorkflowDebugResult> {
  const response = await apiClient.post<WorkflowDebugResult>(
    `/projects/${projectId}/workflows/${workflowId}/debug`,
    {
      environment_id: environmentId,
      version,
      breakpoint_node_id: breakpointNodeId,
    },
  )
  return response.data
}

export async function replayWorkflowNode(
  projectId: string,
  executionId: string,
  nodeId: string,
): Promise<WorkflowDebugResult> {
  const response = await apiClient.post<WorkflowDebugResult>(
    `/projects/${projectId}/workflow-executions/${executionId}/nodes/${nodeId}/replay`,
  )
  return response.data
}

export type FailedItemRerunRequest = {
  loop_node_id: string
  input_indices: number[]
  upstream_resource_status: 'unverified' | 'confirmed_valid' | 'expired'
  write_retry_strategy: 'reject' | 'verified_safe_to_retry'
  verification_note?: string
}

export async function rerunFailedWorkflowItems(
  projectId: string,
  executionId: string,
  payload: FailedItemRerunRequest,
): Promise<WorkflowExecution> {
  const response = await apiClient.post<WorkflowExecution>(
    `/projects/${projectId}/workflow-executions/${executionId}/failed-items/rerun`,
    payload,
    { headers: { 'Idempotency-Key': crypto.randomUUID() } },
  )
  return response.data
}

export async function executeWorkflow(
  projectId: string,
  workflowId: string,
  environmentId: string,
  version?: number,
): Promise<WorkflowExecution> {
  const response = await apiClient.post<WorkflowExecution>(
    `/projects/${projectId}/workflows/${workflowId}/executions`,
    { environment_id: environmentId, ...(version === undefined ? {} : { version }) },
    { headers: { 'Idempotency-Key': crypto.randomUUID() } },
  )
  return response.data
}

export async function getWorkflowExecution(
  projectId: string,
  executionId: string,
  compactControl = false,
): Promise<WorkflowExecutionDetail> {
  const response = await apiClient.get<WorkflowExecutionDetail>(
    `/projects/${projectId}/workflow-executions/${executionId}`,
    { params: { compact_control: compactControl } },
  )
  return response.data
}

export async function downloadWorkflowOutput(projectId: string, artifactId: string): Promise<void> {
  const response = await apiClient.get<ArrayBuffer>(`/projects/${projectId}/files/${artifactId}`, {
    responseType: 'arraybuffer',
  })
  const url = URL.createObjectURL(new Blob([response.data], { type: 'application/json' }))
  try {
    const link = document.createElement('a')
    link.href = url
    link.download = `workflow-output-${artifactId}.json`
    link.click()
  } finally {
    URL.revokeObjectURL(url)
  }
}

export async function listWorkflowControlRecords(
  projectId: string,
  executionId: string,
  nodeId: string,
  kind: 'iteration' | 'branch',
  page: number,
  testVerdict?: 'failed',
): Promise<Page<WorkflowControlRecordSummary>> {
  const response = await apiClient.get<Page<WorkflowControlRecordSummary>>(
    `/projects/${projectId}/workflow-executions/${executionId}/control-records`,
    {
      params: {
        node_id: nodeId,
        kind,
        page,
        page_size: 20,
        ...(testVerdict ? { test_verdict: testVerdict } : {}),
      },
    },
  )
  return response.data
}

export async function getWorkflowControlRecord(
  projectId: string,
  executionId: string,
  nodeId: string,
  kind: 'iteration' | 'branch',
  ordinal: number,
): Promise<WorkflowControlRecordDetail> {
  const response = await apiClient.get<WorkflowControlRecordDetail>(
    `/projects/${projectId}/workflow-executions/${executionId}/control-records/${kind}/${ordinal}`,
    { params: { node_id: nodeId } },
  )
  return response.data
}

export async function getWorkflowInstance(
  projectId: string,
  executionId: string,
  instanceId: string,
): Promise<ExecutionCheckpoint> {
  const response = await apiClient.get<ExecutionCheckpoint>(
    `/projects/${projectId}/workflow-executions/${executionId}/instances/${encodeURIComponent(instanceId)}`,
  )
  return response.data
}

export async function listWorkflowExecutions(
  projectId: string,
  workflowId?: string,
): Promise<Page<WorkflowExecution>> {
  const response = await apiClient.get<Page<WorkflowExecution>>(
    `/projects/${projectId}/workflow-executions`,
    { params: { workflow_id: workflowId, page: 1, page_size: 20 } },
  )
  return response.data
}

export function linearWorkflow(apiId: string, apiVersion?: number): WorkflowDefinition {
  return {
    schema_version: '1.0',
    variables: {},
    nodes: [
      { id: 'start', type: 'start', name: '开始', position: { x: 0, y: 80 }, config: {} },
      {
        id: 'api',
        type: 'api',
        name: '接口请求',
        position: { x: 320, y: 80 },
        config: {
          api_definition_id: apiId,
          ...(apiVersion ? { api_version: apiVersion } : {}),
          request_overrides: {},
          max_retries: 0,
          retry_on: ['network_error', '5xx'],
        },
      },
      { id: 'end', type: 'end', name: '结束', position: { x: 640, y: 80 }, config: {} },
    ],
    edges: [
      { id: 'start-api', source: 'start', target: 'api', condition: null, mappings: [] },
      { id: 'api-end', source: 'api', target: 'end', condition: null, mappings: [] },
    ],
    settings: { fail_fast: true, concurrency: 20, default_timeout_seconds: 30 },
  }
}
