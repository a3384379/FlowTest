import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import type { ContractRun } from '../lib/api'
import type {
  CompatibilityMatrix,
  ContractHubSummary,
  DeploymentCheck,
  PactContract,
  ServiceCatalogEntry,
  ServiceGraph,
} from '../features/contracts/contract-hub-service'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { project, user } from '../test/fixtures'
import { server } from '../test/server'
import ContractHubPage, {
  CompatibilityStatus,
  ContractOverview,
  DecisionTag,
  FailedEvidencePanel,
  ServiceGraphPanel,
  UnifiedContractsPanel,
} from './ContractHubPage'

const timestamp = '2026-08-12T08:00:00Z'
const consumerId = '00000000-0000-4000-8000-000000002701'
const providerId = '00000000-0000-4000-8000-000000002702'
const pactId = '00000000-0000-4000-8000-000000002703'

const services: ServiceCatalogEntry[] = [
  {
    id: consumerId,
    project_id: project.id,
    service_key: 'web-client',
    display_name: 'Web 前端',
    description: 'Consumer',
    created_by_id: user.id,
    created_at: timestamp,
    updated_at: timestamp,
  },
  {
    id: providerId,
    project_id: project.id,
    service_key: 'orders-api',
    display_name: '订单服务',
    description: 'Provider',
    created_by_id: user.id,
    created_at: timestamp,
    updated_at: timestamp,
  },
]

const pact: PactContract = {
  id: pactId,
  project_id: project.id,
  consumer_service_id: consumerId,
  consumer_name: 'Web 前端',
  provider_service_id: providerId,
  provider_name: '订单服务',
  consumer_version: 'web-42',
  pact_specification_version: '3.0.0',
  source_type: 'broker',
  source_name: 'broker:Web:Orders:web-42',
  content_sha256: 'a'.repeat(64),
  interaction_count: 3,
  created_by_id: user.id,
  created_at: timestamp,
}

const openapiRun: ContractRun = {
  id: '00000000-0000-4000-8000-000000002704',
  project_id: project.id,
  baseline_run_id: null,
  source_name: 'orders-openapi.json',
  source_type: 'openapi3',
  source_sha256: 'b'.repeat(64),
  status: 'completed',
  diff_summary: { added: 1, changed: 0, deleted: 0, unchanged: 0 },
  breaking_changes: [],
  coverage: {
    operations_total: 1,
    operations_generated: 1,
    operation_coverage_percent: 100,
    request_fields_total: 0,
    response_fields_total: 1,
    schema_fields_total: 1,
    schema_fields_covered: 1,
    schema_coverage_percent: 100,
  },
  generated_case_count: 1,
  provider_service_id: providerId,
  provider_version: '2.0.0',
  created_by_id: user.id,
  created_at: timestamp,
  updated_at: timestamp,
}

const summary: ContractHubSummary = {
  service_count: 2,
  openapi_contract_count: 1,
  pact_contract_count: 1,
  pending_verification_count: 1,
  failed_verification_count: 1,
  breaking_change_count: 2,
  broker_available: true,
}

const graph: ServiceGraph = {
  nodes: services.map((item) => ({
    id: item.id,
    service_key: item.service_key,
    display_name: item.display_name,
    contract_kinds: ['pact'],
  })),
  edges: [
    {
      consumer_service_id: consumerId,
      provider_service_id: providerId,
      pact_contract_count: 1,
      latest_consumer_version: 'web-42',
      latest_status: 'failed',
    },
  ],
}

const matrix: CompatibilityMatrix = {
  provider_service_id: providerId,
  provider_name: '订单服务',
  provider_versions: ['2.0.0', '2.1.0', '2.2.0'],
  rows: [
    {
      pact_contract_version_id: pactId,
      consumer_service_id: consumerId,
      consumer_name: 'Web 前端',
      consumer_version: 'web-42',
      cells: [
        {
          provider_version: '2.0.0',
          status: 'passed',
          verification_id: 'verify-pass',
          verified_at: timestamp,
        },
        {
          provider_version: '2.1.0',
          status: 'failed',
          verification_id: 'verify-fail',
          verified_at: timestamp,
        },
        {
          provider_version: '2.2.0',
          status: 'pending',
          verification_id: null,
          verified_at: null,
        },
      ],
    },
  ],
}

const unsafeCheck: DeploymentCheck = {
  id: '00000000-0000-4000-8000-000000002705',
  project_id: project.id,
  provider_service_id: providerId,
  provider_version: '2.1.0',
  decision: 'unsafe',
  evidence: { blockers: [{ code: 'PACT_VERIFICATION_FAILED' }], pending: [] },
  checked_by_id: user.id,
  created_at: timestamp,
}

describe('ContractHubPage', () => {
  it('renders unified assets, graph, matrix, and persists a deployment decision', async () => {
    let checkPayload: Record<string, unknown> | null = null
    installHandlers()
    server.use(
      http.post(
        `/api/v1/projects/${project.id}/contract-hub/deployment-checks`,
        async ({ request }) => {
          checkPayload = (await request.json()) as Record<string, unknown>
          return HttpResponse.json({
            ...unsafeCheck,
            id: '00000000-0000-4000-8000-000000002706',
            provider_version: '2.3.0',
            decision: 'safe',
            evidence: { blockers: [], pending: [] },
          })
        },
      ),
    )
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByRole('heading', { name: '契约中心' })).toBeVisible()
    expect(await screen.findByText('Provider 2.1.0 不可安全发布')).toBeVisible()
    expect(screen.getByText(/1 项阻断证据/)).toBeVisible()
    expect(screen.getByText('Consumer · web-42')).toBeVisible()

    await chooseSelect(browser, screen.getByLabelText('提供方服务'), '订单服务')
    expect(await screen.findByRole('columnheader', { name: '订单服务 2.0.0' })).toBeVisible()
    expect(screen.getAllByText('通过').length).toBeGreaterThan(0)
    expect(screen.getAllByText('失败').length).toBeGreaterThan(0)
    expect(screen.getAllByText('待验证').length).toBeGreaterThan(0)

    await browser.type(screen.getByLabelText('待发布提供方版本'), '2.3.0')
    await browser.click(screen.getByRole('button', { name: '判断是否可安全发布' }))
    await waitFor(() =>
      expect(checkPayload).toEqual({
        provider_service_id: providerId,
        provider_version: '2.3.0',
      }),
    )

    await browser.click(screen.getByRole('tab', { name: /Pact/ }))
    expect(screen.getByText('Web 前端 → 订单服务')).toBeVisible()
    expect(screen.getByText('Pact Broker')).toBeVisible()
    await browser.click(screen.getByRole('tab', { name: /OpenAPI/ }))
    expect(screen.getByText('orders-openapi.json')).toBeVisible()
    expect(screen.getByText('订单服务 · 2.0.0')).toBeVisible()
  })

  it('submits service, Pact, Broker, OpenAPI, and provider verification dialogs', async () => {
    const payloads: Record<string, unknown> = {}
    installHandlers()
    server.use(
      http.post(`/api/v1/projects/${project.id}/contract-hub/services`, async ({ request }) => {
        payloads.service = await request.json()
        return HttpResponse.json(services[0], { status: 201 })
      }),
      http.post(`/api/v1/projects/${project.id}/contract-hub/pacts`, async ({ request }) => {
        const form = await request.formData()
        payloads.pactVersion = form.get('consumer_version')
        payloads.pactFile = (form.get('document') as File).name
        payloads.pactSource = form.get('source_name')
        return HttpResponse.json(pact, { status: 201 })
      }),
      http.post(
        `/api/v1/projects/${project.id}/contract-hub/pacts/import-broker`,
        async ({ request }) => {
          payloads.broker = await request.json()
          return HttpResponse.json(pact, { status: 201 })
        },
      ),
      http.post(`/api/v1/projects/${project.id}/contract-runs`, async ({ request }) => {
        const form = await request.formData()
        payloads.openapiProvider = form.get('provider_service_id')
        payloads.openapiVersion = form.get('provider_version')
        return HttpResponse.json(openapiRun, { status: 201 })
      }),
      http.post(
        `/api/v1/projects/${project.id}/contract-hub/pacts/${pactId}/verify`,
        async ({ request }) => {
          payloads.verification = await request.json()
          return HttpResponse.json({
            id: 'verify-1',
            project_id: project.id,
            pact_contract_version_id: pactId,
            provider_version: '2.4.0',
            target_base_url: 'http://orders-api:8080',
            status: 'passed',
            interaction_count: 3,
            passed_count: 3,
            failed_count: 0,
            results: [],
            verified_by_id: user.id,
            created_at: timestamp,
          })
        },
      ),
    )
    const rendered = renderPage()
    const browser = userEvent.setup()
    await screen.findByRole('heading', { name: '契约中心' })

    await browser.click(screen.getByRole('button', { name: /登记服务/ }))
    await browser.type(screen.getByLabelText('服务标识'), 'billing-api')
    await browser.type(screen.getByLabelText('显示名称'), '账单服务')
    await browser.type(screen.getByLabelText('说明'), '账单 Provider')
    await browser.click(screen.getByRole('button', { name: /^登\s*记$/ }))
    await waitFor(() => expect(payloads.service).toBeTruthy())

    await browser.click(screen.getByRole('button', { name: /导入 Pact/ }))
    const pactDialog = await modalByTitle('导入 Pact 文档')
    const pactFile = new File(['{}'], 'web-orders.json', { type: 'application/json' })
    await browser.upload(
      pactDialog.querySelector('input[type="file"]') as HTMLInputElement,
      pactFile,
    )
    await browser.type(within(pactDialog).getByLabelText('消费者版本'), 'web-43')
    await browser.click(within(pactDialog).getByRole('button', { name: /^导\s*入$/ }))
    await waitFor(() => expect(payloads.pactFile).toBe('blob'))
    expect(payloads.pactVersion).toBe('web-43')
    expect(payloads.pactSource).toBe('web-orders.json')

    await browser.click(await screen.findByRole('button', { name: /从 Broker 导入/ }))
    const brokerDialog = await modalByTitle('从 Pact Broker 导入')
    await browser.type(within(brokerDialog).getByLabelText('Consumer'), 'Web 前端')
    await browser.type(within(brokerDialog).getByLabelText('Provider'), '订单服务')
    await browser.type(within(brokerDialog).getByLabelText('消费者版本'), 'web-44')
    await browser.click(within(brokerDialog).getByRole('button', { name: /^导\s*入$/ }))
    await waitFor(() =>
      expect(payloads.broker).toEqual({
        consumer: 'Web 前端',
        provider: '订单服务',
        consumer_version: 'web-44',
      }),
    )

    await browser.click(screen.getByRole('button', { name: /导入 OpenAPI/ }))
    const openapiDialog = await modalByTitle('导入并绑定 OpenAPI')
    const openapiFile = new File(['{}'], 'orders.json', { type: 'application/json' })
    await browser.upload(
      openapiDialog.querySelector('input[type="file"]') as HTMLInputElement,
      openapiFile,
    )
    await chooseSelect(browser, within(openapiDialog).getByLabelText('提供方服务'), '订单服务')
    await browser.type(within(openapiDialog).getByLabelText('提供方版本'), '2.4.0')
    await browser.click(within(openapiDialog).getByRole('button', { name: /^导\s*入$/ }))
    await waitFor(() => expect(payloads.openapiProvider).toBe(providerId))
    expect(payloads.openapiVersion).toBe('2.4.0')

    await browser.click(screen.getByRole('button', { name: /执行提供方验证/ }))
    const verificationDialog = await modalByTitle('执行提供方验证')
    await chooseSelect(
      browser,
      within(verificationDialog).getByLabelText('Pact 契约'),
      'Web 前端 web-42 → 订单服务',
    )
    await browser.type(
      verificationDialog.querySelector('input#provider_version') as HTMLInputElement,
      '2.4.0',
    )
    await browser.type(
      verificationDialog.querySelector('input#target_base_url') as HTMLInputElement,
      'http://orders-api:8080',
    )
    await browser.click(within(verificationDialog).getByRole('button', { name: /执\s*行验证/ }))
    await waitFor(() =>
      expect(payloads.verification).toEqual({
        provider_version: '2.4.0',
        target_base_url: 'http://orders-api:8080',
      }),
    )
    rendered.unmount()
  })

  it('shows empty and unbound states when no contract evidence exists', async () => {
    installHandlers({ empty: true })
    renderPage()

    expect(await screen.findByText('导入 Pact 后生成服务依赖图')).toBeVisible()
    expect(screen.getByText('暂无不可安全发布的判断')).toBeVisible()
    expect(screen.queryByRole('button', { name: /从 Broker 导入/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /执行提供方验证/ })).toBeDisabled()
    expect(screen.getByText('请先选择提供方')).toBeVisible()
  })
})

describe('contract hub presentational branches', () => {
  it('renders statuses, decisions, empty graphs, and both contract kinds', () => {
    render(
      <AntdApp>
        <CompatibilityStatus status="passed" />
        <CompatibilityStatus status="failed" />
        <CompatibilityStatus status="pending" />
        <DecisionTag decision="safe" />
        <DecisionTag decision="unsafe" />
        <DecisionTag decision="unknown" />
        <ContractOverview loading={false} />
        <ServiceGraphPanel graph={{ nodes: [], edges: [] }} loading={false} />
        <FailedEvidencePanel checks={[]} />
        <UnifiedContractsPanel
          services={services}
          pacts={[{ ...pact, source_type: 'upload' }]}
          openapiRuns={[
            {
              ...openapiRun,
              provider_service_id: null,
              provider_version: null,
              breaking_changes: [
                {
                  code: 'PATH_REMOVED',
                  severity: 'breaking',
                  operation_key: 'GET /orders',
                  path: '/orders',
                  message: '路径被移除',
                  before: true,
                  after: null,
                },
              ],
            },
          ]}
          loading={false}
        />
      </AntdApp>,
    )

    expect(screen.getByText('可安全发布')).toBeVisible()
    expect(screen.getByText('证据不足')).toBeVisible()
    expect(screen.getByText('未绑定')).toBeVisible()
    expect(screen.getByText('1 项')).toBeVisible()
    fireEvent.click(screen.getByRole('tab', { name: /Pact/ }))
    expect(screen.getByText('本地上传')).toBeVisible()
  })
})

function installHandlers({ empty = false }: { empty?: boolean } = {}) {
  const page = <T,>(items: T[]) => ({ items, total: items.length, page: 1, page_size: 100 })
  server.use(
    http.get('/api/v1/projects', () => HttpResponse.json(page([project]))),
    http.get(`/api/v1/projects/${project.id}/contract-hub/services`, () =>
      HttpResponse.json(page(empty ? [] : services)),
    ),
    http.get(`/api/v1/projects/${project.id}/contract-hub/pacts`, () =>
      HttpResponse.json(page(empty ? [] : [pact])),
    ),
    http.get(`/api/v1/projects/${project.id}/contract-runs`, () =>
      HttpResponse.json(page(empty ? [] : [openapiRun])),
    ),
    http.get(`/api/v1/projects/${project.id}/contract-hub/summary`, () =>
      HttpResponse.json(
        empty
          ? {
              service_count: 0,
              openapi_contract_count: 0,
              pact_contract_count: 0,
              pending_verification_count: 0,
              failed_verification_count: 0,
              breaking_change_count: 0,
              broker_available: false,
            }
          : summary,
      ),
    ),
    http.get(`/api/v1/projects/${project.id}/contract-hub/service-graph`, () =>
      HttpResponse.json(empty ? { nodes: [], edges: [] } : graph),
    ),
    http.get(`/api/v1/projects/${project.id}/contract-hub/compatibility/${providerId}`, () =>
      HttpResponse.json(matrix),
    ),
    http.get(`/api/v1/projects/${project.id}/contract-hub/deployment-checks`, () =>
      HttpResponse.json(page(empty ? [] : [unsafeCheck])),
    ),
  )
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <ProjectTestProvider section="contracts">
          <ContractHubPage />
        </ProjectTestProvider>
      </QueryClientProvider>
    </AntdApp>,
  )
}

async function chooseSelect(
  browser: ReturnType<typeof userEvent.setup>,
  input: HTMLElement,
  option: string,
) {
  await browser.click(input)
  await browser.click(
    await screen.findByText(option, { selector: '.ant-select-item-option-content' }),
  )
}

async function modalByTitle(title: string): Promise<HTMLElement> {
  const titleElement = await screen.findByText(title, { selector: '.ant-modal-title' })
  const dialog = titleElement.closest('[role="dialog"]')
  if (!(dialog instanceof HTMLElement)) throw new Error(`未找到弹窗：${title}`)
  return dialog
}
