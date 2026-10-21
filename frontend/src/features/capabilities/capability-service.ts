import { apiClient, type Page } from '../../lib/api'

export type V3FeatureFlags = {
  capability_sdk: boolean
  plugin_registry: boolean
  runner_fabric: boolean
  multi_protocol: boolean
  event_protocols: boolean
  performance_lab: boolean
  environment_lab: boolean
  contract_hub: boolean
  impact_engine: boolean
  quality_intelligence: boolean
  integration_flow: boolean
  pact_broker: boolean
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

export async function listCapabilities(page = 1, search = ''): Promise<Page<Capability>> {
  return (
    await apiClient.get<Page<Capability>>('/capabilities', {
      params: { page, page_size: 20, search },
    })
  ).data
}

export async function listPlugins(page = 1, search = ''): Promise<Page<Plugin>> {
  return (
    await apiClient.get<Page<Plugin>>('/plugins', {
      params: { page, page_size: 20, search },
    })
  ).data
}

export async function listRunnerPools(page = 1, search = ''): Promise<Page<RunnerPool>> {
  return (
    await apiClient.get<Page<RunnerPool>>('/runner-pools', {
      params: { page, page_size: 20, search },
    })
  ).data
}

export type PlatformSelection =
  | { kind: 'capability'; id: string; version: string }
  | { kind: 'plugin'; id: string }
  | { kind: 'runnerPool'; id: string }

export type PlatformObject =
  | { kind: 'capability'; record: Capability }
  | { kind: 'plugin'; record: Plugin }
  | { kind: 'runnerPool'; record: RunnerPool }

export async function getPlatformObject(selection: PlatformSelection): Promise<PlatformObject> {
  const id = encodeURIComponent(selection.id)
  if (selection.kind === 'capability')
    return {
      kind: selection.kind,
      record: (
        await apiClient.get<Capability>(
          `/capabilities/${id}/versions/${encodeURIComponent(selection.version)}`,
        )
      ).data,
    }
  if (selection.kind === 'plugin')
    return { kind: selection.kind, record: (await apiClient.get<Plugin>(`/plugins/${id}`)).data }
  return {
    kind: selection.kind,
    record: (await apiClient.get<RunnerPool>(`/runner-pools/${id}`)).data,
  }
}
