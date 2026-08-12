import { apiClient, type Page } from '../../lib/api'

export type EnvironmentHealthCheck = {
  kind: 'http' | 'tcp'
  path: string | null
  expected_status: number
  interval_seconds: number
  timeout_seconds: number
  maximum_attempts: number
}

export type EnvironmentServiceDefinition = {
  name: string
  image: string
  internal_port: number
  environment: Array<{ name: string; value: string }>
  depends_on: string[]
  health_check: EnvironmentHealthCheck
  cpu_millicores: number
  memory_megabytes: number
  pids_limit: number
  user_id: number
  group_id: number
  read_only_root_filesystem: true
  drop_all_capabilities: true
  no_new_privileges: true
}

export type EnvironmentTemplateManifest = {
  services: EnvironmentServiceDefinition[]
  seeds: Array<{ profile: 'http_get_v1'; service: string; path: string }>
  default_ttl_seconds: number
  maximum_ttl_seconds: number
}

export type EnvironmentTemplateVersion = {
  id: string
  template_id: string
  template_key: string
  display_name: string
  description: string
  status: 'active' | 'disabled'
  version: number
  manifest: EnvironmentTemplateManifest
  manifest_sha256: string
  signature: string
  signature_algorithm: string
  signed_by_id: string
  created_at: string
}

export type EnvironmentEndpoint = {
  service: string
  url: string
  internal_port: number
}

export type EnvironmentInstance = {
  id: string
  project_id: string
  template_version_id: string
  template_key: string
  template_version: number
  status: 'queued' | 'provisioning' | 'ready' | 'failed' | 'cancelled' | 'expired' | 'cleaned'
  cleanup_status: 'none' | 'pending' | 'running' | 'completed' | 'failed'
  runtime_name: string
  ttl_seconds: number
  fencing_token: number
  endpoints: EnvironmentEndpoint[]
  seed_evidence: Array<{
    profile: 'http_get_v1'
    service: string
    path: string
    status_code: number
  }>
  error_code: string | null
  error_message: string | null
  cleanup_error_code: string | null
  cleanup_attempts: number
  queued_at: string
  started_at: string | null
  ready_at: string | null
  expires_at: string
  cancellation_requested_at: string | null
  cleanup_started_at: string | null
  cleaned_at: string | null
  created_by_id: string
  created_at: string
  updated_at: string
}

export type EnvironmentTemplateInput = {
  template_key: string
  display_name: string
  description: string
  manifest: EnvironmentTemplateManifest
}

export async function listEnvironmentTemplates(): Promise<Page<EnvironmentTemplateVersion>> {
  return (
    await apiClient.get<Page<EnvironmentTemplateVersion>>('/environment-templates', {
      params: { page: 1, page_size: 100 },
    })
  ).data
}

export async function registerEnvironmentTemplate(
  input: EnvironmentTemplateInput,
): Promise<EnvironmentTemplateVersion> {
  return (await apiClient.post<EnvironmentTemplateVersion>('/environment-templates', input)).data
}

export async function createEnvironmentTemplateVersion(
  templateId: string,
  manifest: EnvironmentTemplateManifest,
): Promise<EnvironmentTemplateVersion> {
  return (
    await apiClient.post<EnvironmentTemplateVersion>(
      `/environment-templates/${templateId}/versions`,
      { manifest },
    )
  ).data
}

export async function disableEnvironmentTemplate(templateId: string): Promise<void> {
  await apiClient.post(`/environment-templates/${templateId}/disable`)
}

export async function listEnvironmentInstances(
  projectId: string,
): Promise<Page<EnvironmentInstance>> {
  return (
    await apiClient.get<Page<EnvironmentInstance>>(`/projects/${projectId}/environment-instances`, {
      params: { page: 1, page_size: 100 },
    })
  ).data
}

export async function provisionEnvironment(
  projectId: string,
  templateVersionId: string,
  ttlSeconds: number,
  idempotencyKey: string,
): Promise<EnvironmentInstance> {
  return (
    await apiClient.post<EnvironmentInstance>(
      `/projects/${projectId}/environment-instances`,
      { template_version_id: templateVersionId, ttl_seconds: ttlSeconds },
      { headers: { 'Idempotency-Key': idempotencyKey } },
    )
  ).data
}

export async function cleanupEnvironment(
  projectId: string,
  instanceId: string,
): Promise<EnvironmentInstance> {
  return (
    await apiClient.post<EnvironmentInstance>(
      `/projects/${projectId}/environment-instances/${instanceId}/cleanup`,
    )
  ).data
}
