import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import type {
  ContractHubSummary,
  ServiceCatalogEntry,
  ServiceGraph,
} from '../features/contracts/contract-hub-service'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { project, user } from '../test/fixtures'
import { server } from '../test/server'
import ServiceCatalogPage from './ServiceCatalogPage'

const timestamp = '2026-08-14T08:00:00Z'
const consumerId = '00000000-0000-4000-8000-000000003101'
const providerId = '00000000-0000-4000-8000-000000003102'

const initialServices: ServiceCatalogEntry[] = [
  service(consumerId, 'web-client', 'Web 前端', 'Pact Consumer'),
  service(providerId, 'orders-api', '订单服务', 'OpenAPI Provider'),
]

const graph: ServiceGraph = {
  nodes: [
    {
      id: consumerId,
      service_key: 'web-client',
      display_name: 'Web 前端',
      contract_kinds: ['pact'],
    },
    {
      id: providerId,
      service_key: 'orders-api',
      display_name: '订单服务',
      contract_kinds: ['openapi', 'pact'],
    },
  ],
  edges: [
    {
      consumer_service_id: consumerId,
      provider_service_id: providerId,
      pact_contract_count: 1,
      latest_consumer_version: 'web-42',
      latest_status: 'passed',
    },
  ],
}

describe('ServiceCatalogPage', () => {
  it('shows real catalog evidence, focuses search deep-links, filters, and creates a service', async () => {
    let services = [...initialServices]
    let createPayload: Record<string, unknown> | null = null
    installFeatureHandler(true)
    server.use(
      http.get(`/api/v1/projects/${project.id}/contract-hub/services`, () =>
        HttpResponse.json({ items: services, total: services.length, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/contract-hub/summary`, () =>
        HttpResponse.json(summary(services.length)),
      ),
      http.get(`/api/v1/projects/${project.id}/contract-hub/service-graph`, () =>
        HttpResponse.json(graph),
      ),
      http.post(`/api/v1/projects/${project.id}/contract-hub/services`, async ({ request }) => {
        createPayload = (await request.json()) as Record<string, unknown>
        const created = service(
          '00000000-0000-4000-8000-000000003103',
          'billing-api',
          '账单服务',
          '收费域服务',
        )
        services = [...services, created]
        return HttpResponse.json(created, { status: 201 })
      }),
    )
    renderPage(`?focus=contract_service:${providerId}`)
    const browser = userEvent.setup()

    expect(await screen.findByRole('heading', { name: '服务目录' })).toBeVisible()
    expect(await screen.findByText('Web 前端')).toBeVisible()
    expect(screen.getByText('订单服务')).toBeVisible()
    expect(screen.getByText('消费方')).toBeVisible()
    expect(screen.getByText('提供方')).toBeVisible()
    expect(screen.getByText('OpenAPI')).toBeVisible()
    expect(screen.getAllByText('Pact').length).toBeGreaterThan(0)
    expect(screen.getByText('服务数量').closest('.ant-card')).toHaveTextContent('2')
    expect(screen.getByRole('row', { name: /订单服务/ })).toHaveClass('service-catalog-row-focused')

    await browser.type(screen.getByLabelText('搜索服务'), 'web')
    expect(screen.getByText('Web 前端')).toBeVisible()
    expect(screen.queryByText('订单服务')).not.toBeInTheDocument()
    await browser.clear(screen.getByLabelText('搜索服务'))

    await browser.click(screen.getByRole('button', { name: /新建服务/ }))
    const dialog = screen.getByRole('dialog', { name: '新建服务' })
    await browser.type(within(dialog).getByLabelText('服务标识'), 'Billing API')
    await browser.type(within(dialog).getByLabelText('显示名称'), '账单服务')
    await browser.click(within(dialog).getByRole('button', { name: '登记服务' }))
    expect(await within(dialog).findByText('服务标识格式不正确')).toBeInTheDocument()
    expect(within(dialog).getByLabelText('服务标识')).toHaveAttribute('aria-invalid', 'true')
    expect(createPayload).toBeNull()

    await browser.clear(within(dialog).getByLabelText('服务标识'))
    await browser.type(within(dialog).getByLabelText('服务标识'), 'billing-api')
    await browser.type(within(dialog).getByLabelText('服务描述'), '收费域服务')
    await browser.click(within(dialog).getByRole('button', { name: '登记服务' }))

    await waitFor(() =>
      expect(createPayload).toEqual({
        service_key: 'billing-api',
        display_name: '账单服务',
        description: '收费域服务',
      }),
    )
    expect(await screen.findByText('账单服务')).toBeVisible()
    expect(screen.getByText('服务数量').closest('.ant-card')).toHaveTextContent('3')
  })

  it('keeps the route visible without calling disabled Contract Hub APIs', async () => {
    let catalogReads = 0
    installFeatureHandler(false)
    server.use(
      http.get(`/api/v1/projects/${project.id}/contract-hub/services`, () => {
        catalogReads += 1
        return HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 })
      }),
    )
    renderPage()

    expect(await screen.findByText('Contract Hub 未启用')).toBeVisible()
    expect(screen.getByRole('button', { name: /新建服务/ })).toBeDisabled()
    expect(screen.getByText('功能未启用')).toBeVisible()
    expect(catalogReads).toBe(0)
  })

  it('keeps the catalog read-only for project viewers', async () => {
    installFeatureHandler(true)
    server.use(
      http.get(`/api/v1/projects/${project.id}/contract-hub/services`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/contract-hub/summary`, () =>
        HttpResponse.json(summary(0)),
      ),
      http.get(`/api/v1/projects/${project.id}/contract-hub/service-graph`, () =>
        HttpResponse.json({ nodes: [], edges: [] }),
      ),
    )
    renderPage('', { ...project, role: 'viewer' })

    const createButton = await screen.findByRole('button', { name: /新建服务/ })
    expect(createButton).toBeDisabled()
    expect(createButton).toHaveAttribute('title', '查看者无权登记服务')
    expect(await screen.findByText('暂无匹配服务')).toBeVisible()
  })
})

function renderPage(search = '', visibleProject = project) {
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [visibleProject], total: 1, page: 1, page_size: 100 }),
    ),
  )
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <ProjectTestProvider
          section="services"
          initialEntry={`/projects/${project.id}/services${search}`}
        >
          <ServiceCatalogPage />
        </ProjectTestProvider>
      </QueryClientProvider>
    </AntdApp>,
  )
}

function installFeatureHandler(enabled: boolean): void {
  server.use(
    http.get('/api/v1/v3/features', () =>
      HttpResponse.json({
        capability_sdk: true,
        plugin_registry: false,
        runner_fabric: true,
        multi_protocol: true,
        event_protocols: true,
        performance_lab: true,
        environment_lab: true,
        contract_hub: enabled,
        impact_engine: true,
        quality_intelligence: true,
        pact_broker: false,
      }),
    ),
  )
}

function service(
  id: string,
  serviceKey: string,
  displayName: string,
  description: string,
): ServiceCatalogEntry {
  return {
    id,
    project_id: project.id,
    service_key: serviceKey,
    display_name: displayName,
    description,
    created_by_id: user.id,
    created_at: timestamp,
    updated_at: timestamp,
  }
}

function summary(serviceCount: number): ContractHubSummary {
  return {
    service_count: serviceCount,
    openapi_contract_count: 1,
    pact_contract_count: 1,
    pending_verification_count: 0,
    failed_verification_count: 0,
    breaking_change_count: 0,
    broker_available: false,
  }
}
