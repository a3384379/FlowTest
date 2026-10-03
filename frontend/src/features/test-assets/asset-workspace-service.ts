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
export type CaseRunHistory = {
  id: string
  execution_id: string | null
  case_version: number
  workflow_id: string
  workflow_version: number
  environment_id: string
  status: AssetRunItem['status']
  source: 'direct' | 'plan'
  started_at: string | null
  created_at: string
  plan_run_id: string | null
  plan_id: string | null
}
export type SuiteLatestRun = { suite_id: string; detail: AssetRunDetail }

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

export async function listCaseRunHistory(
  projectId: string,
  caseId: string,
  page: number,
  version?: number,
): Promise<Page<CaseRunHistory>> {
  return (
    await apiClient.get<Page<CaseRunHistory>>(`/projects/${projectId}/test-cases/${caseId}/runs`, {
      params: { page, page_size: 20, version },
    })
  ).data
}

export async function listSuiteRunHistory(
  projectId: string,
  suiteId: string,
  page: number,
  version?: number,
): Promise<Page<AssetRunDetail>> {
  return (
    await apiClient.get<Page<AssetRunDetail>>(
      `/projects/${projectId}/test-suites/${suiteId}/runs`,
      {
        params: { page, page_size: 20, version },
      },
    )
  ).data
}

export async function listLatestSuiteRuns(
  projectId: string,
  suiteIds: string[],
): Promise<SuiteLatestRun[]> {
  if (!suiteIds.length) return []
  return (
    await apiClient.get<SuiteLatestRun[]>(`/projects/${projectId}/test-suites/runs/latest`, {
      params: { suite_ids: suiteIds },
      paramsSerializer: { indexes: null },
    })
  ).data
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
