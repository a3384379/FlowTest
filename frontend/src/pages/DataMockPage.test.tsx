import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp, ConfigProvider } from 'antd'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import userEvent from '@testing-library/user-event'

import DataMockPage, { CredentialPanel, MockPanel } from './DataMockPage'
import type { Credential, MockRequestLog, MockRoute, MockService } from '../lib/api'
import { project, user } from '../test/fixtures'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { server } from '../test/server'
import { authenticateTestUser } from '../test/auth'
import { useAuthStore } from '../features/auth/auth-store'

const timestamp = '2026-08-10T00:00:00Z'

describe('DataMockPage', () => {
  it.each([
    { role: null, admin: false, editable: false },
    { role: null, admin: true, editable: true },
    { role: 'viewer', admin: false, editable: false },
    { role: 'editor', admin: false, editable: true },
    { role: 'owner', admin: false, editable: true },
  ] as const)(
    'requires a known writable role or system administrator ($role, admin=$admin)',
    async ({ role, admin, editable }) => {
      const previous = useAuthStore.getState()
      authenticateTestUser({ ...user, is_system_admin: admin })
      installBaseHandlers([])
      server.use(
        http.get('/api/v1/projects', () =>
          HttpResponse.json({ items: [{ ...project, role }], total: 1, page: 1, page_size: 100 }),
        ),
        http.get(`/api/v1/projects/${project.id}`, () => HttpResponse.json({ ...project, role })),
      )
      try {
        renderPage()
        await screen.findByText('Credential 元数据')
        const save = screen.queryByRole('button', { name: /加密保存/ })
        if (editable) expect(save).toBeEnabled()
        else expect(save).not.toBeInTheDocument()
      } finally {
        useAuthStore.setState(previous)
      }
    },
  )
  it('reports credential read failures and retries without exposing secret data', async () => {
    let reads = 0
    server.use(
      http.get('/api/v1/credentials', () => {
        reads += 1
        if (reads === 1)
          return HttpResponse.json(
            {
              error: {
                code: 'UNAVAILABLE',
                message: '凭据元数据读取失败',
                trace_id: 'credential-trace',
              },
            },
            { status: 503 },
          )
        return HttpResponse.json([credential({})])
      }),
    )
    renderCredentialPanel()
    expect(await screen.findByText(/凭据元数据读取失败/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByText('只读数据库')).toBeInTheDocument()
    expect(reads).toBe(2)
    expect(screen.queryByText(/凭据元数据读取失败/)).not.toBeInTheDocument()
  })

  it('creates a write-only credential', async () => {
    const credentials: Credential[] = []
    installBaseHandlers(credentials)
    server.use(
      http.post('/api/v1/credentials', async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>
        expect(body.secret).toBe('database-password')
        const created = credential({
          id: 'credential-new',
          name: String(body.name),
          host: String(body.host),
        })
        credentials.push(created)
        return HttpResponse.json(created, { status: 201 })
      }),
    )
    renderPage()

    expect(await screen.findByText('数据与 Mock')).toBeVisible()
    fireEvent.change(screen.getByLabelText('名称'), { target: { value: '订单只读库' } })
    fireEvent.change(screen.getByLabelText('Host'), { target: { value: 'db.example.com' } })
    fireEvent.change(screen.getByLabelText('数据库'), { target: { value: 'orders' } })
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'reader' } })
    fireEvent.change(screen.getByLabelText('密码/访问密钥'), {
      target: { value: 'database-password' },
    })
    fireEvent.click(screen.getByRole('button', { name: /加密保存/ }))

    expect(await screen.findByText('订单只读库')).toBeVisible()
    expect(screen.queryByDisplayValue('database-password')).not.toBeInTheDocument()
  })

  it('renders editable mock rules and safe request metadata', async () => {
    const calls = { toggles: 0, serviceCreates: 0, routeCreates: 0 }
    installMockHandlers(calls)
    renderMockPanel(true)

    await waitFor(() => expect(document.body).toHaveTextContent('查询用户'))
    expect(document.body).toHaveTextContent('/api/v1/mock/user-mock/')
    expect(document.body).toHaveTextContent('新建 Mock 服务')
    expect(document.body).toHaveTextContent('新增路由规则')
    expect(document.querySelector('button[aria-label="删除 Mock 路由"]')).toBeTruthy()

    const toggle = [...document.querySelectorAll('button')].find(
      (button) => button.textContent?.replaceAll(' ', '') === '停用',
    ) as HTMLButtonElement
    fireEvent.click(toggle)

    fireEvent.change(screen.getByPlaceholderText('用户服务 Mock'), {
      target: { value: '支付 Mock' },
    })
    fireEvent.change(screen.getByPlaceholderText('user-service'), {
      target: { value: 'payment-mock' },
    })
    const serviceCard = screen.getByText('新建 Mock 服务').closest('.ant-card') as HTMLElement
    fireEvent.click(within(serviceCard).getByRole('button', { name: /新建/ }))

    await waitFor(() => expect(calls.serviceCreates).toBe(1))
    await screen.findByText('无路由规则')
    await waitFor(() => expect(screen.getByRole('button', { name: '保存路由' })).toBeEnabled())
    const routeCard = screen.getByText('新增路由规则').closest('.ant-card') as HTMLElement
    const routeName = within(routeCard).getByLabelText('名称')
    fireEvent.change(routeName, {
      target: { value: '查询订单' },
    })
    fireEvent.change(within(routeCard).getByPlaceholderText('/users/{user_id}'), {
      target: { value: '/orders/{order_id}' },
    })
    const scenario = within(routeCard).getByPlaceholderText('happy')
    fireEvent.change(scenario, {
      target: { value: 'failure' },
    })
    fireEvent.click(within(routeCard).getByRole('button', { name: '保存路由' }))

    await waitFor(() => expect(calls).toEqual({ toggles: 1, serviceCreates: 1, routeCreates: 1 }))
    await screen.findByText('编辑路由规则')
    fireEvent.click(screen.getByRole('button', { name: '新建规则' }))
    const freshCard = screen.getByText('新增路由规则').closest('.ant-card') as HTMLElement
    fireEvent.change(within(freshCard).getByLabelText('名称'), {
      target: { value: '默认订单场景' },
    })
    fireEvent.change(within(freshCard).getByPlaceholderText('/users/{user_id}'), {
      target: { value: '/orders/{order_id}' },
    })
    fireEvent.click(within(freshCard).getByRole('button', { name: '保存路由' }))
    await waitFor(() => expect(calls.routeCreates).toBe(2))
  })

  it('keeps mock configuration read-only for viewers', async () => {
    installMockHandlers(
      undefined,
      { ...mockService, is_enabled: false },
      { ...mockRoute, scenario: 'failure' },
    )
    renderMockPanel(false)

    await waitFor(() => expect(document.body).toHaveTextContent('查询用户'))
    expect(document.body).toHaveTextContent('已停用')
    expect(document.body).toHaveTextContent('failure')
    expect(screen.queryByText('新建 Mock 服务')).not.toBeInTheDocument()
    expect(screen.queryByText('新增路由规则')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '删除 Mock 路由' })).not.toBeInTheDocument()
  })

  it('renders credential metadata without edit controls for viewers', async () => {
    server.use(
      http.get('/api/v1/credentials', () =>
        HttpResponse.json([
          credential({ database_name: '', tls_enabled: false }),
          { ...credential({ id: 'credential-future' }), kind: 'future' },
        ]),
      ),
    )
    renderCredentialPanel()

    await waitFor(() => expect(document.body).toHaveTextContent('只读数据库'))
    expect(document.body).toHaveTextContent('关闭')
    expect(document.body).toHaveTextContent('future')
    expect(document.querySelector('button[aria-label="删除 Credential"]')).toBeNull()
  })

  it('hides the database name for Redis credentials', async () => {
    server.use(http.get('/api/v1/credentials', () => HttpResponse.json([])))
    renderCredentialPanel(true)

    fireEvent.mouseDown(screen.getByLabelText('类型'))
    fireEvent.click(
      await screen.findByText('Redis', { selector: '.ant-select-item-option-content' }),
    )

    await waitFor(() => expect(screen.queryByLabelText('数据库')).not.toBeInTheDocument())
  })

  it('uses a write-only JSON editor for gRPC mTLS credentials', async () => {
    server.use(http.get('/api/v1/credentials', () => HttpResponse.json([])))
    renderCredentialPanel(true)

    fireEvent.mouseDown(screen.getByLabelText('类型'))
    fireEvent.click(
      await screen.findByText('gRPC mTLS', { selector: '.ant-select-item-option-content' }),
    )

    await waitFor(() => expect(screen.queryByLabelText('数据库')).not.toBeInTheDocument())
    expect(screen.queryByLabelText('用户名')).not.toBeInTheDocument()
    expect(screen.getByLabelText('mTLS 材料（JSON）')).toHaveAttribute(
      'placeholder',
      expect.stringContaining('private_key_pem'),
    )
  })

  it('offers activation for a disabled mock service to editors', async () => {
    installMockHandlers(undefined, { ...mockService, is_enabled: false })
    renderMockPanel(true)

    await waitFor(() => expect(document.body).toHaveTextContent('已停用'))
    expect(
      [...document.querySelectorAll('button')].some(
        (button) => button.textContent?.replaceAll(' ', '') === '启用',
      ),
    ).toBe(true)
  })

  it('edits service metadata without changing the slug and retains failed input', async () => {
    installMockHandlers()
    let current = mockService
    let failed = true
    server.use(
      http.get(`/api/v1/projects/${project.id}/mock-services`, () => HttpResponse.json([current])),
      http.patch(
        `/api/v1/projects/${project.id}/mock-services/${mockService.id}`,
        async ({ request }) => {
          const input = (await request.json()) as { name: string; description: string }
          expect(input).toEqual({ name: '订单服务新名称', description: '保留访问地址的服务说明' })
          if (failed)
            return HttpResponse.json(
              {
                error: {
                  message: '服务更新暂不可用',
                  trace_id: 'service-edit-failed',
                  code: 'UNAVAILABLE',
                },
              },
              { status: 503 },
            )
          current = { ...current, ...input }
          return HttpResponse.json(current)
        },
      ),
    )
    renderMockPanel(true)
    await userEvent.click(await screen.findByRole('button', { name: '编辑服务' }))
    const dialog = screen.getByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('服务名称'), {
      target: { value: '订单服务新名称' },
    })
    fireEvent.change(within(dialog).getByLabelText('服务说明'), {
      target: { value: '保留访问地址的服务说明' },
    })
    await userEvent.click(within(dialog).getByRole('button', { name: '保存服务' }))
    await screen.findByText(/服务更新暂不可用/)
    expect(within(dialog).getByLabelText('服务名称')).toHaveValue('订单服务新名称')
    expect(dialog).toHaveTextContent(mockService.slug)
    failed = false
    await userEvent.click(within(dialog).getByRole('button', { name: '保存服务' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(current.slug).toBe(mockService.slug)
    expect(await screen.findByText('订单服务新名称')).toBeInTheDocument()
  })

  it('requires an explicit discard before switching a service with unsaved rule fields', async () => {
    installMockHandlers()
    const another = { ...mockService, id: 'another-mock-service', name: '另外一个 Mock' }
    server.use(
      http.get(`/api/v1/projects/${project.id}/mock-services`, () =>
        HttpResponse.json([mockService, another]),
      ),
    )
    renderMockPanel(true)
    const edit = await screen.findByLabelText('编辑 Mock 路由：查询用户')
    expect(edit).toHaveRole('button')
    await userEvent.click(edit)
    const nameInput = screen.getByLabelText('名称')
    fireEvent.change(nameInput, { target: { value: '未保存的规则名称' } })
    const servicePicker = screen.getByLabelText('Mock 服务')
    expect(servicePicker).toHaveRole('combobox')
    async function switchService() {
      await userEvent.click(servicePicker)
      await userEvent.click(
        screen.getByText(another.name, { selector: '.ant-select-item-option-content' }),
      )
    }
    await switchService()
    let dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('切换服务前放弃未保存规则？')
    await userEvent.click(within(dialog).getByRole('button', { name: '继续编辑' }))
    expect(screen.getByLabelText('名称')).toHaveValue('未保存的规则名称')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await switchService()
    dialog = screen.getByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: '放弃并切换' }))
    await screen.findByText('无路由规则')
    expect(screen.getByLabelText('名称')).toHaveValue('')
    expect(screen.queryByDisplayValue('未保存的规则名称')).not.toBeInTheDocument()
  })

  it('retains dirty rule fields but disables writes when the service directory refresh fails', async () => {
    installMockHandlers()
    const client = renderMockPanel(true)
    await userEvent.click(await screen.findByLabelText('编辑 Mock 路由：查询用户'))
    const nameInput = screen.getByLabelText('名称')
    const editor = nameInput.closest('form')!
    fireEvent.change(nameInput, { target: { value: '读取失败仍保留草稿' } })
    const saveButton = within(editor).getByRole('button', { name: '保存路由' })
    const editServiceButton = screen.getByText('编辑服务').closest('button')!
    server.use(
      http.get(`/api/v1/projects/${project.id}/mock-services`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'UNAVAILABLE',
              message: '服务目录读取失败',
              trace_id: 'mock-directory-failed',
            },
          },
          { status: 503 },
        ),
      ),
    )
    await act(async () => {
      await client.invalidateQueries({ queryKey: ['mock-services', project.id] })
    })
    await screen.findByText(/服务目录读取失败/)
    expect(nameInput).toHaveValue('读取失败仍保留草稿')
    expect(saveButton).toBeInTheDocument()
    expect(saveButton).toBeDisabled()
    expect(editServiceButton).toBeInTheDocument()
    expect(editServiceButton).toBeDisabled()
  })
})

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <ProjectTestProvider section="data">
          <DataMockPage />
        </ProjectTestProvider>
      </QueryClientProvider>
    </AntdApp>,
  )
}

function renderMockPanel(canEdit: boolean) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <MockPanel projectId={project.id} canEdit={canEdit} />
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
  return queryClient
}

function renderCredentialPanel(canEdit = false) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <CredentialPanel projectId={project.id} canEdit={canEdit} />
      </QueryClientProvider>
    </AntdApp>,
  )
}

function installBaseHandlers(credentials: Credential[]) {
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
    ),
    http.get('/api/v1/credentials', () => HttpResponse.json(credentials)),
  )
}

function installMockHandlers(
  calls: { toggles: number; serviceCreates: number; routeCreates: number } = emptyCalls(),
  service: MockService = mockService,
  route: MockRoute = mockRoute,
) {
  const services = [service]
  const rules = new Map<string, MockRoute[]>([[service.id, [route]]])
  server.use(
    http.get(`/api/v1/projects/${project.id}/mock-services`, () => HttpResponse.json(services)),
    http.get(`/api/v1/projects/${project.id}/mock-services/:serviceId/routes`, ({ params }) =>
      HttpResponse.json(rules.get(String(params.serviceId)) ?? []),
    ),
    http.get(`/api/v1/projects/${project.id}/mock-services/:serviceId/request-logs`, ({ params }) =>
      HttpResponse.json({
        items: params.serviceId === service.id ? [mockLog] : [],
        total: params.serviceId === service.id ? 1 : 0,
        page: 1,
        page_size: 20,
      }),
    ),
    http.patch(
      `/api/v1/projects/${project.id}/mock-services/:serviceId`,
      async ({ request, params }) => {
        const input = (await request.json()) as Partial<MockService>
        if ('is_enabled' in input) calls.toggles += 1
        const index = services.findIndex((item) => item.id === params.serviceId)
        services[index] = { ...services[index], ...input }
        return HttpResponse.json(services[index])
      },
    ),
    http.post(`/api/v1/projects/${project.id}/mock-services`, async ({ request }) => {
      calls.serviceCreates += 1
      const created = {
        ...service,
        ...((await request.json()) as Partial<MockService>),
        id: 'mock-2',
      }
      services.push(created)
      rules.set(created.id, [])
      return HttpResponse.json(created, { status: 201 })
    }),
    http.post(
      `/api/v1/projects/${project.id}/mock-services/:serviceId/routes`,
      async ({ request, params }) => {
        calls.routeCreates += 1
        const id = String(params.serviceId)
        const created = {
          ...route,
          ...((await request.json()) as Partial<MockRoute>),
          id: `created-route-${calls.routeCreates}`,
          mock_service_id: id,
        }
        rules.set(id, [...(rules.get(id) ?? []), created])
        return HttpResponse.json(created, { status: 201 })
      },
    ),
    http.put(
      `/api/v1/projects/${project.id}/mock-services/:serviceId/routes/:routeId`,
      async ({ request, params }) => {
        const id = String(params.serviceId)
        const updated = {
          ...route,
          ...((await request.json()) as Partial<MockRoute>),
          id: String(params.routeId),
          mock_service_id: id,
        }
        rules.set(
          id,
          (rules.get(id) ?? []).map((item) => (item.id === updated.id ? updated : item)),
        )
        return HttpResponse.json(updated)
      },
    ),
  )
}

function emptyCalls() {
  return { toggles: 0, serviceCreates: 0, routeCreates: 0 }
}

function credential(overrides: Partial<Credential> = {}): Credential {
  return {
    id: 'credential-1',
    project_id: project.id,
    name: '只读数据库',
    kind: 'postgresql',
    host: 'db.example.com',
    port: 5432,
    database_name: 'orders',
    username: 'reader',
    secret_provider: 'local',
    tls_enabled: true,
    created_by_id: user.id,
    created_at: timestamp,
    updated_at: timestamp,
    ...overrides,
  }
}

const mockService: MockService = {
  id: 'mock-1',
  project_id: project.id,
  name: '用户 Mock',
  slug: 'user-mock',
  description: '',
  is_enabled: true,
  created_by_id: user.id,
  created_at: timestamp,
  updated_at: timestamp,
}
const mockRoute: MockRoute = {
  id: 'route-1',
  mock_service_id: mockService.id,
  name: '查询用户',
  method: 'GET',
  path_pattern: '/users/{user_id}',
  query_conditions: {},
  header_conditions: {},
  response_status: 200,
  response_headers: {},
  response_body: { id: '{{path.user_id}}' },
  delay_ms: 0,
  scenario: null,
  priority: 0,
  is_enabled: true,
  created_by_id: user.id,
  created_at: timestamp,
  updated_at: timestamp,
}
const mockLog: MockRequestLog = {
  id: 'log-1',
  mock_service_id: mockService.id,
  mock_route_id: mockRoute.id,
  method: 'GET',
  path: '/users/42',
  query_parameters: {},
  headers: { authorization: '***' },
  body: null,
  matched: true,
  scenario: null,
  response_status: 200,
  duration_ms: 5,
  created_at: timestamp,
}
