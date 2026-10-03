import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '../../lib/api'
import {
  createAssetPlan,
  getAsset,
  listAssetPlans,
  listAssetWorkflows,
  listCaseCatalog,
  listCaseRunHistory,
  listSuiteRunHistory,
  listLatestSuiteRuns,
  listSuiteCatalog,
} from './asset-workspace-service'

afterEach(() => vi.restoreAllMocks())

describe('asset workspace service', () => {
  it('loads later pages for directories and pickers instead of truncating at 100', async () => {
    const get = vi.spyOn(apiClient, 'get').mockImplementation(async (_url, config) => ({
      data:
        (config?.params as { page: number }).page === 1
          ? {
              items: Array.from({ length: 100 }, (_, index) => ({ id: `item-${index}` })),
              total: 101,
              page: 1,
              page_size: 100,
            }
          : { items: [{ id: 'item-100' }], total: 101, page: 2, page_size: 100 },
    }))
    expect((await listCaseCatalog('project-1', '订单', 'regression')).items).toHaveLength(101)
    expect((await listSuiteCatalog('project-1', '', '')).items).toHaveLength(101)
    expect((await listAssetWorkflows('project-1')).items).toHaveLength(101)
    expect((await listAssetPlans('project-1')).items).toHaveLength(101)
    expect(get).toHaveBeenCalledWith('/projects/project-1/test-cases', {
      params: { page: 2, page_size: 100, search: '订单', tag: 'regression' },
    })
  })

  it('rejects a stalled catalog rather than claiming a partial directory is complete', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { items: [{ id: 'item-1' }], total: 180 },
    })
    await expect(listCaseCatalog('project-1', '', '')).rejects.toThrow(
      '资产列表在分页读取时发生变化',
    )
  })

  it('queries asset-owned history by version and page instead of a project-wide recent window', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: {} })
    await getAsset('project-1', 'case', 'case-1')
    await getAsset('project-1', 'suite', 'suite-1')
    await listCaseRunHistory('project-1', 'case-1', 3, 1)
    await listSuiteRunHistory('project-1', 'suite-1', 2)
    await listLatestSuiteRuns('project-1', ['suite-1'])
    expect(get).toHaveBeenCalledWith('/projects/project-1/test-cases/case-1')
    expect(get).toHaveBeenCalledWith('/projects/project-1/test-suites/suite-1')
    expect(get).toHaveBeenCalledWith('/projects/project-1/test-cases/case-1/runs', {
      params: { page: 3, page_size: 20, version: 1 },
    })
    expect(get).toHaveBeenCalledWith('/projects/project-1/test-suites/suite-1/runs', {
      params: { page: 2, page_size: 20, version: undefined },
    })
    expect(get).toHaveBeenCalledWith('/projects/project-1/test-suites/runs/latest', {
      params: { suite_ids: ['suite-1'] },
      paramsSerializer: { indexes: null },
    })
  })

  it('creates plans with explicit selected asset versions and performs no execution', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: {} })
    await createAssetPlan('project-1', '固定版本回归', [
      { kind: 'case', id: 'case-1', name: '订单校验', version: 1 },
      { kind: 'suite', id: 'suite-1', name: '核心回归', version: 3 },
    ])
    expect(post).toHaveBeenCalledTimes(1)
    expect(post).toHaveBeenCalledWith('/projects/project-1/test-plans', {
      name: '固定版本回归',
      enabled: true,
      items: [
        { target_type: 'case', target_id: 'case-1', target_version: 1 },
        { target_type: 'suite', target_id: 'suite-1', target_version: 3 },
      ],
    })
  })
})
