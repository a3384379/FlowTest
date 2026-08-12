import { apiClient, type Page } from '../../lib/api'

export type ImpactSourceKind = 'git' | 'openapi' | 'graphql' | 'grpc'
export type ImpactTargetType =
  'test_case' | 'workflow' | 'openapi_contract' | 'pact_contract' | 'performance'

export type ImpactMapping = {
  id: string
  project_id: string
  source_kind: ImpactSourceKind
  source_selector: string
  target_type: ImpactTargetType
  target_id: string
  target_name: string
  target_version: string | number | null
  created_by_id: string
  created_at: string
}

export type ImpactCatalogItem = {
  id: string
  target_type: ImpactTargetType
  name: string
  version: string | number | null
}

export type ImpactSchemaCatalogItem = {
  id: string
  protocol: 'graphql' | 'grpc'
  name: string
  version: number
}

export type ImpactCatalog = {
  targets: ImpactCatalogItem[]
  schemas: ImpactSchemaCatalogItem[]
}

export type ImpactChange = {
  key: string
  source_kind: ImpactSourceKind
  source_key: string
  change_type: 'added' | 'changed' | 'deleted'
  severity: 'breaking' | 'warning' | 'info'
  label: string
  detail: string
  before: unknown
  after: unknown
}

export type SelectedAsset = {
  asset_type: 'case' | 'workflow' | 'contract' | 'performance'
  target_type: ImpactTargetType
  target_id: string
  name: string
  version: string | number | null
  risk: 'high' | 'medium' | 'normal'
  change_keys: string[]
  reasons: string[]
}

export type CoverageMatrixRow = {
  change_key: string
  source_kind: ImpactSourceKind
  source_key: string
  label: string
  severity: 'breaking' | 'warning' | 'info'
  case_count: number
  workflow_count: number
  contract_count: number
  performance_count: number
  covered: boolean
}

export type CoverageGap = {
  change_key: string
  source_kind: ImpactSourceKind
  source_key: string
  label: string
  reason: string
}

export type ImpactRunSummary = {
  id: string
  project_id: string
  title: string
  source_ref: string
  status: 'completed' | 'failed'
  source_fingerprint: string
  source_summary: Record<string, unknown>
  change_count: number
  summary: {
    change_count: number
    breaking_change_count: number
    selected_asset_count: number
    covered_change_count: number
    gap_count: number
    coverage_percent: number
  }
  created_by_id: string
  created_at: string
}

export type ImpactRunDetail = ImpactRunSummary & {
  changes: ImpactChange[]
  graph: {
    nodes: Array<{
      id: string
      kind: 'change' | 'asset'
      label: string
      severity?: ImpactChange['severity']
      asset_type?: SelectedAsset['asset_type']
    }>
    edges: Array<{ from: string; to: string; reason: string }>
  }
  selection: {
    id: string
    strategy: string
    selected_assets: SelectedAsset[]
    explanations: CoverageMatrixRow[]
    created_at: string
  }
  coverage: {
    id: string
    total_changes: number
    covered_changes: number
    coverage_percent: number
    matrix: CoverageMatrixRow[]
    gaps: CoverageGap[]
    created_at: string
  }
}

export type ImpactRunInput = {
  title: string
  source_ref: string
  git_diff?: string
  openapi_diffs: Array<{ baseline_run_id: string; current_run_id: string }>
  schema_diffs: Array<{ baseline_artifact_id: string; current_artifact_id: string }>
}

export async function listImpactMappings(projectId: string): Promise<Page<ImpactMapping>> {
  return (
    await apiClient.get<Page<ImpactMapping>>(`/projects/${projectId}/impact/mappings`, {
      params: { page: 1, page_size: 100 },
    })
  ).data
}

export async function createImpactMapping(
  projectId: string,
  input: Pick<ImpactMapping, 'source_kind' | 'source_selector' | 'target_type' | 'target_id'>,
): Promise<ImpactMapping> {
  return (await apiClient.post<ImpactMapping>(`/projects/${projectId}/impact/mappings`, input)).data
}

export async function deleteImpactMapping(projectId: string, mappingId: string): Promise<void> {
  await apiClient.delete(`/projects/${projectId}/impact/mappings/${mappingId}`)
}

export async function getImpactCatalog(projectId: string): Promise<ImpactCatalog> {
  return (await apiClient.get<ImpactCatalog>(`/projects/${projectId}/impact/catalog`)).data
}

export async function listImpactRuns(projectId: string): Promise<Page<ImpactRunSummary>> {
  return (
    await apiClient.get<Page<ImpactRunSummary>>(`/projects/${projectId}/impact/runs`, {
      params: { page: 1, page_size: 100 },
    })
  ).data
}

export async function getImpactRun(projectId: string, runId: string): Promise<ImpactRunDetail> {
  return (await apiClient.get<ImpactRunDetail>(`/projects/${projectId}/impact/runs/${runId}`)).data
}

export async function createImpactRun(
  projectId: string,
  input: ImpactRunInput,
): Promise<ImpactRunDetail> {
  return (await apiClient.post<ImpactRunDetail>(`/projects/${projectId}/impact/runs`, input)).data
}
