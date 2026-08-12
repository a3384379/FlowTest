import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../../lib/api'
import {
  createContractRun,
  listContractRuns,
  listGeneratedContractCases,
  reviewGeneratedContractCase,
} from './contract-service'

describe('contract service', () => {
  afterEach(() => vi.restoreAllMocks())

  it('maps contract run uploads and list resources', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { items: [] } })
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { id: 'run-2' } })
    const file = new File(['{}'], 'openapi.json', { type: 'application/json' })

    await listContractRuns('project-1')
    await createContractRun('project-1', file, 'run-1')
    await createContractRun('project-1', file, null)
    await createContractRun('project-1', file, null, {
      providerServiceId: 'provider-1',
      providerVersion: '2.0.0',
    })
    await listGeneratedContractCases('project-1', 'run-2')

    expect(get).toHaveBeenNthCalledWith(1, '/projects/project-1/contract-runs', {
      params: { page: 1, page_size: 100 },
    })
    const firstForm = post.mock.calls[0][1] as FormData
    expect(firstForm.get('document')).toBe(file)
    expect(firstForm.get('source_name')).toBe('openapi.json')
    expect(firstForm.get('baseline_run_id')).toBe('run-1')
    const secondForm = post.mock.calls[1][1] as FormData
    expect(secondForm.has('baseline_run_id')).toBe(false)
    const providerForm = post.mock.calls[2][1] as FormData
    expect(providerForm.get('provider_service_id')).toBe('provider-1')
    expect(providerForm.get('provider_version')).toBe('2.0.0')
    expect(get).toHaveBeenNthCalledWith(
      2,
      '/projects/project-1/contract-runs/run-2/generated-cases',
      { params: { page: 1, page_size: 100 } },
    )
  })

  it('maps accept and reject decisions', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { id: 'case-1' } })
    await reviewGeneratedContractCase('project-1', 'run-1', 'case-1', 'accept', {
      name: '确认用例',
      definition: { confirmed: true },
      note: '已检查',
    })
    await reviewGeneratedContractCase('project-1', 'run-1', 'case-2', 'reject', {
      note: '不适用',
    })

    expect(post).toHaveBeenNthCalledWith(
      1,
      '/projects/project-1/contract-runs/run-1/generated-cases/case-1/accept',
      { name: '确认用例', definition: { confirmed: true }, note: '已检查' },
    )
    expect(post).toHaveBeenNthCalledWith(
      2,
      '/projects/project-1/contract-runs/run-1/generated-cases/case-2/reject',
      { note: '不适用' },
    )
  })
})
