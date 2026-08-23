import { apiClient, type Page } from '../../lib/api'

export type OrganizationRole = 'owner' | 'admin' | 'member' | 'viewer'
export type QuotaMode = 'observe' | 'warn' | 'soft_limit' | 'hard_limit'
export type QuotaDimension =
  | 'project_count'
  | 'user_count'
  | 'runner_concurrency'
  | 'execution_concurrency'
  | 'ai_request_count'
  | 'artifact_storage'

export type Organization = {
  id: string
  name: string
  slug: string
  description: string
  enabled: boolean
  created_by_id: string | null
  role: OrganizationRole | null
  member_count: number | null
  created_at: string
  updated_at: string
}

export type OrganizationMember = {
  id: string
  organization_id: string
  user_id: string
  role: OrganizationRole
  created_at: string
  updated_at: string
}

export type ServiceAccount = {
  id: string
  organization_id: string
  name: string
  account_key: string
  token_prefix: string
  scopes: string[]
  enabled: boolean
  created_by_id: string
  expires_at: string | null
  last_used_at: string | null
  revoked_at: string | null
  metadata_json: Record<string, string>
  created_at: string
  updated_at: string
}

export type IssuedServiceAccount = ServiceAccount & { token: string }

export type QuotaRule = {
  mode: QuotaMode
  limit: number | null
  warn_at: number | null
}

export type RunnerGovernancePolicy = {
  allowed_runner_types: string[]
  allowed_runtimes: string[]
  max_pools: number
  registration_requires_approval: boolean
}

export type OrganizationGovernance = {
  organization_id: string
  audit_retention_days: number
  quota_policies: Record<QuotaDimension, QuotaRule>
  runner_policy: RunnerGovernancePolicy
  active_key_version: number
  updated_at: string
}

export type OrganizationAuditLog = {
  id: string
  actor_user_id: string | null
  organization_id: string | null
  project_id: string | null
  action: string
  resource_type: string
  resource_id: string | null
  details: Record<string, unknown>
  created_at: string
}

export type RunnerGovernanceSummary = {
  organization_id: string
  pool_count: number
  runner_count: number
  current_load: number
  capacity: number
  pools: Array<{
    id: string
    name: string
    runner_type: string
    runtime: string
    enabled: boolean
    max_concurrency: number
    current_load: number
    runner_count: number
  }>
}

export type KeyVersion = {
  id: string
  organization_id: string
  version: number
  key_reference: string
  key_fingerprint: string
  status: 'pending' | 'active' | 'retiring' | 'retired' | 'rolled_back'
  migration_status: 'planned' | 'migrating' | 'migrated' | 'rolled_back'
  previous_version: number | null
  created_by_id: string
  activated_at: string | null
  migrated_at: string | null
  rolled_back_at: string | null
  created_at: string
  updated_at: string
}

export type OrganizationSecurity = {
  organization_id: string
  active_key_version: number
  key_versions: KeyVersion[]
  capability_name: 'Key Lifecycle Metadata / Rotation Plan'
  capability_mode: 'metadata_plan_only'
  ciphertext_reencryption_available: false
  ga_blocker: 'REAL_KEY_ROTATION_NOT_IMPLEMENTED'
}

export type SupportBundleRedaction = {
  organization_id: string
  schema_version: string
  data_classification: string
  included_sections: string[]
  redacted_fields: string[]
  excluded_fields: string[]
}

export type OrganizationCreateInput = {
  name: string
  slug?: string
  description?: string
}

export type OrganizationGovernanceInput = {
  audit_retention_days?: number
  quota_policies?: Partial<Record<QuotaDimension, QuotaRule>>
  runner_policy?: RunnerGovernancePolicy
}

export async function listOrganizations(): Promise<Organization[]> {
  return (await apiClient.get<Organization[]>('/organizations')).data
}

export async function createOrganization(input: OrganizationCreateInput): Promise<Organization> {
  return (await apiClient.post<Organization>('/organizations', input)).data
}

export async function listOrganizationMembers(
  organizationId: string,
): Promise<OrganizationMember[]> {
  return (await apiClient.get<OrganizationMember[]>(`/organizations/${organizationId}/members`))
    .data
}

export async function upsertOrganizationMember(
  organizationId: string,
  userId: string,
  role: OrganizationRole,
): Promise<OrganizationMember> {
  return (
    await apiClient.put<OrganizationMember>(`/organizations/${organizationId}/members/${userId}`, {
      user_id: userId,
      role,
    })
  ).data
}

export async function listServiceAccounts(organizationId: string): Promise<ServiceAccount[]> {
  return (
    await apiClient.get<ServiceAccount[]>(`/organizations/${organizationId}/service-accounts`)
  ).data
}

export async function createServiceAccount(
  organizationId: string,
  input: { name: string; account_key: string; scopes: string[] },
): Promise<IssuedServiceAccount> {
  return (
    await apiClient.post<IssuedServiceAccount>(
      `/organizations/${organizationId}/service-accounts`,
      { ...input, metadata: {} },
    )
  ).data
}

export async function rotateServiceAccount(
  organizationId: string,
  accountId: string,
): Promise<IssuedServiceAccount> {
  return (
    await apiClient.post<IssuedServiceAccount>(
      `/organizations/${organizationId}/service-accounts/${accountId}/rotate`,
    )
  ).data
}

export async function revokeServiceAccount(
  organizationId: string,
  accountId: string,
): Promise<ServiceAccount> {
  return (
    await apiClient.post<ServiceAccount>(
      `/organizations/${organizationId}/service-accounts/${accountId}/revoke`,
    )
  ).data
}

export async function getOrganizationGovernance(
  organizationId: string,
): Promise<OrganizationGovernance> {
  return (
    await apiClient.get<OrganizationGovernance>(`/organizations/${organizationId}/governance`)
  ).data
}

export async function updateOrganizationGovernance(
  organizationId: string,
  input: OrganizationGovernanceInput,
): Promise<OrganizationGovernance> {
  return (
    await apiClient.patch<OrganizationGovernance>(
      `/organizations/${organizationId}/governance`,
      input,
    )
  ).data
}

export async function getRunnerGovernance(
  organizationId: string,
): Promise<RunnerGovernanceSummary> {
  return (
    await apiClient.get<RunnerGovernanceSummary>(
      `/organizations/${organizationId}/runner-governance`,
    )
  ).data
}

export async function listOrganizationAuditLogs(
  organizationId: string,
): Promise<Page<OrganizationAuditLog>> {
  return (
    await apiClient.get<Page<OrganizationAuditLog>>(`/organizations/${organizationId}/audit-logs`, {
      params: { page: 1, page_size: 50 },
    })
  ).data
}

export async function getOrganizationSecurity(
  organizationId: string,
): Promise<OrganizationSecurity> {
  return (await apiClient.get<OrganizationSecurity>(`/organizations/${organizationId}/security`))
    .data
}

export async function prepareKeyRotation(
  organizationId: string,
  input: { key_reference: string; key_fingerprint: string },
): Promise<KeyVersion> {
  return (
    await apiClient.post<KeyVersion>(
      `/organizations/${organizationId}/security/key-rotation/prepare`,
      input,
    )
  ).data
}

export async function applyKeyRotation(
  organizationId: string,
  keyVersionId: string,
): Promise<KeyVersion> {
  return (
    await apiClient.post<KeyVersion>(
      `/organizations/${organizationId}/security/key-rotation/${keyVersionId}/apply`,
    )
  ).data
}

export async function rollbackKeyRotation(
  organizationId: string,
  keyVersionId: string,
): Promise<KeyVersion> {
  return (
    await apiClient.post<KeyVersion>(
      `/organizations/${organizationId}/security/key-rotation/${keyVersionId}/rollback`,
    )
  ).data
}

export async function getSupportBundleRedaction(
  organizationId: string,
): Promise<SupportBundleRedaction> {
  return (
    await apiClient.get<SupportBundleRedaction>(
      `/organizations/${organizationId}/support-bundle/redaction`,
    )
  ).data
}
