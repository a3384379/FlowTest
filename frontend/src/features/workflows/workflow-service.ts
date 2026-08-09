import {
  apiClient,
  type ApiDefinition,
  type Artifact,
  type Environment,
  type Page,
  type Project,
  type Workflow,
  type WorkflowDefinition,
  type WorkflowDebugResult,
  type WorkflowExecution,
  type WorkflowExecutionDetail,
  type WorkflowVersion,
  type WorkflowVersionDiff,
} from '../../lib/api'

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

export async function listApis(projectId: string): Promise<Page<ApiDefinition>> {
  const response = await apiClient.get<Page<ApiDefinition>>(`/projects/${projectId}/apis`, {
    params: { page: 1, page_size: 100 },
  })
  return response.data
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

export async function createWorkflow(
  projectId: string,
  input: { name: string; description: string; apiId: string },
): Promise<Workflow> {
  const response = await apiClient.post<Workflow>(`/projects/${projectId}/workflows`, {
    name: input.name,
    description: input.description,
    definition: linearWorkflow(input.apiId),
  })
  return response.data
}

export async function updateWorkflowDraft(
  projectId: string,
  workflow: Workflow,
  definition: WorkflowDefinition,
): Promise<Workflow> {
  const response = await apiClient.patch<Workflow>(
    `/projects/${projectId}/workflows/${workflow.id}`,
    { expected_revision: workflow.draft_revision, definition },
  )
  return response.data
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

export async function executeWorkflow(
  projectId: string,
  workflowId: string,
  environmentId: string,
): Promise<WorkflowExecution> {
  const response = await apiClient.post<WorkflowExecution>(
    `/projects/${projectId}/workflows/${workflowId}/executions`,
    { environment_id: environmentId },
    { headers: { 'Idempotency-Key': crypto.randomUUID() } },
  )
  return response.data
}

export async function getWorkflowExecution(
  projectId: string,
  executionId: string,
): Promise<WorkflowExecutionDetail> {
  const response = await apiClient.get<WorkflowExecutionDetail>(
    `/projects/${projectId}/workflow-executions/${executionId}`,
  )
  return response.data
}

export async function listWorkflowExecutions(projectId: string): Promise<Page<WorkflowExecution>> {
  const response = await apiClient.get<Page<WorkflowExecution>>(
    `/projects/${projectId}/workflow-executions`,
    { params: { page: 1, page_size: 20 } },
  )
  return response.data
}

export function linearWorkflow(apiId: string): WorkflowDefinition {
  return {
    schema_version: '1.0',
    variables: {},
    nodes: [
      { id: 'start', type: 'start', name: '开始', position: { x: 0, y: 80 }, config: {} },
      {
        id: 'api',
        type: 'api',
        name: '接口请求',
        position: { x: 220, y: 80 },
        config: {
          api_definition_id: apiId,
          max_retries: 0,
          retry_on: ['network_error', '5xx'],
        },
      },
      { id: 'end', type: 'end', name: '结束', position: { x: 440, y: 80 }, config: {} },
    ],
    edges: [
      { id: 'start-api', source: 'start', target: 'api', condition: null, mappings: [] },
      { id: 'api-end', source: 'api', target: 'end', condition: null, mappings: [] },
    ],
    settings: { fail_fast: true, concurrency: 20, default_timeout_seconds: 30 },
  }
}
