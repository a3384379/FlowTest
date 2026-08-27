import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import type { ApiDefinition, Environment, RequestService, ServiceEndpoint } from '../lib/api'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { apiDefinition, environment, project, user } from '../test/fixtures'
import { server } from '../test/server'
import RequestTargetsPage from './RequestTargetsPage'

const service: RequestService = {
  id: '00000000-0000-4000-8000-000000004001',
  project_id: project.id,
  service_key: 'orders',
  name: '订单服务',
  description: '请求目标服务',
  owner_team: null,
  service_type: 'https',
  enabled: true,
  created_by_id: user.id,
  created_at: '2026-08-22T08:00:00Z',
  updated_at: '2026-08-22T08:00:00Z',
}

const targetEnvironment: Environment = {
  ...environment,
  default_service_id: service.id,
}

const endpoint: ServiceEndpoint = {
  id: '00000000-0000-4000-8000-000000004002',
  project_id: project.id,
  environment_id: environment.id,
  service_id: service.id,
  variant: 'default',
  base_url: 'https://orders.example.com',
  enabled: true,
  connect_timeout_ms: 5000,
  read_timeout_ms: 30000,
  tls_verify: true,
  proxy_ref: null,
  headers: {},
  variables: {},
  secret_refs: [],
  health_check_path: null,
  health_expected_status: null,
  revision: 1,
  created_by_id: user.id,
  created_at: '2026-08-22T08:00:00Z',
  updated_at: '2026-08-22T08:00:00Z',
}

describe('RequestTargetsPage', () => {
  it('manages services, endpoint variants, environment defaults, and API bindings', async () => {
    let services = [service]
    let environments = [targetEnvironment]
    let endpoints = [endpoint]
    const api: ApiDefinition = { ...apiDefinition, service_id: service.id }
    let servicePayload: Record<string, unknown> | null = null
    let endpointPayload: Record<string, unknown> | null = null
    let defaultPayload: Record<string, unknown> | null = null
    let apiPayload: Record<string, unknown> | null = null
    let serviceUpdatePayload: Record<string, unknown> | null = null
    server.use(
      projectHandlers(),
      http.get(`/api/v1/projects/${project.id}/environments`, () =>
        HttpResponse.json(environments),
      ),
      http.get(`/api/v1/projects/${project.id}/services`, () => HttpResponse.json(services)),
      http.get(`/api/v1/projects/${project.id}/secrets`, () =>
        HttpResponse.json([
          {
            id: 'secret-1',
            project_id: project.id,
            environment_id: null,
            name: 'orders-token',
            created_by_id: user.id,
            created_at: '2026-08-22T08:00:00Z',
            updated_at: '2026-08-22T08:00:00Z',
          },
        ]),
      ),
      http.get(
        `/api/v1/projects/${project.id}/environments/${environment.id}/service-endpoints`,
        () => HttpResponse.json(endpoints),
      ),
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({ items: [api], total: 1, page: 1, page_size: 100 }),
      ),
      http.post(`/api/v1/projects/${project.id}/services`, async ({ request }) => {
        servicePayload = (await request.json()) as Record<string, unknown>
        const created = { ...service, id: '00000000-0000-4000-8000-000000004003' }
        services = [...services, created]
        return HttpResponse.json(created, { status: 201 })
      }),
      http.get(`/api/v1/projects/${project.id}/services/${service.id}/impact-preview`, () =>
        HttpResponse.json({
          strategy: 'request_target_dependency_v1',
          service_id: service.id,
          service_key: service.service_key,
          affected_apis: [{ id: api.id, name: api.name, reason: 'API 默认 Service' }],
          affected_workflows: [],
          affected_test_plans: [],
          affected_scheduled_runs: [],
          affected_release_gates: [],
        }),
      ),
      http.patch(`/api/v1/projects/${project.id}/services/${service.id}`, async ({ request }) => {
        serviceUpdatePayload = (await request.json()) as Record<string, unknown>
        services = [{ ...service, ...serviceUpdatePayload } as RequestService]
        return HttpResponse.json(services[0])
      }),
      http.post(
        `/api/v1/projects/${project.id}/environments/${environment.id}/service-endpoints`,
        async ({ request }) => {
          endpointPayload = (await request.json()) as Record<string, unknown>
          endpoints = [...endpoints, { ...endpoint, id: '00000000-0000-4000-8000-000000004004' }]
          return HttpResponse.json(endpoints.at(-1), { status: 201 })
        },
      ),
      http.patch(
        `/api/v1/projects/${project.id}/environments/${environment.id}`,
        async ({ request }) => {
          defaultPayload = (await request.json()) as Record<string, unknown>
          environments = [{ ...targetEnvironment, default_service_id: null }]
          return HttpResponse.json(environments[0])
        },
      ),
      http.patch(`/api/v1/projects/${project.id}/apis/${api.id}`, async ({ request }) => {
        apiPayload = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...api, service_id: null })
      }),
    )
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByRole('heading', { name: '请求目标' })).toBeVisible()
    expect(await screen.findByText('订单服务')).toBeVisible()
    expect(await screen.findByText('https://orders.example.com')).toBeVisible()
    expect(screen.getByText('环境默认 Service')).toBeVisible()

    await browser.type(screen.getByPlaceholderText('orders'), 'orders-new')
    await browser.type(screen.getByPlaceholderText('订单服务'), '副本')
    await browser.click(screen.getByRole('button', { name: /创建 Service/ }))
    await waitFor(() => expect(servicePayload).toMatchObject({ service_key: 'orders-new' }))

    const environmentSelect = screen
      .getByRole('combobox', { name: '环境默认 Service' })
      .closest('.ant-select') as HTMLElement | null
    await browser.click(within(environmentSelect!).getByRole('img', { name: 'close-circle' }))
    await waitFor(() => expect(defaultPayload).toEqual({ default_service_id: null }))

    await browser.click(screen.getByRole('combobox', { name: 'Endpoint Service' }))
    await chooseOption(browser, '订单服务 · orders')
    await browser.type(
      screen.getByRole('textbox', { name: 'Endpoint Base URL' }),
      'https://orders.example.com',
    )
    await browser.click(screen.getByRole('button', { name: '添加 Endpoint' }))
    await waitFor(() => expect(endpointPayload).toMatchObject({ variant: 'default' }))

    await browser.click(screen.getByRole('combobox', { name: '查询当前用户 默认 Service' }))
    await chooseOption(browser, '订单服务 · orders')
    await waitFor(() =>
      expect(apiPayload).toEqual({ service_id: '00000000-0000-4000-8000-000000004003' }),
    )

    await browser.click(screen.getAllByRole('button', { name: /影响预览 \/ 编辑/ })[0])
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('保存前请确认下游影响')).toBeInTheDocument()
    expect(within(dialog).getByText(`1: ${api.name}`)).toBeInTheDocument()
    await browser.click(within(dialog).getByRole('switch', { name: 'Enable / Disable Service' }))
    await browser.click(within(dialog).getByRole('button', { name: '保存变更' }))
    await waitFor(() => expect(serviceUpdatePayload).toMatchObject({ enabled: false }))
  })

  it('shows a standard error envelope when the target data cannot be loaded', async () => {
    server.use(
      projectHandlers(),
      http.get(`/api/v1/projects/${project.id}/environments`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'TARGET_READ_FAILED',
              message: '读取目标失败',
              trace_id: 'trace-target',
            },
          },
          { status: 503 },
        ),
      ),
      http.get(`/api/v1/projects/${project.id}/services`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${project.id}/secrets`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
    )
    renderPage()

    expect(await screen.findByText('请求目标加载失败')).toBeVisible()
    expect(screen.getByText('读取目标失败')).toBeVisible()
  })
})

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <ProjectTestProvider section="request-targets">
          <RequestTargetsPage />
        </ProjectTestProvider>
      </QueryClientProvider>
    </AntdApp>,
  )
}

function projectHandlers() {
  return http.get('/api/v1/projects', () =>
    HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
  )
}

async function chooseOption(browser: ReturnType<typeof userEvent.setup>, label: string) {
  const options = await screen.findAllByText(label)
  await browser.click(options[options.length - 1])
}
