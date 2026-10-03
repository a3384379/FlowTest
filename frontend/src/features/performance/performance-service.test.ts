import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../../lib/api'
import { downloadPerformanceMetrics, type PerformanceRun } from './performance-service'

const run: PerformanceRun = {
  id: 'frozen-run',
  project_id: 'owner-project',
  scenario_id: 'scenario',
  scenario_version: 2,
  status: 'passed',
  definition_snapshot: {
    executor: 'constant_vus',
    steps: [],
    thresholds: [],
    vus: 5,
    duration_seconds: 30,
    start_vus: null,
    stages: [],
    graceful_stop_seconds: 30,
  },
  compiled_sha256: 'a'.repeat(64),
  summary: {},
  threshold_results: [],
  baseline_run_id: null,
  raw_metrics_artifact_id: 'authorized-file',
  error_code: null,
  error_message: null,
  started_at: null,
  completed_at: null,
  created_by_id: 'owner',
  created_at: '',
  updated_at: '',
  gate_evaluations: [],
}

afterEach(() => vi.restoreAllMocks())

describe('performance metric download', () => {
  it('downloads the authorized frozen artifact and releases its object URL', async () => {
    const createUrl = vi.fn(() => 'blob:metrics')
    const revokeUrl = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createUrl })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeUrl })
    const downloaded: string[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      downloaded.push(this.download)
    })
    const get = vi
      .spyOn(apiClient, 'get')
      .mockResolvedValue({ data: new Blob(['original ndjson']) } as never)
    await downloadPerformanceMetrics(run.project_id, run)
    expect(get).toHaveBeenCalledWith('/projects/owner-project/files/authorized-file', {
      responseType: 'blob',
    })
    expect(downloaded).toEqual(['performance-frozen-run.ndjson'])
    expect(revokeUrl).toHaveBeenCalledWith('blob:metrics')
  })

  it('rejects foreign projects and missing artifact references before requesting any file', async () => {
    const get = vi.spyOn(apiClient, 'get')
    await expect(downloadPerformanceMetrics('foreign-project', run)).rejects.toThrow(
      '没有可下载的原始指标',
    )
    await expect(
      downloadPerformanceMetrics(run.project_id, { ...run, raw_metrics_artifact_id: null }),
    ).rejects.toThrow('没有可下载的原始指标')
    expect(get).not.toHaveBeenCalled()
  })

  it('preserves server download failures and does not synthesize an empty metrics file', async () => {
    const error = new Error('原始指标文件已过期')
    vi.spyOn(apiClient, 'get').mockRejectedValue(error)
    const createUrl = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createUrl })
    await expect(downloadPerformanceMetrics(run.project_id, run)).rejects.toBe(error)
    expect(createUrl).not.toHaveBeenCalled()
  })
})
