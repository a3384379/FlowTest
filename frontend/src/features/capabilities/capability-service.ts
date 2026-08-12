import { apiClient, type Page } from '../../lib/api'

export type V3FeatureFlags = {
  capability_sdk: boolean
  plugin_registry: boolean
  runner_fabric: boolean
}

export type CapabilityManifest = {
  id: string
  version: string
  category: string
  display_name: string
  description: string
  credential_types: string[]
  runner_type: string
  network_policy: {
    access: 'denied' | 'project_allowlist' | 'broker_only'
    protocols: string[]
    dns_revalidation: boolean
  }
  timeout_policy: { default_seconds: number; maximum_seconds: number }
  snapshot_policy: {
    include_configuration: boolean
    include_schema_hash: boolean
    pin_plugin_digest: boolean
    credential_material: string
  }
  redaction_policy: {
    sensitive_paths: string[]
    redact_credentials: boolean
    redact_headers: boolean
    redact_artifacts: boolean
  }
  plugin_id: string | null
  plugin_digest: string | null
  input_schema: Record<string, unknown>
  output_schema: Record<string, unknown>
  configuration_schema: Record<string, unknown>
}

export type Capability = {
  id: string
  version: string
  category: string
  display_name: string
  description: string
  runner_type: string
  network_access: string
  schema_hash: string
  source: 'builtin' | 'plugin'
  enabled: boolean
  plugin_id: string | null
  plugin_digest: string | null
  manifest: CapabilityManifest
}

export type Plugin = {
  id: string
  plugin_key: string
  version: string
  display_name: string
  oci_repository: string
  oci_digest: string
  signature_identity: string
  status: 'pending' | 'active' | 'disabled'
  created_at: string
  updated_at: string
}

export type Runner = {
  id: string
  pool_id: string
  name: string
  status: 'offline' | 'online' | 'draining' | 'disabled'
  labels: string[]
  capabilities: string[]
  current_load: number
  last_seen_at: string | null
}

export type RunnerPool = {
  id: string
  name: string
  runner_type: string
  network_zone: string
  labels: string[]
  max_concurrency: number
  enabled: boolean
  runners: Runner[]
}

export async function getV3FeatureFlags(): Promise<V3FeatureFlags> {
  return (await apiClient.get<V3FeatureFlags>('/v3/features')).data
}

export async function listCapabilities(): Promise<Page<Capability>> {
  return (
    await apiClient.get<Page<Capability>>('/capabilities', {
      params: { page: 1, page_size: 100 },
    })
  ).data
}

export async function listPlugins(): Promise<Page<Plugin>> {
  return (
    await apiClient.get<Page<Plugin>>('/plugins', {
      params: { page: 1, page_size: 100 },
    })
  ).data
}

export async function listRunnerPools(): Promise<Page<RunnerPool>> {
  return (
    await apiClient.get<Page<RunnerPool>>('/runner-pools', {
      params: { page: 1, page_size: 100 },
    })
  ).data
}
