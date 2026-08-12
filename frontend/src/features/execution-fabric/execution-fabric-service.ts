import { apiClient, type Page } from '../../lib/api'

export type RunnerFabricOverview = {
  pools: number
  runners_online: number
  runners_offline: number
  runners_draining: number
  queued_tasks: number
  active_leases: number
  completed_tasks: number
  failed_tasks: number
}

export type FabricRunner = {
  id: string
  pool_id: string
  name: string
  status: 'offline' | 'online' | 'draining' | 'disabled'
  runtime: 'docker' | 'kubernetes'
  agent_version: string
  architecture: string
  labels: string[]
  capabilities: string[]
  max_concurrency: number
  current_load: number
  last_seen_at: string | null
  draining_requested_at: string | null
  disabled_at: string | null
}

export type FabricPool = {
  id: string
  name: string
  runner_type: string
  runtime: 'docker' | 'kubernetes'
  network_zone: string
  labels: string[]
  capabilities: string[]
  max_concurrency: number
  lease_timeout_seconds: number
  heartbeat_timeout_seconds: number
  enabled: boolean
  created_at: string
  runners: FabricRunner[]
}

export type FabricTask = {
  id: string
  execution_id: string
  project_id: string
  required_runner_type: string
  required_labels: string[]
  required_capabilities: string[]
  status: 'queued' | 'leased' | 'completed' | 'failed' | 'cancelled'
  priority: number
  attempts: number
  max_attempts: number
  fencing_token: number
  available_at: string
  selected_runner_id: string | null
  last_lease_id: string | null
  error_code: string | null
  error_message: string | null
  completed_at: string | null
  created_at: string
}

export type FabricLease = {
  id: string
  task_id: string
  runner_id: string
  fencing_token: number
  status: 'active' | 'completed' | 'expired' | 'released'
  acquired_at: string
  expires_at: string
  last_renewed_at: string
  completed_at: string | null
}

export type FabricEvent = {
  id: string
  pool_id: string
  runner_id: string | null
  task_id: string | null
  lease_id: string | null
  kind: string
  message: string
  details: Record<string, unknown>
  created_at: string
}

export type FabricPoolInput = {
  name: string
  runner_type: 'general' | 'data' | 'protocol' | 'performance' | 'environment'
  runtime: 'docker' | 'kubernetes'
  network_zone: string
  labels: string[]
  capabilities: string[]
  max_concurrency: number
  lease_timeout_seconds: number
  heartbeat_timeout_seconds: number
}

export type RegistrationToken = {
  id: string
  pool_id: string
  token: string
  expires_at: string
}

export async function getRunnerFabricOverview(): Promise<RunnerFabricOverview> {
  return (await apiClient.get<RunnerFabricOverview>('/execution-fabric/overview')).data
}

export async function listFabricPools(): Promise<Page<FabricPool>> {
  return (
    await apiClient.get<Page<FabricPool>>('/execution-fabric/pools', {
      params: { page: 1, page_size: 100 },
    })
  ).data
}

export async function listFabricTasks(): Promise<Page<FabricTask>> {
  return (
    await apiClient.get<Page<FabricTask>>('/execution-fabric/tasks', { params: { limit: 100 } })
  ).data
}

export async function listFabricLeases(): Promise<Page<FabricLease>> {
  return (
    await apiClient.get<Page<FabricLease>>('/execution-fabric/leases', {
      params: { limit: 100 },
    })
  ).data
}

export async function listFabricEvents(): Promise<Page<FabricEvent>> {
  return (
    await apiClient.get<Page<FabricEvent>>('/execution-fabric/events', {
      params: { limit: 100 },
    })
  ).data
}

export async function createFabricPool(input: FabricPoolInput): Promise<FabricPool> {
  return (await apiClient.post<FabricPool>('/execution-fabric/pools', input)).data
}

export async function createRegistrationToken(poolId: string): Promise<RegistrationToken> {
  return (
    await apiClient.post<RegistrationToken>(
      `/execution-fabric/pools/${poolId}/registration-tokens`,
      { expires_in_seconds: 900 },
    )
  ).data
}

export async function changeRunnerState(
  runnerId: string,
  action: 'drain' | 'resume' | 'disable',
): Promise<FabricRunner> {
  return (
    await apiClient.post<FabricRunner>(`/execution-fabric/runners/${runnerId}/actions`, {
      action,
    })
  ).data
}
