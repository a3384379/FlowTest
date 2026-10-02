import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '../../lib/api'
import {
  createAssetPlan,
  getAsset,
  getAssetRun,
  listAssetPlans,
  listAssetWorkflows,
  listCaseCatalog,
  listRecentAssetRuns,
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

  it('keeps every read project-scoped and limits the declared execution range to 20 runs', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: {} })
    await getAsset('project-1', 'case', 'case-1')
    await getAsset('project-1', 'suite', 'suite-1')
    await getAssetRun('project-1', 'run-1')
    await listRecentAssetRuns('project-1')
    expect(get).toHaveBeenCalledWith('/projects/project-1/test-cases/case-1')
    expect(get).toHaveBeenCalledWith('/projects/project-1/test-suites/suite-1')
    expect(get).toHaveBeenCalledWith('/projects/project-1/test-plan-runs/run-1')
    expect(get).toHaveBeenCalledWith('/projects/project-1/test-plan-runs', {
      params: { page: 1, page_size: 20 },
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
