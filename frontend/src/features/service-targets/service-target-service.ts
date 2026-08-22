import {
  apiClient,
  type Environment,
  type RequestService,
  type ServiceEndpoint,
} from '../../lib/api'

export type CreateRequestServiceInput = {
  service_key: string
  name: string
  description?: string
  owner_team?: string
  service_type?: RequestService['service_type']
}

export type CreateEndpointInput = {
  service_id: string
  variant?: string
  base_url: string
  headers?: Record<string, string>
  variables?: Record<string, string>
  secret_refs?: string[]
  enabled?: boolean
  tls_verify?: boolean
}

export async function listRequestServices(projectId: string): Promise<RequestService[]> {
  return (await apiClient.get<RequestService[]>(`/projects/${projectId}/services`)).data
}

export async function createRequestService(
  projectId: string,
  input: CreateRequestServiceInput,
): Promise<RequestService> {
  return (await apiClient.post<RequestService>(`/projects/${projectId}/services`, input)).data
}

export async function listServiceEndpoints(
  projectId: string,
  environmentId: string,
): Promise<ServiceEndpoint[]> {
  return (
    await apiClient.get<ServiceEndpoint[]>(
      `/projects/${projectId}/environments/${environmentId}/service-endpoints`,
    )
  ).data
}

export async function createServiceEndpoint(
  projectId: string,
  environmentId: string,
  input: CreateEndpointInput,
): Promise<ServiceEndpoint> {
  return (
    await apiClient.post<ServiceEndpoint>(
      `/projects/${projectId}/environments/${environmentId}/service-endpoints`,
      input,
    )
  ).data
}

export async function setEnvironmentDefaultService(
  projectId: string,
  environment: Environment,
  serviceId: string | null,
): Promise<Environment> {
  return (
    await apiClient.patch<Environment>(`/projects/${projectId}/environments/${environment.id}`, {
      default_service_id: serviceId,
    })
  ).data
}
