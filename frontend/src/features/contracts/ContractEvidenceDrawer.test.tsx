import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { App as AntdApp, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { expect, it, vi } from 'vitest'

import { server } from '../../test/server'
import ContractEvidenceViewer from './ContractEvidenceDrawer'
import type {
  DeploymentCheck,
  PactContractDetail,
  ProviderVerificationDetail,
} from './contract-hub-service'

const timestamp = '2026-10-20T12:00:00Z'
const pact: PactContractDetail = {
  contract: {
    id: 'pact-v1',
    project_id: 'project-1',
    consumer_service_id: 'consumer-1',
    consumer_name: 'Web',
    provider_service_id: 'provider-1',
    provider_name: 'Orders',
    consumer_version: 'web-v1',
    pact_specification_version: '3.0.0',
    source_type: 'upload',
    source_name: 'old.json',
    content_sha256: 'a'.repeat(64),
    interaction_count: 1,
    created_by_id: 'user-1',
    created_at: timestamp,
  },
  contract_document: {
    consumer: 'Web',
    provider: 'Orders',
    specification_version: '3.0.0',
    interactions: [
      {
        description: '读取旧订单',
        provider_states: [],
        request: { method: 'GET', path: '/orders/1', query: {}, headers: {}, body: null },
        response: { status: 200, headers: {}, body: { version: 'v1' } },
      },
    ],
  },
}
const verification: ProviderVerificationDetail = {
  actual_response_available: false,
  pact,
  verification: {
    id: 'verify-old',
    project_id: 'project-1',
    pact_contract_version_id: 'pact-v1',
    provider_version: 'orders-v1',
    target_base_url: 'http://synthetic-provider:8080',
    status: 'failed',
    interaction_count: 1,
    passed_count: 0,
    failed_count: 1,
    results: [
      {
        interaction_index: 0,
        description: '读取旧订单',
        status: 'failed',
        mismatch_codes: ['BODY_MISMATCH'],
      },
    ],
    verified_by_id: 'user-1',
    created_at: timestamp,
  },
}
const check: DeploymentCheck = {
  id: 'check-old',
  project_id: 'project-1',
  provider_service_id: 'provider-1',
  provider_version: 'orders-v1',
  decision: 'unsafe',
  evidence: {
    provider_name: 'Orders',
    blockers: [
      {
        code: 'PACT_VERIFICATION_FAILED',
        pact_contract_version_id: 'pact-v1',
        verification_id: 'verify-old',
      },
      { code: 'OPENAPI_BREAKING_CHANGE', contract_run_id: 'run-old', breaking_count: 2 },
      { code: 'LEGACY_BLOCKER', reason: '保留原始第三项证据' },
    ],
    pending: [],
  },
  checked_by_id: 'user-1',
  created_at: timestamp,
}

it('shows every blocker and exact old Interaction without provider calls or invented actual values', async () => {
  const reads: string[] = []
  const writes = vi.fn()
  server.use(
    http.get('/api/v1/projects/project-1/contract-hub/deployment-checks/check-old', () => {
      reads.push('check-old')
      return HttpResponse.json(check)
    }),
    http.get('/api/v1/projects/project-1/contract-hub/verifications/verify-old', () => {
      reads.push('verify-old')
      return HttpResponse.json(verification)
    }),
    http.get('/api/v1/projects/project-1/contract-hub/pacts/pact-v1', () => {
      reads.push('pact-v1')
      return HttpResponse.json(pact)
    }),
    http.post('/api/v1/projects/project-1/contract-hub/*', () => {
      writes()
      return HttpResponse.json({})
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <ConfigProvider theme={{ token: { motion: false } }}>
        <AntdApp>
          <ContractEvidenceViewer
            projectId="project-1"
            selection={{ kind: 'check', id: 'check-old' }}
            onClose={vi.fn()}
          />
        </AntdApp>
      </ConfigProvider>
    </QueryClientProvider>,
  )
  const drawer = screen.getByRole('dialog')
  expect(await within(drawer).findByText('阻断证据（3项）')).toBeVisible()
  expect(within(drawer).getByText('3. LEGACY_BLOCKER')).toBeVisible()
  fireEvent.click(within(drawer).getByRole('button', { name: '查看固定验证' }))
  expect(await within(drawer).findByText('实际响应未采集')).toBeVisible()
  expect(within(drawer).getByText(/"version": "v1"/)).toBeVisible()
  expect(within(drawer).getByText(/BODY_MISMATCH/)).toBeVisible()
  expect(within(drawer).queryByText(/"version": "v2"/)).not.toBeInTheDocument()
  expect(within(drawer).getByText('实际值：未提供')).toBeVisible()
  fireEvent.click(within(drawer).getByRole('button', { name: '返回上级证据' }))
  await within(drawer).findByText('阻断证据（3项）')
  fireEvent.click(within(drawer).getByRole('button', { name: '查看固定Pact' }))
  expect(await within(drawer).findByText('固定预期响应')).toBeVisible()
  expect(within(drawer).getByText(/"version": "v1"/)).toBeVisible()
  expect(reads).toEqual(['check-old', 'verify-old', 'pact-v1'])
  expect(writes).not.toHaveBeenCalled()
})
