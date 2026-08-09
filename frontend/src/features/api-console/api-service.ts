import {
  apiClient,
  type Artifact,
  type ApiDefinition,
  type Environment,
  type ExecutionDetail,
  type ImportRun,
  type Page,
  type Project,
} from '../../lib/api'

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
export type BodyKind = 'none' | 'json' | 'multipart'
export type AuthKind = 'none' | 'bearer' | 'basic' | 'api_key'

export type CreateProjectInput = {
  name: string
  description: string
}

export type CreateEnvironmentInput = {
  name: string
  base_url: string
  variables: Record<string, string>
  headers: Record<string, string>
}

export type CreateApiInput = {
  name: string
  description: string
  method: HttpMethod
  path: string
  body: unknown
  body_kind?: BodyKind
  auth?: { kind: AuthKind; values: Record<string, string> }
}

export async function listProjects(): Promise<Page<Project>> {
  const response = await apiClient.get<Page<Project>>('/projects', {
    params: { page: 1, page_size: 100 },
  })
  return response.data
}

export async function createProject(input: CreateProjectInput): Promise<Project> {
  const response = await apiClient.post<Project>('/projects', input)
  return response.data
}

export async function listEnvironments(projectId: string): Promise<Environment[]> {
  const response = await apiClient.get<Environment[]>(`/projects/${projectId}/environments`)
  return response.data
}

export async function createEnvironment(
  projectId: string,
  input: CreateEnvironmentInput,
): Promise<Environment> {
  const response = await apiClient.post<Environment>(`/projects/${projectId}/environments`, input)
  return response.data
}

export async function listApis(projectId: string): Promise<Page<ApiDefinition>> {
  const response = await apiClient.get<Page<ApiDefinition>>(`/projects/${projectId}/apis`, {
    params: { page: 1, page_size: 100 },
  })
  return response.data
}

export async function createApi(projectId: string, input: CreateApiInput) {
  const bodyKind = input.body_kind ?? (input.body === null ? 'none' : 'json')
  const response = await apiClient.post<{ definition: ApiDefinition }>(
    `/projects/${projectId}/apis`,
    {
      name: input.name,
      description: input.description,
      folder_id: null,
      request: {
        method: input.method,
        path: input.path,
        query_parameters: [],
        headers: {},
        body_kind: bodyKind,
        body: input.body,
        auth: input.auth ?? { kind: 'none', values: {} },
      },
    },
  )
  return response.data.definition
}

export async function previewApiDocument(
  projectId: string,
  file: File,
  sourceType: 'auto' | 'openapi3' | 'swagger2' | 'postman' = 'auto',
): Promise<ImportRun> {
  const form = new FormData()
  form.append('document', file)
  form.append('source_type', sourceType)
  const response = await apiClient.post<ImportRun>(`/projects/${projectId}/imports/preview`, form)
  return response.data
}

export async function mergeApiImport(
  projectId: string,
  runId: string,
  selectedKeys: string[],
): Promise<ImportRun> {
  const response = await apiClient.post<ImportRun>(
    `/projects/${projectId}/imports/${runId}/merge`,
    { selected_keys: selectedKeys },
  )
  return response.data
}

export async function listArtifacts(projectId: string): Promise<Page<Artifact>> {
  const response = await apiClient.get<Page<Artifact>>(`/projects/${projectId}/files`, {
    params: { page: 1, page_size: 100 },
  })
  return response.data
}

export async function uploadArtifact(projectId: string, file: File): Promise<Artifact> {
  const form = new FormData()
  form.append('file', file)
  const response = await apiClient.post<Artifact>(`/projects/${projectId}/files`, form)
  return response.data
}

export async function downloadArtifact(projectId: string, artifact: Artifact): Promise<void> {
  const response = await apiClient.get<Blob>(`/projects/${projectId}/files/${artifact.id}`, {
    responseType: 'blob',
  })
  const url = URL.createObjectURL(response.data)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = artifact.filename
  anchor.click()
  URL.revokeObjectURL(url)
}

export async function executeApi(
  projectId: string,
  apiId: string,
  environmentId: string,
  expectedStatus: number,
): Promise<ExecutionDetail> {
  const response = await apiClient.post<ExecutionDetail>(
    `/projects/${projectId}/apis/${apiId}/execute`,
    {
      environment_id: environmentId,
      assertions: [
        {
          kind: 'status_code',
          operator: 'equals',
          expected: expectedStatus,
        },
      ],
    },
    { headers: { 'Idempotency-Key': crypto.randomUUID() } },
  )
  return response.data
}

export async function listExecutions(projectId: string) {
  const response = await apiClient.get<Page<ExecutionDetail['execution']>>(
    `/projects/${projectId}/executions`,
    { params: { page: 1, page_size: 20 } },
  )
  return response.data
}
