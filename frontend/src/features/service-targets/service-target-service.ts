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
  connect_timeout_ms?: number
  read_timeout_ms?: number
  proxy_ref?: string | null
  health_check_path?: string | null
  health_expected_status?: number | null
}

export type UpdateRequestServiceInput = Partial<
  Pick<RequestService, 'name' | 'description' | 'owner_team' | 'service_type' | 'enabled'>
>

export type UpdateEndpointInput = Partial<
  Pick<
    ServiceEndpoint,
    | 'variant'
    | 'base_url'
    | 'enabled'
    | 'connect_timeout_ms'
    | 'read_timeout_ms'
    | 'tls_verify'
    | 'proxy_ref'
    | 'headers'
    | 'variables'
    | 'secret_refs'
    | 'health_check_path'
    | 'health_expected_status'
  >
>

export type EndpointConnectivity = {
  endpoint_id: string
  status: string
  dns: string
  http_status: number | null
  latency_ms: number | null
  redirect: boolean
  error_code: string | null
}

export type ServiceTargetImpactPreview = {
  strategy: string
  service_id: string
  service_key: string
  affected_apis: ImpactItem[]
  affected_workflows: ImpactItem[]
  affected_test_plans: ImpactItem[]
  affected_scheduled_runs: ImpactItem[]
  affected_release_gates: ImpactItem[]
}

type ImpactItem = { id: string; name: string; reason: string }

export async function listRequestServices(projectId: string): Promise<RequestService[]> {
  return (await apiClient.get<RequestService[]>(`/projects/${projectId}/services`)).data
}

export async function createRequestService(
  projectId: string,
  input: CreateRequestServiceInput,
): Promise<RequestService> {
  return (await apiClient.post<RequestService>(`/projects/${projectId}/services`, input)).data
}

export async function updateRequestService(
  projectId: string,
  serviceId: string,
  input: UpdateRequestServiceInput,
): Promise<RequestService> {
  return (
    await apiClient.patch<RequestService>(`/projects/${projectId}/services/${serviceId}`, input)
  ).data
}

export async function getServiceTargetImpactPreview(
  projectId: string,
  serviceId: string,
): Promise<ServiceTargetImpactPreview> {
  return (
    await apiClient.get<ServiceTargetImpactPreview>(
      `/projects/${projectId}/services/${serviceId}/impact-preview`,
    )
  ).data
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

export async function updateServiceEndpoint(
  projectId: string,
  endpointId: string,
  input: UpdateEndpointInput,
): Promise<ServiceEndpoint> {
  return (
    await apiClient.patch<ServiceEndpoint>(
      `/projects/${projectId}/service-endpoints/${endpointId}`,
      input,
    )
  ).data
}

export async function checkServiceEndpointConnectivity(
  projectId: string,
  endpointId: string,
): Promise<EndpointConnectivity> {
  return (
    await apiClient.post<EndpointConnectivity>(
      `/projects/${projectId}/service-endpoints/${endpointId}/connectivity`,
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
