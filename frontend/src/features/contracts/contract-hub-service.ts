import { apiClient, type Page } from '../../lib/api'

export type ServiceCatalogEntry = {
  id: string
  project_id: string
  service_key: string
  display_name: string
  description: string
  created_by_id: string
  created_at: string
  updated_at: string
}

export type PactContract = {
  id: string
  project_id: string
  consumer_service_id: string
  consumer_name: string
  provider_service_id: string
  provider_name: string
  consumer_version: string
  pact_specification_version: string
  source_type: 'upload' | 'broker'
  source_name: string
  content_sha256: string
  interaction_count: number
  created_by_id: string
  created_at: string
}

export type ProviderVerification = {
  id: string
  project_id: string
  pact_contract_version_id: string
  provider_version: string
  target_base_url: string
  status: 'passed' | 'failed'
  interaction_count: number
  passed_count: number
  failed_count: number
  results: Array<Record<string, unknown>>
  verified_by_id: string
  created_at: string
}

export type ContractHubSummary = {
  service_count: number
  openapi_contract_count: number
  pact_contract_count: number
  pending_verification_count: number
  failed_verification_count: number
  breaking_change_count: number
  broker_available: boolean
}

export type ServiceGraph = {
  nodes: Array<{
    id: string
    service_key: string
    display_name: string
    contract_kinds: Array<'openapi' | 'pact'>
  }>
  edges: Array<{
    consumer_service_id: string
    provider_service_id: string
    pact_contract_count: number
    latest_consumer_version: string
    latest_status: 'passed' | 'failed' | 'pending'
  }>
}

export type CompatibilityMatrix = {
  provider_service_id: string
  provider_name: string
  provider_versions: string[]
  rows: Array<{
    pact_contract_version_id: string
    consumer_service_id: string
    consumer_name: string
    consumer_version: string
    cells: Array<{
      provider_version: string
      status: 'passed' | 'failed' | 'pending'
      verification_id: string | null
      verified_at: string | null
    }>
  }>
}

export type DeploymentCheck = {
  id: string
  project_id: string
  provider_service_id: string
  provider_version: string
  decision: 'safe' | 'unsafe' | 'unknown'
  evidence: Record<string, unknown>
  checked_by_id: string
  created_at: string
}

export type PactImportInput =
  | { kind: 'upload'; document: File; consumerVersion: string }
  | { kind: 'broker'; consumer: string; provider: string; consumerVersion: string }

export async function listContractServices(projectId: string) {
  return (
    await apiClient.get<Page<ServiceCatalogEntry>>(`/projects/${projectId}/contract-hub/services`, {
      params: { page: 1, page_size: 100 },
    })
  ).data
}

export async function createContractService(
  projectId: string,
  input: { service_key: string; display_name: string; description: string },
) {
  return (
    await apiClient.post<ServiceCatalogEntry>(`/projects/${projectId}/contract-hub/services`, input)
  ).data
}

export async function listPactContracts(projectId: string) {
  return (
    await apiClient.get<Page<PactContract>>(`/projects/${projectId}/contract-hub/pacts`, {
      params: { page: 1, page_size: 100 },
    })
  ).data
}

export async function importPactContract(projectId: string, input: PactImportInput) {
  if (input.kind === 'broker') {
    return (
      await apiClient.post<PactContract>(
        `/projects/${projectId}/contract-hub/pacts/import-broker`,
        {
          consumer: input.consumer,
          provider: input.provider,
          consumer_version: input.consumerVersion,
        },
      )
    ).data
  }
  const form = new FormData()
  form.append('document', input.document)
  form.append('consumer_version', input.consumerVersion)
  form.append('source_name', input.document.name)
  return (await apiClient.post<PactContract>(`/projects/${projectId}/contract-hub/pacts`, form))
    .data
}

export async function verifyPactProvider(
  projectId: string,
  input: { pactId: string; providerVersion: string; targetBaseUrl: string },
) {
  return (
    await apiClient.post<ProviderVerification>(
      `/projects/${projectId}/contract-hub/pacts/${input.pactId}/verify`,
      {
        provider_version: input.providerVersion,
        target_base_url: input.targetBaseUrl,
      },
    )
  ).data
}

export async function getContractHubSummary(projectId: string) {
  return (await apiClient.get<ContractHubSummary>(`/projects/${projectId}/contract-hub/summary`))
    .data
}

export async function getServiceGraph(projectId: string) {
  return (await apiClient.get<ServiceGraph>(`/projects/${projectId}/contract-hub/service-graph`))
    .data
}

export async function getCompatibilityMatrix(projectId: string, providerServiceId: string) {
  return (
    await apiClient.get<CompatibilityMatrix>(
      `/projects/${projectId}/contract-hub/compatibility/${providerServiceId}`,
    )
  ).data
}

export async function runDeploymentCheck(
  projectId: string,
  input: { providerServiceId: string; providerVersion: string },
) {
  return (
    await apiClient.post<DeploymentCheck>(`/projects/${projectId}/contract-hub/deployment-checks`, {
      provider_service_id: input.providerServiceId,
      provider_version: input.providerVersion,
    })
  ).data
}

export async function listDeploymentChecks(projectId: string) {
  return (
    await apiClient.get<Page<DeploymentCheck>>(
      `/projects/${projectId}/contract-hub/deployment-checks`,
      { params: { page: 1, page_size: 50 } },
    )
  ).data
}
