import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'

import DataMockPage, { CredentialPanel, MockPanel } from './DataMockPage'
import type { Credential, MockRequestLog, MockRoute, MockService } from '../lib/api'
import { project, user } from '../test/fixtures'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { server } from '../test/server'

const timestamp = '2026-08-10T00:00:00Z'

describe('DataMockPage', () => {
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
    fireEvent.change(scenario, { target: { value: '' } })
    fireEvent.click(within(routeCard).getByRole('button', { name: '保存路由' }))
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
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <MockPanel projectId={project.id} canEdit={canEdit} />
      </QueryClientProvider>
    </AntdApp>,
  )
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
  server.use(
    http.get(`/api/v1/projects/${project.id}/mock-services`, () => HttpResponse.json([service])),
    http.get(`/api/v1/projects/${project.id}/mock-services/${mockService.id}/routes`, () =>
      HttpResponse.json([route]),
    ),
    http.get(`/api/v1/projects/${project.id}/mock-services/${mockService.id}/request-logs`, () =>
      HttpResponse.json({ items: [mockLog], total: 1, page: 1, page_size: 50 }),
    ),
    http.patch(`/api/v1/projects/${project.id}/mock-services/${mockService.id}`, () => {
      calls.toggles += 1
      return HttpResponse.json({ ...mockService, is_enabled: false })
    }),
    http.post(`/api/v1/projects/${project.id}/mock-services`, () => {
      calls.serviceCreates += 1
      return HttpResponse.json(
        { ...mockService, id: 'mock-2', slug: 'payment-mock' },
        { status: 201 },
      )
    }),
    http.post(`/api/v1/projects/${project.id}/mock-services/${mockService.id}/routes`, () => {
      calls.routeCreates += 1
      return HttpResponse.json({ ...mockRoute, id: 'route-2' }, { status: 201 })
    }),
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
