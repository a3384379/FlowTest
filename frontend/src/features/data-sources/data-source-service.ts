import {
  apiClient,
  type Credential,
  type MockRequestLog,
  type MockRoute,
  type MockService,
  type Page,
} from '../../lib/api'

export type CredentialInput = {
  name: string
  kind: Credential['kind']
  host: string
  port?: number
  database_name: string
  username: string
  secret: string
  secret_provider: Credential['secret_provider']
  tls_enabled: boolean
}

export type MockRouteInput = Omit<
  MockRoute,
  'id' | 'mock_service_id' | 'created_by_id' | 'created_at' | 'updated_at'
>

export async function listCredentials(projectId: string): Promise<Credential[]> {
  const response = await apiClient.get<Credential[]>('/credentials', {
    params: { project_id: projectId },
  })
  return response.data
}

export async function createCredential(
  projectId: string,
  input: CredentialInput,
): Promise<Credential> {
  const response = await apiClient.post<Credential>('/credentials', {
    project_id: projectId,
    ...input,
  })
  return response.data
}

export async function deleteCredential(credentialId: string): Promise<void> {
  await apiClient.delete(`/credentials/${credentialId}`)
}

export async function listMockServices(projectId: string): Promise<MockService[]> {
  const response = await apiClient.get<MockService[]>(`/projects/${projectId}/mock-services`)
  return response.data
}

export async function createMockService(
  projectId: string,
  input: { name: string; slug: string; description: string },
): Promise<MockService> {
  const response = await apiClient.post<MockService>(`/projects/${projectId}/mock-services`, input)
  return response.data
}

export async function updateMockService(
  projectId: string,
  serviceId: string,
  input: { is_enabled: boolean },
): Promise<MockService> {
  const response = await apiClient.patch<MockService>(
    `/projects/${projectId}/mock-services/${serviceId}`,
    input,
  )
  return response.data
}

export async function listMockRoutes(projectId: string, serviceId: string): Promise<MockRoute[]> {
  const response = await apiClient.get<MockRoute[]>(
    `/projects/${projectId}/mock-services/${serviceId}/routes`,
  )
  return response.data
}

export async function createMockRoute(
  projectId: string,
  serviceId: string,
  input: MockRouteInput,
): Promise<MockRoute> {
  const response = await apiClient.post<MockRoute>(
    `/projects/${projectId}/mock-services/${serviceId}/routes`,
    input,
  )
  return response.data
}

export async function deleteMockRoute(
  projectId: string,
  serviceId: string,
  routeId: string,
): Promise<void> {
  await apiClient.delete(`/projects/${projectId}/mock-services/${serviceId}/routes/${routeId}`)
}

export async function listMockLogs(
  projectId: string,
  serviceId: string,
): Promise<Page<MockRequestLog>> {
  const response = await apiClient.get<Page<MockRequestLog>>(
    `/projects/${projectId}/mock-services/${serviceId}/request-logs`,
    { params: { page: 1, page_size: 50 } },
  )
  return response.data
}
