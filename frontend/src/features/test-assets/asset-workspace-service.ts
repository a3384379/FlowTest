import {
  apiClient,
  type CreatedTestPlan,
  type Page,
  type TestCase,
  type TestCaseDefinition,
  type TestPlan,
  type TestPlanRun,
  type TestSuite,
  type Workflow,
} from '../../lib/api'
import { listTestCases, listTestSuites } from './test-asset-service'

export type AssetKind = 'case' | 'suite'
export type PublishedAssetTarget = {
  kind: AssetKind
  id: string
  name: string
  version: number
}
export type AssetCatalog<T> = { items: T[]; total: number }
export type AssetRunItem = {
  id: string
  target_type: 'workflow' | 'case'
  target_id: string
  target_version: number
  target_snapshot: {
    target_type: 'workflow' | 'case'
    target_id: string
    target_version: number
    definition?: TestCaseDefinition
    source_suite?: { id: string; version: number }
  }
  workflow_id: string
  environment_id: string
  workflow_version: number
  position: number
  max_retries: number
  attempts: number
  status: 'queued' | 'running' | 'passed' | 'failed' | 'cancelled' | 'quarantined'
  workflow_execution_id: string | null
  error_message: string | null
}
export type AssetRunDetail = { run: TestPlanRun; items: AssetRunItem[] }

// These three existing resources share the same page contract. Complete catalogs
// let directory filters and version pickers include records beyond page one.
export function listCaseCatalog(projectId: string, search: string, tag: string) {
  return collectPages((page) => listTestCases(projectId, search, tag, page, 100))
}

export function listSuiteCatalog(projectId: string, search: string, tag: string) {
  return collectPages((page) => listTestSuites(projectId, search, tag, page, 100))
}

export function listAssetWorkflows(projectId: string) {
  return collectPages(
    async (page) =>
      (
        await apiClient.get<Page<Workflow>>(`/projects/${projectId}/workflows`, {
          params: { page, page_size: 100 },
        })
      ).data,
  )
}

async function collectPages<T extends { id: string }>(
  fetchPage: (page: number) => Promise<Page<T>>,
): Promise<AssetCatalog<T>> {
  const first = await fetchPage(1)
  const items = new Map(first.items.map((item) => [item.id, item]))
  let total = first.total
  let page = 1
  while (items.size < total) {
    const next = await fetchPage(++page)
    const before = items.size
    next.items.forEach((item) => items.set(item.id, item))
    total = next.total
    if (items.size === before && items.size < total) {
      throw new Error('资产列表在分页读取时发生变化，请重新加载')
    }
  }
  if (items.size !== total) throw new Error('资产数量在读取时发生变化，请重新加载')
  return { items: [...items.values()], total }
}

export async function getAsset(projectId: string, kind: 'case', id: string): Promise<TestCase>
export async function getAsset(projectId: string, kind: 'suite', id: string): Promise<TestSuite>
export async function getAsset(
  projectId: string,
  kind: AssetKind,
  id: string,
): Promise<TestCase | TestSuite>
export async function getAsset(projectId: string, kind: AssetKind, id: string) {
  const resource = kind === 'case' ? 'test-cases' : 'test-suites'
  return (await apiClient.get<TestCase | TestSuite>(`/projects/${projectId}/${resource}/${id}`))
    .data
}

export async function listAssetPlans(projectId: string): Promise<AssetCatalog<TestPlan>> {
  return collectPages(
    async (page) =>
      (
        await apiClient.get<Page<TestPlan>>(`/projects/${projectId}/test-plans`, {
          params: { page, page_size: 100 },
        })
      ).data,
  )
}

export async function listRecentAssetRuns(projectId: string): Promise<Page<TestPlanRun>> {
  return (
    await apiClient.get<Page<TestPlanRun>>(`/projects/${projectId}/test-plan-runs`, {
      params: { page: 1, page_size: 20 },
    })
  ).data
}

export async function getAssetRun(projectId: string, runId: string): Promise<AssetRunDetail> {
  return (await apiClient.get<AssetRunDetail>(`/projects/${projectId}/test-plan-runs/${runId}`))
    .data
}

export async function createAssetPlan(
  projectId: string,
  name: string,
  targets: PublishedAssetTarget[],
): Promise<CreatedTestPlan> {
  return (
    await apiClient.post<CreatedTestPlan>(`/projects/${projectId}/test-plans`, {
      name,
      enabled: true,
      items: targets.map((target) => ({
        target_type: target.kind,
        target_id: target.id,
        target_version: target.version,
      })),
    })
  ).data
}
