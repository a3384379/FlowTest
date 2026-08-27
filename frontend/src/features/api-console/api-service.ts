import {
  apiClient,
  type Artifact,
  type ApiDefinition,
  type ApiDetail,
  type ApiVersion,
  type Environment,
  type ExecutionDetail,
  type ImportRun,
  type Page,
  type Project,
} from '../../lib/api'

export { createProject } from '../projects/project-service'
export type { CreateProjectInput } from '../projects/project-service'

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
export type BodyKind = 'none' | 'json' | 'raw' | 'form' | 'multipart'
export type AuthKind = 'none' | 'bearer' | 'basic' | 'api_key'
export type ImportSourceType =
  'auto' | 'openapi3' | 'swagger2' | 'postman' | 'har' | 'curl' | 'bruno' | 'excel'
export type ImportPreviewInput =
  | { kind: 'file'; file: File; sourceType: ImportSourceType }
  | { kind: 'url'; url: string; sourceType: ImportSourceType; documentId?: string }

export type ImportUrlDocument = {
  id: string
  name: string
  url: string
}

export type ImportUrlDiscovery = {
  source_url: string
  source_kind: 'document' | 'swagger_ui'
  documents: ImportUrlDocument[]
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

export type ApiVersionInput = Pick<
  ApiVersion,
  | 'method'
  | 'path'
  | 'query_parameters'
  | 'headers'
  | 'body_kind'
  | 'body'
  | 'extraction_rules'
  | 'assertions'
> & {
  auth: { kind: ApiVersion['auth_kind']; values: Record<string, string> }
}

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

export async function createEnvironment(
  projectId: string,
  input: CreateEnvironmentInput,
): Promise<Environment> {
  const response = await apiClient.post<Environment>(`/projects/${projectId}/environments`, input)
  return response.data
}

export async function listApis(
  projectId: string,
  options: { page?: number; pageSize?: number; search?: string; method?: HttpMethod } = {},
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

export async function getApiDetail(
  projectId: string,
  apiId: string,
  version?: number,
): Promise<ApiDetail> {
  return (
    await apiClient.get<ApiDetail>(`/projects/${projectId}/apis/${apiId}`, {
      params: version ? { version } : undefined,
    })
  ).data
}

export async function updateApiDefinition(
  projectId: string,
  apiId: string,
  input: { name?: string; service_id?: string | null },
): Promise<ApiDefinition> {
  const response = await apiClient.patch<ApiDefinition>(
    `/projects/${projectId}/apis/${apiId}`,
    input,
  )
  return response.data
}

export async function createApiVersion(
  projectId: string,
  apiId: string,
  input: ApiVersionInput,
): Promise<ApiVersion> {
  return (await apiClient.post<ApiVersion>(`/projects/${projectId}/apis/${apiId}/versions`, input))
    .data
}

export async function previewApi(
  projectId: string,
  apiId: string,
  environmentId: string,
  options: {
    version?: number
    queryParametersOverride?: ApiVersion['query_parameters']
    headersOverride?: Record<string, string>
    serviceOverride?: string
    endpointVariant?: string
    bodyOverride?: unknown
    useBodyOverride?: boolean
  } = {},
): Promise<{
  method: string
  url: string
  headers: Array<{ name: string; value: string; source: string }>
  body: unknown
  target?: Record<string, unknown>
}> {
  return (
    await apiClient.post(`/projects/${projectId}/apis/${apiId}/preview`, {
      environment_id: environmentId,
      runtime_variables: {},
      runtime_headers: {},
      ...(options.serviceOverride ? { service_override: options.serviceOverride } : {}),
      ...(options.endpointVariant ? { endpoint_variant: options.endpointVariant } : {}),
      ...(options.version ? { version: options.version } : {}),
      ...(options.queryParametersOverride !== undefined
        ? { query_parameters_override: options.queryParametersOverride }
        : {}),
      ...(options.headersOverride !== undefined
        ? { headers_override: options.headersOverride }
        : {}),
      ...(options.useBodyOverride !== undefined
        ? {
            body_override: options.bodyOverride,
            use_body_override: options.useBodyOverride,
          }
        : {}),
    })
  ).data
}

export async function exportApis(
  projectId: string,
  exportFormat: 'har' | 'curl' | 'bruno' | 'excel',
): Promise<void> {
  const response = await apiClient.get<Blob>(`/projects/${projectId}/exports/apis`, {
    params: { format: exportFormat },
    responseType: 'blob',
  })
  const disposition = String(response.headers['content-disposition'] ?? '')
  const filename = disposition.match(/filename="([^"]+)"/)?.[1] ?? `flowtest.${exportFormat}`
  const url = URL.createObjectURL(response.data)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

export async function previewApiDocument(
  projectId: string,
  file: File,
  sourceType: ImportSourceType = 'auto',
): Promise<ImportRun> {
  const form = new FormData()
  form.append('document', file)
  form.append('source_type', sourceType)
  const response = await apiClient.post<ImportRun>(`/projects/${projectId}/imports/preview`, form)
  return response.data
}

export async function previewApiDocumentUrl(
  projectId: string,
  url: string,
  sourceType: ImportSourceType = 'auto',
  documentId?: string,
): Promise<ImportRun> {
  const response = await apiClient.post<ImportRun>(`/projects/${projectId}/imports/url/preview`, {
    url,
    source_type: sourceType,
    ...(documentId ? { document_id: documentId } : {}),
  })
  return response.data
}

export async function discoverApiDocumentUrl(
  projectId: string,
  url: string,
): Promise<ImportUrlDiscovery> {
  const response = await apiClient.post<ImportUrlDiscovery>(
    `/projects/${projectId}/imports/url/discover`,
    { url },
  )
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
  assertions?: ApiVersion['assertions'],
): Promise<ExecutionDetail> {
  const response = await apiClient.post<ExecutionDetail>(
    `/projects/${projectId}/apis/${apiId}/execute`,
    {
      environment_id: environmentId,
      assertions: assertions?.length
        ? assertions
        : [
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
