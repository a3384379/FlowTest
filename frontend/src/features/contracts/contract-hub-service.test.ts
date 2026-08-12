import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../../lib/api'
import {
  createContractService,
  getCompatibilityMatrix,
  getContractHubSummary,
  getServiceGraph,
  importPactContract,
  listContractServices,
  listDeploymentChecks,
  listPactContracts,
  runDeploymentCheck,
  verifyPactProvider,
} from './contract-hub-service'

describe('contract hub service', () => {
  afterEach(() => vi.restoreAllMocks())

  it('maps read and JSON write endpoints', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { items: [] } })
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { id: 'result-1' } })

    await listContractServices('project-1')
    await listPactContracts('project-1')
    await getContractHubSummary('project-1')
    await getServiceGraph('project-1')
    await getCompatibilityMatrix('project-1', 'provider-1')
    await listDeploymentChecks('project-1')
    await createContractService('project-1', {
      service_key: 'orders-api',
      display_name: '订单服务',
      description: '',
    })
    await verifyPactProvider('project-1', {
      pactId: 'pact-1',
      providerVersion: '2.0.0',
      targetBaseUrl: 'http://orders:8080',
    })
    await runDeploymentCheck('project-1', {
      providerServiceId: 'provider-1',
      providerVersion: '2.0.0',
    })
    await importPactContract('project-1', {
      kind: 'broker',
      consumer: 'Web',
      provider: 'Orders',
      consumerVersion: '42',
    })

    expect(get).toHaveBeenNthCalledWith(1, '/projects/project-1/contract-hub/services', {
      params: { page: 1, page_size: 100 },
    })
    expect(get).toHaveBeenNthCalledWith(
      5,
      '/projects/project-1/contract-hub/compatibility/provider-1',
    )
    expect(post).toHaveBeenCalledWith('/projects/project-1/contract-hub/services', {
      service_key: 'orders-api',
      display_name: '订单服务',
      description: '',
    })
    expect(post).toHaveBeenCalledWith('/projects/project-1/contract-hub/pacts/pact-1/verify', {
      provider_version: '2.0.0',
      target_base_url: 'http://orders:8080',
    })
    expect(post).toHaveBeenCalledWith('/projects/project-1/contract-hub/deployment-checks', {
      provider_service_id: 'provider-1',
      provider_version: '2.0.0',
    })
    expect(post).toHaveBeenCalledWith('/projects/project-1/contract-hub/pacts/import-broker', {
      consumer: 'Web',
      provider: 'Orders',
      consumer_version: '42',
    })
  })

  it('uploads Pact as multipart data', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { id: 'pact-1' } })
    const document = new File(['{}'], 'web-orders.json', { type: 'application/json' })
    await importPactContract('project-1', {
      kind: 'upload',
      document,
      consumerVersion: 'web-42',
    })

    const form = post.mock.calls[0][1] as FormData
    expect(post.mock.calls[0][0]).toBe('/projects/project-1/contract-hub/pacts')
    expect(form.get('document')).toBe(document)
    expect(form.get('consumer_version')).toBe('web-42')
    expect(form.get('source_name')).toBe('web-orders.json')
  })
})
