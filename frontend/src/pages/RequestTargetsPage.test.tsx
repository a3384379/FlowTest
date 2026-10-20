import { useApiConsole } from '../features/api-console/use-api-console'
import type { ApiVersion } from '../lib/api'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { ApiDefinition, Environment, RequestService, ServiceEndpoint } from '../lib/api'
import { useAuthStore } from '../features/auth/auth-store'
import { authenticateTestUser } from '../test/auth'
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
  beforeEach(() => {
    localStorage.clear()
    authenticateTestUser(user)
    server.use(
      http.post(`/api/v1/projects/${project.id}/request-targets/impact-preview`, () =>
        HttpResponse.json({
          scope_kind: 'endpoint',
          scope_id: endpoint.id,
          complete: true,
          trace_id: 'impact-test',
          diagnostics: [],
          affected_apis: [],
          affected_workflows: [],
          affected_test_plans: [],
          affected_scheduled_runs: [],
          affected_release_gates: [],
        }),
      ),
      http.post(`/api/v1/projects/${project.id}/request-targets/preview`, () =>
        HttpResponse.json({
          before: unavailableResolution,
          after: unavailableResolution,
          persisted: false,
          network_checked: false,
        }),
      ),
    )
  })
  afterEach(() => {
    localStorage.clear()
    useAuthStore.setState({ user: null })
  })

  it('keeps a conflicted API binding candidate until explicitly reloading and reviewing the latest revision', async () => {
    let currentVersion = 1
    const writes: Array<{ base_version?: number; service_id?: string }> = []
    const previews: Array<{ base_version?: number }> = []
    installTargetCatalog(() => [targetEnvironment])
    server.use(
      http.post(`/api/v1/projects/${project.id}/request-targets/preview`, async ({ request }) => {
        const input = (await request.json()) as { change: { base_version?: number } }
        previews.push(input.change)
        return HttpResponse.json({
          before: unavailableResolution,
          after: unavailableResolution,
          persisted: false,
          network_checked: false,
        })
      }),
      http.patch(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}`, async ({ request }) => {
        const body = (await request.json()) as { base_version?: number; service_id?: string }
        writes.push(body)
        if (body.base_version !== currentVersion)
          return HttpResponse.json(
            {
              error: {
                code: 'API_VERSION_CONFLICT',
                message: '接口已有新版本,请读取最新版本并重新分析候选',
                details: { current_version: currentVersion },
                trace_id: 'binding-revision-trace',
              },
            },
            { status: 409 },
          )
        currentVersion += 1
        return HttpResponse.json({
          ...apiDefinition,
          current_version: currentVersion,
          service_id: body.service_id,
        })
      }),
      http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}`, () =>
        HttpResponse.json({
          definition: { ...apiDefinition, current_version: currentVersion },
          version: {
            id: '00000000-0000-4000-8000-000000001231',
            api_definition_id: apiDefinition.id,
            version: currentVersion,
            method: 'GET',
            path: '/users/new',
            headers: {},
            variables: {},
            query_parameters: [],
            body_kind: 'none',
            body: null,
            auth_kind: 'none',
            auth_config: {},
            extraction_rules: [],
            assertions: [],
            created_at: '2026-10-21T00:00:00Z',
          },
        }),
      ),
    )
    renderPage()
    const browser = userEvent.setup()
    await browser.click(
      await screen.findByRole('combobox', { name: `${apiDefinition.name} 默认服务` }),
    )
    await chooseOption(browser, '订单服务 · orders')
    const dialog = await screen.findByRole('dialog')
    await waitFor(() =>
      expect(within(dialog).getByRole('button', { name: '确认保存' })).toBeEnabled(),
    )
    expect(previews.at(-1)?.base_version).toBe(1)
    currentVersion = 2
    await browser.click(within(dialog).getByRole('button', { name: '确认保存' }))
    await screen.findByText('接口已有新版本,请读取最新版本并重新分析候选')
    expect(writes).toEqual([{ service_id: service.id, base_version: 1 }])
    expect(currentVersion).toBe(2)
    expect(within(dialog).getByRole('button', { name: '确认保存' })).toBeDisabled()
    expect(screen.getByText(/binding-revision-trace/)).toBeInTheDocument()
    await browser.click(within(dialog).getByRole('button', { name: '读取最新版本并重新分析' }))
    await waitFor(() => expect(previews.at(-1)?.base_version).toBe(2))
    const refreshed = screen.getByRole('dialog')
    await waitFor(() =>
      expect(within(refreshed).getByRole('button', { name: '确认保存' })).toBeEnabled(),
    )
    expect(writes).toHaveLength(1)
    await browser.click(within(refreshed).getByRole('button', { name: '确认保存' }))
    await waitFor(() => expect(writes).toHaveLength(2))
    expect(writes[1]).toEqual({ service_id: service.id, base_version: 2 })
    expect(currentVersion).toBe(3)
    await waitFor(() => expect(refreshed).not.toBeInTheDocument())
  })

  it('ignores a late revision reload after its candidate was cancelled and a new review opened', async () => {
    let release: () => void = () => {}
    let started = false
    const pending = new Promise<void>((resolve) => {
      release = resolve
    })
    installTargetCatalog(() => [targetEnvironment])
    server.use(
      http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}`, async () => {
        started = true
        await pending
        return HttpResponse.json({
          definition: { ...apiDefinition, current_version: 9 },
          version: {
            id: '00000000-0000-4000-8000-000000001239',
            api_definition_id: apiDefinition.id,
            version: 9,
            method: 'GET',
            path: '/users/new',
            headers: {},
            variables: {},
            query_parameters: [],
            body_kind: 'none',
            body: null,
            auth_kind: 'none',
            auth_config: {},
            extraction_rules: [],
            assertions: [],
            created_at: '2026-10-21T00:00:00Z',
          },
        })
      }),
    )
    const view = renderPage()
    const browser = userEvent.setup()
    await browser.click(
      await screen.findByRole('combobox', { name: `${apiDefinition.name} 默认服务` }),
    )
    await chooseOption(browser, '订单服务 · orders')
    const old = await screen.findByRole('dialog')
    await waitFor(() => expect(within(old).getByRole('button', { name: '确认保存' })).toBeEnabled())
    await browser.click(within(old).getByRole('button', { name: '读取最新版本并重新分析' }))
    await waitFor(() => expect(started).toBe(true))
    await browser.click(within(old).getByRole('button', { name: '取消候选' }))
    await waitFor(() => expect(old).not.toBeInTheDocument())
    expect(
      screen
        .getByRole('combobox', { name: `${apiDefinition.name} 默认服务` })
        .closest('.ant-select'),
    ).not.toHaveTextContent('订单服务')
    await browser.click(screen.getByRole('combobox', { name: `${apiDefinition.name} 默认服务` }))
    await chooseOption(browser, '订单服务 · orders')
    const current = await screen.findByRole('dialog')
    await waitFor(() =>
      expect(within(current).getByRole('button', { name: '确认保存' })).toBeEnabled(),
    )
    release()
    await waitFor(() => expect(view.queryClient.isMutating()).toBe(0))
    expect(within(current).getByText('已锁定接口当前版本 v1')).toBeInTheDocument()
    expect(screen.queryByText('已锁定接口当前版本 v9')).not.toBeInTheDocument()
  })

  it('allows viewers to review target impact while keeping forms and bindings read-only', async () => {
    let writes = 0
    server.use(
      projectHandlers(),
      http.get(`/api/v1/projects/${project.id}/permissions`, () =>
        HttpResponse.json({ effective_role: 'viewer', capabilities: ['read'], matrix: {} }),
      ),
      http.get(`/api/v1/projects/${project.id}/environments`, () =>
        HttpResponse.json([targetEnvironment]),
      ),
      http.get(`/api/v1/projects/${project.id}/services`, () => HttpResponse.json([service])),
      http.get(`/api/v1/projects/${project.id}/secrets`, () => HttpResponse.json([])),
      http.get(
        `/api/v1/projects/${project.id}/environments/${environment.id}/service-endpoints`,
        () => HttpResponse.json([endpoint]),
      ),
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({ items: [apiDefinition], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/services/${service.id}/impact-preview`, () =>
        HttpResponse.json({
          strategy: 'request_target_dependency_v1',
          service_id: service.id,
          service_key: service.service_key,
          affected_apis: [],
          affected_workflows: [],
          affected_test_plans: [],
          affected_scheduled_runs: [],
          affected_release_gates: [],
        }),
      ),
      http.post('/api/v1/projects/:projectId/*', () => {
        writes += 1
        return HttpResponse.json({})
      }),
      http.patch('/api/v1/projects/:projectId/*', () => {
        writes += 1
        return HttpResponse.json({})
      }),
    )
    renderPage()
    expect(await screen.findByRole('button', { name: service.name })).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: /新建逻辑服务/ }))
    expect(screen.getByPlaceholderText('orders')).toBeDisabled()
    expect(screen.getByRole('combobox', { name: '环境默认服务' })).toBeDisabled()
    expect(screen.getByRole('combobox', { name: `${apiDefinition.name} 默认服务` })).toBeDisabled()
    expect(screen.getByRole('combobox', { name: '目标环境' })).not.toBeDisabled()
    await userEvent.click(screen.getAllByRole('button', { name: /影响预览/ })[0])
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('逻辑服务影响预览 / 编辑')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: '分析影响与目标' })).toBeDisabled()
    expect(writes).toBe(0)
  })

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
          affected_apis: [{ id: api.id, name: api.name, reason: 'API 默认服务' }],
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
    server.use(
      http.get(
        `/api/v1/projects/${project.id}/services/00000000-0000-4000-8000-000000004003/impact-preview`,
        () =>
          HttpResponse.json({
            strategy: 'request_target_dependency_v1',
            service_id: '00000000-0000-4000-8000-000000004003',
            service_key: 'orders-new',
            affected_apis: [],
            affected_workflows: [],
            affected_test_plans: [],
            affected_scheduled_runs: [],
            affected_release_gates: [],
          }),
      ),
    )
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByRole('heading', { name: '请求目标' })).toBeVisible()
    expect(await screen.findByRole('button', { name: '订单服务' })).toBeVisible()
    expect(await screen.findByText('https://orders.example.com')).toBeVisible()
    expect(screen.getByText('环境默认服务')).toBeVisible()

    await browser.click(screen.getByRole('button', { name: /新建逻辑服务/ }))
    await browser.type(screen.getByPlaceholderText('orders'), 'orders-new')
    await browser.type(screen.getByPlaceholderText('订单服务'), '副本')
    await browser.click(screen.getByRole('button', { name: /创建逻辑服务/ }))
    await waitFor(() => expect(servicePayload).toMatchObject({ service_key: 'orders-new' }))

    const environmentSelect = screen
      .getByRole('combobox', { name: '环境默认服务' })
      .closest('.ant-select') as HTMLElement | null
    await browser.click(within(environmentSelect!).getByRole('img', { name: 'close-circle' }))
    const defaultReview = await screen.findByRole('dialog')
    expect(defaultPayload).toBeNull()
    const unload = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(unload)
    expect(unload.defaultPrevented).toBe(true)
    await browser.click(within(defaultReview).getByRole('button', { name: '取消候选' }))
    await waitFor(() => expect(defaultReview).not.toBeInTheDocument())
    expect(defaultPayload).toBeNull()
    await browser.click(within(environmentSelect!).getByRole('img', { name: 'close-circle' }))
    const confirmedDefault = await screen.findByRole('dialog')
    await waitFor(() =>
      expect(within(confirmedDefault).getByRole('button', { name: '确认保存' })).toBeEnabled(),
    )
    await browser.click(within(confirmedDefault).getByRole('button', { name: '确认保存' }))
    await waitFor(() => expect(defaultPayload).toEqual({ default_service_id: null }))
    await waitFor(() => expect(confirmedDefault).not.toBeInTheDocument())

    await browser.click(screen.getByRole('button', { name: /新增地址变体/ }))
    await browser.click(screen.getByRole('combobox', { name: '新增地址的逻辑服务' }))
    await chooseOption(browser, '订单服务 · orders')
    await browser.type(
      screen.getByRole('textbox', { name: '新增部署地址' }),
      'https://orders.example.com',
    )
    await browser.click(screen.getByRole('button', { name: '添加部署地址' }))
    await waitFor(() => expect(endpointPayload).toMatchObject({ variant: 'default' }))

    await browser.click(screen.getByRole('combobox', { name: '查询当前用户 默认服务' }))
    await chooseOption(browser, '订单服务 · orders')
    const apiReview = await screen.findByRole('dialog')
    expect(apiPayload).toBeNull()
    await waitFor(() =>
      expect(within(apiReview).getByRole('button', { name: '确认保存' })).toBeEnabled(),
    )
    await browser.click(within(apiReview).getByRole('button', { name: '确认保存' }))
    await waitFor(() =>
      expect(apiPayload).toEqual({
        service_id: '00000000-0000-4000-8000-000000004003',
        base_version: apiDefinition.current_version,
      }),
    )

    await browser.click(screen.getAllByRole('button', { name: /影响预览 \/ 编辑/ })[0])
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('保存前请确认下游影响')).toBeInTheDocument()
    await waitFor(() => expect(within(dialog).getByText('API 默认服务')).toBeVisible())
    expect(within(dialog).getByRole('link', { name: api.name })).toHaveAttribute(
      'href',
      `/projects/${project.id}/apis?focus=${api.id}`,
    )
    await browser.click(within(dialog).getByRole('switch', { name: '启用服务' }))
    await browser.click(within(dialog).getByRole('button', { name: '分析影响与目标' }))
    expect(serviceUpdatePayload).toBeNull()
    await waitFor(() =>
      expect(within(dialog).getByRole('button', { name: '确认保存' })).toBeEnabled(),
    )
    await browser.click(within(dialog).getByRole('button', { name: '确认保存' }))
    await waitFor(() => expect(serviceUpdatePayload).toMatchObject({ enabled: false }))
  })

  it('updates the API address and endpoint options after editing a target in another module', async () => {
    let savedInput: Record<string, unknown> | undefined
    let currentEndpoint: ServiceEndpoint = {
      ...endpoint,
      variables: { gateway: 'v1' },
      headers: { 'X-Team': 'orders' },
      secret_refs: ['retired-token'],
      proxy_ref: 'corporate-proxy',
      health_check_path: '/health',
      health_expected_status: 204,
    }
    const version: ApiVersion = {
      id: 'api-v1',
      api_definition_id: apiDefinition.id,
      version: 1,
      service_id: service.id,
      method: 'GET',
      path: '/users/me',
      headers: {},
      variables: {},
      query_parameters: [],
      body_kind: 'none',
      body: null,
      auth_kind: 'none',
      auth_config: {},
      extraction_rules: [],
      assertions: [],
      created_at: '2026-10-11T00:00:00Z',
    }
    server.use(
      projectHandlers(),
      http.get(`/api/v1/projects/${project.id}/environments`, () =>
        HttpResponse.json([targetEnvironment]),
      ),
      http.get(`/api/v1/projects/${project.id}/services`, () => HttpResponse.json([service])),
      http.get(`/api/v1/projects/${project.id}/secrets`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({ items: [apiDefinition], total: 1, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}`, () =>
        HttpResponse.json({ definition: apiDefinition, version }),
      ),
      http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}/versions`, () =>
        HttpResponse.json([version]),
      ),
      http.get(
        `/api/v1/projects/${project.id}/environments/${environment.id}/service-endpoints`,
        () => HttpResponse.json([currentEndpoint]),
      ),
      http.get(`/api/v1/projects/${project.id}/executions`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/files`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
      http.post(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}/preview`, () =>
        HttpResponse.json({ url: `${currentEndpoint.base_url}/users/me` }),
      ),
      http.get(`/api/v1/projects/${project.id}/services/${service.id}/impact-preview`, () =>
        HttpResponse.json({
          strategy: 'request_target_dependency_v1',
          affected_apis: [],
          affected_workflows: [],
          affected_test_plans: [],
          affected_scheduled_runs: [],
          affected_release_gates: [],
        }),
      ),
      http.patch(
        `/api/v1/projects/${project.id}/service-endpoints/${endpoint.id}`,
        async ({ request }) => {
          const input = (await request.json()) as ServiceEndpoint
          savedInput = input
          currentEndpoint = { ...currentEndpoint, ...input, revision: 2 }
          return HttpResponse.json(currentEndpoint)
        },
      ),
    )
    renderPage(true)
    const browser = userEvent.setup()
    await waitFor(() =>
      expect(screen.getByTestId('api-target-probe')).toHaveTextContent(
        'https://orders.example.com/users/me',
      ),
    )
    const endpointCard = screen.getByText('部署地址与变体').closest<HTMLElement>('.ant-card')!
    await browser.click(within(endpointCard).getByRole('button', { name: /影响预览 \/ 编辑/ }))
    const dialog = await screen.findByRole('dialog')
    await waitFor(() => expect(within(dialog).getByText('部署地址影响预览 / 编辑')).toBeVisible())
    await browser.clear(within(dialog).getByLabelText('部署地址'))
    await browser.type(within(dialog).getByLabelText('部署地址'), 'https://orders-new.example.com')
    await browser.click(within(dialog).getByRole('button', { name: /请求头与变量/ }))
    await browser.clear(within(dialog).getByRole('textbox', { name: '变量值 1' }))
    await browser.type(within(dialog).getByRole('textbox', { name: '变量值 1' }), 'v2')
    await browser.click(within(dialog).getByRole('button', { name: '请求头高级 JSON' }))
    await browser.clear(within(dialog).getByRole('textbox', { name: '请求头 JSON' }))
    fireEvent.change(within(dialog).getByRole('textbox', { name: '请求头 JSON' }), {
      target: { value: '{"X-Team":"platform"}' },
    })
    await browser.click(within(dialog).getByRole('button', { name: '分析影响与目标' }))
    expect(savedInput).toBeUndefined()
    await waitFor(() =>
      expect(within(dialog).getByRole('button', { name: '确认保存' })).toBeEnabled(),
    )
    await browser.click(within(dialog).getByRole('button', { name: '确认保存' }))
    await waitFor(() =>
      expect(savedInput).toMatchObject({
        base_url: 'https://orders-new.example.com',
        headers: { 'X-Team': 'platform' },
        variables: { gateway: 'v2' },
        secret_refs: ['retired-token'],
        proxy_ref: 'corporate-proxy',
        health_check_path: '/health',
        health_expected_status: 204,
        connect_timeout_ms: 5000,
        read_timeout_ms: 30000,
        tls_verify: true,
        enabled: true,
      }),
    )
    await waitFor(() =>
      expect(screen.getByTestId('api-target-probe')).toHaveTextContent(
        'https://orders-new.example.com/users/me',
      ),
    )
    expect(screen.getByTestId('api-endpoint-probe')).toHaveTextContent(
      'https://orders-new.example.com',
    )
  })

  it('refreshes the displayed catalog when the refresh button is clicked', async () => {
    let name = service.name
    server.use(
      projectHandlers(),
      http.get(`/api/v1/projects/${project.id}/environments`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${project.id}/services`, () =>
        HttpResponse.json([{ ...service, name }]),
      ),
      http.get(`/api/v1/projects/${project.id}/secrets`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
      ),
    )
    renderPage()
    expect(await screen.findByRole('button', { name: service.name })).toBeVisible()
    name = 'Updated remote service'
    await userEvent.click(screen.getByRole('button', { name: /刷新/ }))
    expect(await screen.findByRole('button', { name })).toBeVisible()
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

  it('requires an explicit environment when multiple environments are available', async () => {
    const secondEnvironment: Environment = {
      ...targetEnvironment,
      id: '00000000-0000-4000-8000-000000004010',
      name: '集成测试',
    }
    let endpointRequests = 0
    server.use(
      projectHandlers(),
      http.get(`/api/v1/projects/${project.id}/environments`, () =>
        HttpResponse.json([targetEnvironment, secondEnvironment]),
      ),
      http.get(`/api/v1/projects/${project.id}/services`, () => HttpResponse.json([service])),
      http.get(`/api/v1/projects/${project.id}/secrets`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
      http.get(
        `/api/v1/projects/${project.id}/environments/:environmentId/service-endpoints`,
        () => {
          endpointRequests += 1
          return HttpResponse.json([])
        },
      ),
    )

    renderPage()

    expect(await screen.findByText('请先选择环境')).toBeVisible()
    expect(endpointRequests).toBe(0)
  })

  it('keeps an invalid stored environment visible instead of falling back', async () => {
    localStorage.setItem(
      `flowtest:environment:v1:${encodeURIComponent(user.id)}:${encodeURIComponent(project.id)}`,
      'missing-environment',
    )
    let endpointRequests = 0
    server.use(
      projectHandlers(),
      http.get(`/api/v1/projects/${project.id}/environments`, () =>
        HttpResponse.json([targetEnvironment]),
      ),
      http.get(`/api/v1/projects/${project.id}/services`, () => HttpResponse.json([service])),
      http.get(`/api/v1/projects/${project.id}/secrets`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
      http.get(
        `/api/v1/projects/${project.id}/environments/:environmentId/service-endpoints`,
        () => {
          endpointRequests += 1
          return HttpResponse.json([])
        },
      ),
    )

    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent('原环境已失效，请重新选择')
    expect(endpointRequests).toBe(0)
  })
  it('selects a logical service without changing bindings and shows only its environment addresses', async () => {
    const second = {
      ...service,
      id: '00000000-0000-4000-8000-000000004010',
      service_key: 'billing',
      name: '结算服务',
    }
    const secondEndpoint = {
      ...endpoint,
      id: '00000000-0000-4000-8000-000000004011',
      service_id: second.id,
      base_url: 'https://billing.example.test',
    }
    let writes = 0
    installTargetCatalog(() => [targetEnvironment])
    server.use(
      http.get(`/api/v1/projects/${project.id}/services`, () =>
        HttpResponse.json([service, second]),
      ),
      http.get(`/api/v1/projects/${project.id}/environments/:environmentId/service-endpoints`, () =>
        HttpResponse.json([endpoint, secondEndpoint]),
      ),
      http.patch('/api/v1/projects/:projectId/*', () => {
        writes += 1
        return HttpResponse.json({})
      }),
    )
    renderPage()
    await screen.findByText(endpoint.base_url)
    expect(screen.queryByText(secondEndpoint.base_url)).not.toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: '结算服务' }))
    await screen.findByText(secondEndpoint.base_url)
    expect(screen.queryByText(endpoint.base_url)).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '结算服务 · 部署地址' })).toBeVisible()
    expect(writes).toBe(0)
  })

  it('retains a failed binding candidate and retries the same captured environment only on confirmation', async () => {
    let current = targetEnvironment
    const writes: Array<{ id: string; body: unknown }> = []
    installTargetCatalog(() => [current])
    server.use(
      http.patch(
        `/api/v1/projects/${project.id}/environments/:environmentId`,
        async ({ request, params }) => {
          writes.push({ id: String(params.environmentId), body: await request.json() })
          if (writes.length === 1)
            return HttpResponse.json(
              {
                error: {
                  code: 'SAVE_FAILED',
                  message: '保存模拟失败',
                  details: null,
                  trace_id: 'save-trace',
                },
              },
              { status: 500 },
            )
          current = { ...current, default_service_id: null }
          return HttpResponse.json(current)
        },
      ),
    )
    renderPage()
    const browser = userEvent.setup()
    const select = await screen.findByRole('combobox', { name: '环境默认服务' })
    await waitFor(() => expect(select).toBeEnabled())
    await browser.click(
      within(select.closest('.ant-select')!).getByRole('img', { name: 'close-circle' }),
    )
    const dialog = await screen.findByRole('dialog')
    await waitFor(() =>
      expect(within(dialog).getByRole('button', { name: '确认保存' })).toBeEnabled(),
    )
    expect(writes).toEqual([])
    await browser.click(within(dialog).getByRole('button', { name: '确认保存' }))
    await within(dialog).findByText('保存模拟失败')
    expect(writes).toEqual([{ id: environment.id, body: { default_service_id: null } }])
    expect(
      within(dialog).getByText(`${targetEnvironment.name} · 尚未保存`, { exact: true }),
    ).toBeVisible()
    await browser.click(within(dialog).getByRole('button', { name: '确认保存' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(writes).toEqual([writes[0], writes[0]])
    const unload = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(unload)
    expect(unload.defaultPrevented).toBe(false)
  })

  it('disables an open candidate when its environment disappears or permission is revoked', async () => {
    let environments = [targetEnvironment]
    let editable = true
    let writes = 0
    installTargetCatalog(() => environments)
    server.use(
      http.get(`/api/v1/projects/${project.id}/permissions`, () =>
        HttpResponse.json({
          effective_role: editable ? 'editor' : 'viewer',
          capabilities: editable ? ['read', 'edit'] : ['read'],
          matrix: {},
        }),
      ),
      http.patch('/api/v1/projects/:projectId/*', () => {
        writes += 1
        return HttpResponse.json({})
      }),
    )
    const { queryClient } = renderPage()
    const browser = userEvent.setup()
    const select = await screen.findByRole('combobox', { name: '环境默认服务' })
    await waitFor(() => expect(select).toBeEnabled())
    await browser.click(
      within(select.closest('.ant-select')!).getByRole('img', { name: 'close-circle' }),
    )
    const dialog = await screen.findByRole('dialog')
    const save = within(dialog).getByRole('button', { name: '确认保存' })
    await waitFor(() => expect(save).toBeEnabled())
    editable = false
    await queryClient.invalidateQueries({ queryKey: ['project-permissions', project.id] })
    await waitFor(() => expect(save).toBeDisabled())
    editable = true
    await queryClient.invalidateQueries({ queryKey: ['project-permissions', project.id] })
    await waitFor(() => expect(save).toBeEnabled())
    environments = []
    await queryClient.invalidateQueries({ queryKey: ['request-target-environments', project.id] })
    await within(dialog).findByText(/管理环境已切换/)
    expect(save).toBeDisabled()
    expect(writes).toBe(0)
  })

  it('ignores a late impact read after switching to another environment', async () => {
    installTargetCatalog(() => [
      targetEnvironment,
      { ...targetEnvironment, id: 'second-environment', name: '第二环境' },
    ])
    let release: () => void = () => {}
    let reads = 0
    const pending = new Promise<void>((resolve) => {
      release = resolve
    })
    server.use(
      http.get(`/api/v1/projects/${project.id}/services/${service.id}/impact-preview`, async () => {
        reads += 1
        await pending
        return HttpResponse.json(emptyImpact)
      }),
    )
    renderPage()
    const browser = userEvent.setup()
    const environmentSelect = await screen.findByRole('combobox', { name: '目标环境' })
    await browser.click(environmentSelect)
    await chooseOption(browser, targetEnvironment.name)
    await browser.click(screen.getAllByRole('button', { name: /影响预览/ })[0])
    await waitFor(() => expect(reads).toBe(1))
    await browser.click(environmentSelect)
    await chooseOption(browser, '第二环境')
    release()
    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: /影响预览/ })[0]).toBeEnabled(),
    )
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

function renderPage(withApiProbe = false) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const view = render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <ProjectTestProvider section="request-targets">
            <RequestTargetsPage />
            {withApiProbe ? <ApiTargetProbe /> : null}
          </ProjectTestProvider>
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
  return { ...view, queryClient }
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

function ApiTargetProbe() {
  const state = useApiConsole(apiDefinition.id)
  return (
    <>
      <div data-testid="api-target-probe">{state.targetPreview.data?.url}</div>
      <div data-testid="api-endpoint-probe">{state.endpoints.data?.[0]?.base_url}</div>
    </>
  )
}

const unavailableResolution = {
  status: 'unavailable',
  url: null,
  service_key: null,
  endpoint_variant: null,
  endpoint_revision: null,
  api_version: null,
  error: {
    code: 'PREVIEW_CONTEXT_MISSING',
    message: '请选择预览环境和接口',
    details: null,
    trace_id: 'preview-test-trace',
  },
}

const emptyImpact = {
  strategy: 'request_target_dependency_v1',
  service_id: service.id,
  service_key: service.service_key,
  affected_apis: [],
  affected_workflows: [],
  affected_test_plans: [],
  affected_scheduled_runs: [],
  affected_release_gates: [],
}
function installTargetCatalog(environments: () => Environment[]) {
  server.use(
    projectHandlers(),
    http.get(`/api/v1/projects/${project.id}/environments`, () =>
      HttpResponse.json(environments()),
    ),
    http.get(`/api/v1/projects/${project.id}/services`, () => HttpResponse.json([service])),
    http.get(`/api/v1/projects/${project.id}/secrets`, () => HttpResponse.json([])),
    http.get(`/api/v1/projects/${project.id}/environments/:environmentId/service-endpoints`, () =>
      HttpResponse.json([endpoint]),
    ),
    http.get(`/api/v1/projects/${project.id}/apis`, () =>
      HttpResponse.json({ items: [apiDefinition], total: 1, page: 1, page_size: 20 }),
    ),
    http.get(`/api/v1/projects/${project.id}/services/${service.id}/impact-preview`, () =>
      HttpResponse.json(emptyImpact),
    ),
  )
}
