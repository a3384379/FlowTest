import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
      http.get(`/api/v1/projects/${project.id}/contract-hub/services`, ({ request }) => {
        const search = new URL(request.url).searchParams.get('search')?.toLowerCase() ?? ''
        const items = services.filter((item) =>
          [item.display_name, item.service_key, item.description].some((value) =>
            value.toLowerCase().includes(search),
          ),
        )
        return HttpResponse.json({ items, total: items.length, page: 1, page_size: 20 })
      }),
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
    const list = within(screen.getByLabelText('服务目录列表'))
    expect(await list.findByText('Web 前端')).toBeVisible()
    expect(list.getByText('订单服务')).toBeVisible()
    expect(screen.getByText('消费方')).toBeVisible()
    expect(list.getByText('提供方')).toBeVisible()
    expect(list.getByText('OpenAPI')).toBeVisible()
    expect(screen.getAllByText('Pact').length).toBeGreaterThan(0)
    expect(screen.getByText('服务数量').closest('.ant-card')).toHaveTextContent('2')
    expect(list.getByRole('row', { name: /订单服务/ })).toHaveClass('service-catalog-row-focused')

    await browser.type(screen.getByLabelText('搜索服务'), 'web{Enter}')
    await waitFor(() => expect(list.queryByText('订单服务')).not.toBeInTheDocument())
    expect(list.getByText('Web 前端')).toBeVisible()
    expect(within(screen.getByLabelText('选中服务详情')).getByText('订单服务')).toBeInTheDocument()
    await browser.clear(screen.getByLabelText('搜索服务'))
    await browser.keyboard('{Enter}')

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

  it('reads a selected service outside the visible page and keeps it through server searches', async () => {
    const services = Array.from({ length: 105 }, (_, index) =>
      service(
        `00000000-0000-4000-8000-${String(4000 + index).padStart(12, '0')}`,
        `service-${index}`,
        `完整目录${index}`,
        '真实服务端范围',
      ),
    )
    const requests: URLSearchParams[] = []
    installFeatureHandler(true)
    server.use(
      http.get(`/api/v1/projects/${project.id}/contract-hub/services`, ({ request }) => {
        const params = new URL(request.url).searchParams
        requests.push(params)
        const matching = services.filter((item) =>
          item.display_name.includes(params.get('search') ?? ''),
        )
        const page = Number(params.get('page') ?? 1)
        return HttpResponse.json({
          items: matching.slice((page - 1) * 20, page * 20),
          total: matching.length,
          page,
          page_size: 20,
        })
      }),
      http.get(`/api/v1/projects/${project.id}/contract-hub/services/:serviceId`, ({ params }) =>
        HttpResponse.json(services.find((item) => item.id === params.serviceId)),
      ),
      http.get(`/api/v1/projects/${project.id}/contract-hub/summary`, () =>
        HttpResponse.json(summary(105)),
      ),
      http.get(`/api/v1/projects/${project.id}/contract-hub/service-graph`, () =>
        HttpResponse.json({ nodes: [], edges: [] }),
      ),
    )
    renderPage(`?contractServiceId=${services[104].id}&servicePage=6`)
    const details = await screen.findByLabelText('选中服务详情')
    expect(await within(details).findByText('service-104')).toBeInTheDocument()
    expect(requests.at(-1)?.get('page')).toBe('6')
    const browser = userEvent.setup()
    await browser.type(screen.getByLabelText('搜索服务'), '完整目录0{Enter}')
    await waitFor(() => expect(requests.at(-1)?.get('search')).toBe('完整目录0'))
    expect(requests.at(-1)?.get('page')).toBe('1')
    expect(within(details).getByText('service-104')).toBeInTheDocument()
    expect(await screen.findByText('完整目录0')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '查看服务契约' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/contracts?contractServiceId=${services[104].id}`,
    )
    expect(screen.getByRole('link', { name: '查看服务影响' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/impact?contractServiceId=${services[104].id}`,
    )
  })

  it('shows a failed exact lookup instead of selecting a visible different service', async () => {
    installFeatureHandler(true)
    server.use(
      http.get(`/api/v1/projects/${project.id}/contract-hub/services`, () =>
        HttpResponse.json({ items: [initialServices[0]], total: 1, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/contract-hub/summary`, () =>
        HttpResponse.json(summary(1)),
      ),
      http.get(`/api/v1/projects/${project.id}/contract-hub/service-graph`, () =>
        HttpResponse.json({ nodes: [], edges: [] }),
      ),
      http.get(`/api/v1/projects/${project.id}/contract-hub/services/${providerId}`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'SERVICE_CATALOG_ENTRY_NOT_FOUND',
              message: '服务目录项不存在',
              trace_id: 'service-missing',
            },
          },
          { status: 404 },
        ),
      ),
    )
    renderPage(`?contractServiceId=${providerId}`)
    expect(await screen.findByText('服务目录项不存在')).toBeInTheDocument()
    const detail = within(screen.getByLabelText('选中服务详情'))
    expect(detail.queryByText('Web 前端')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '查看服务契约' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试' })).toBeEnabled()
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

  it('uses fresh capabilities and preserves the draft while revoked editing disables submit', async () => {
    installFeatureHandler(true)
    let editable = true
    let writes = 0
    server.use(
      http.get(`/api/v1/projects/${project.id}/permissions`, () =>
        HttpResponse.json({
          effective_role: editable ? 'owner' : 'viewer',
          capabilities: editable ? ['read', 'edit'] : ['read'],
          matrix: {},
        }),
      ),
      http.get(`/api/v1/projects/${project.id}/contract-hub/services`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/contract-hub/summary`, () =>
        HttpResponse.json(summary(0)),
      ),
      http.get(`/api/v1/projects/${project.id}/contract-hub/service-graph`, () =>
        HttpResponse.json({ nodes: [], edges: [] }),
      ),
      http.post(`/api/v1/projects/${project.id}/contract-hub/services`, () => {
        writes += 1
        return HttpResponse.json({})
      }),
    )
    const { queryClient } = renderPage()
    const open = screen.getByRole('button', { name: /新建服务/ })
    await waitFor(() => expect(open).toBeEnabled())
    await userEvent.click(open)
    const dialog = within(screen.getByRole('dialog', { name: '新建服务' }))
    fireEvent.change(dialog.getByLabelText('服务标识'), { target: { value: 'audit-revoked' } })
    fireEvent.change(dialog.getByLabelText('显示名称'), { target: { value: '权限撤销时保留草稿' } })
    editable = false
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ['project-permissions', project.id] })
    })
    const submit = dialog.getByRole('button', { name: '登记服务' })
    await waitFor(() => expect(submit).toBeDisabled())
    expect(dialog.getByLabelText('显示名称')).toBeDisabled()
    expect(dialog.getByLabelText('显示名称')).toHaveValue('权限撤销时保留草稿')
    fireEvent.click(submit)
    expect(writes).toBe(0)
  })

  it('keeps the catalog read-only for project viewers', async () => {
    installFeatureHandler(true)
    server.use(
      http.get(`/api/v1/projects/${project.id}/permissions`, () =>
        HttpResponse.json({ effective_role: 'viewer', capabilities: ['read'], matrix: {} }),
      ),
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
    await waitFor(() => expect(createButton).toHaveAttribute('title', '当前权限不能登记服务'))
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
  const view = render(
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
  return { ...view, queryClient }
}

function installFeatureHandler(enabled: boolean): void {
  server.use(
    http.get(`/api/v1/projects/${project.id}/contract-hub/services/:serviceId/versions`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
    ),
    http.get(`/api/v1/projects/${project.id}/contract-hub/services/:serviceId`, ({ params }) =>
      HttpResponse.json(initialServices.find((item) => item.id === params.serviceId)),
    ),
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
