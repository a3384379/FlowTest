import { describe, expect, it } from 'vitest'
import { assetRunHistory, assetRunStatus, reportItem } from './asset-run-view-model'
import type { AssetRunDetail, AssetRunItem } from './asset-workspace-service'

const item = (overrides: Partial<AssetRunItem> = {}): AssetRunItem => ({
  id: 'item-1',
  target_type: 'case',
  target_id: 'case-1',
  target_version: 1,
  target_snapshot: { target_type: 'case', target_id: 'case-1', target_version: 1 },
  workflow_id: 'flow-1',
  workflow_version: 2,
  environment_id: 'env-1',
  position: 0,
  max_retries: 0,
  attempts: 1,
  status: 'passed',
  workflow_execution_id: 'execution-1',
  error_message: null,
  ...overrides,
})
const detail = (items: AssetRunItem[], created = '2026-10-02T10:00:00Z'): AssetRunDetail => ({
  run: { id: `run-${created}`, created_at: created, status: 'failed' } as AssetRunDetail['run'],
  items,
})

describe('asset execution linkage', () => {
  it('uses actual case targets and never attributes a workflow run or another case to this asset', () => {
    const records = [
      detail([
        item(),
        item({ id: 'other', target_id: 'case-2', status: 'failed' }),
        item({ id: 'flow', target_type: 'workflow', target_id: 'case-1', status: 'failed' }),
      ]),
    ]
    const history = assetRunHistory(records, 'case', 'case-1')
    expect(history).toHaveLength(1)
    expect(history[0].status).toBe('passed')
    expect(history[0].versions).toEqual([1])
    expect(history[0].items).toEqual([item()])
  })

  it('aggregates only frozen suite members and chooses failed execution evidence', () => {
    const source_suite = { id: 'suite-1', version: 3 }
    const records = [
      detail([
        item({ target_snapshot: { ...item().target_snapshot, source_suite } }),
        item({
          id: 'failed',
          target_id: 'case-2',
          target_version: 2,
          status: 'failed',
          workflow_execution_id: 'execution-failed',
          target_snapshot: { ...item().target_snapshot, source_suite },
        }),
        item({ id: 'unrelated', target_id: 'case-3', status: 'cancelled' }),
      ]),
    ]
    const entry = assetRunHistory(records, 'suite', 'suite-1')[0]
    expect(entry.status).toBe('failed')
    expect(entry.versions).toEqual([3])
    expect(entry.items).toHaveLength(2)
    expect(reportItem(entry)?.workflow_execution_id).toBe('execution-failed')
    expect(assetRunHistory(records, 'suite', 'suite-2')).toEqual([])
  })

  it('orders actual run time and preserves historical asset versions', () => {
    const entries = assetRunHistory(
      [
        detail([item({ target_version: 4 })], '2026-10-02T10:10:00Z'),
        detail([item({ target_version: 1 })]),
      ],
      'case',
      'case-1',
    )
    expect(entries.map((entry) => entry.versions)).toEqual([[4], [1]])
  })

  it('keeps unfinished, cancelled and quarantined items from becoming a pass', () => {
    expect(assetRunStatus([item(), item({ status: 'queued' })])).toBe('queued')
    expect(assetRunStatus([item(), item({ status: 'running' })])).toBe('running')
    expect(assetRunStatus([item(), item({ status: 'cancelled' })])).toBe('cancelled')
    expect(assetRunStatus([item(), item({ status: 'quarantined' })])).toBe('quarantined')
    const entry = assetRunHistory(
      [detail([item({ status: 'queued', workflow_execution_id: null })])],
      'case',
      'case-1',
    )[0]
    expect(reportItem(entry)).toBeUndefined()
  })
})
