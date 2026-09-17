import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import { useAuthStore } from './features/auth/auth-store'
import { setAccessToken } from './lib/api'
import { project, user } from './test/fixtures'
import { server } from './test/server'

describe('App authentication', () => {
  beforeEach(() => {
    localStorage.clear()
    setAccessToken(null)
    useAuthStore.setState({
      initialized: false,
      initializing: false,
      token: null,
      user: null,
    })
  })

  afterEach(() => vi.restoreAllMocks())

  it.each([true, false])(
    'preserves every existing navigation URL for admin=%s',
    async (isAdmin) => {
      authenticateExistingUser()
      useAuthStore.setState({ user: { ...user, is_system_admin: isAdmin } })
      renderApp(`/projects/${project.id}/dashboard`)
      await screen.findByRole('heading', { name: '质量指挥中心' })
      const navigation = within(document.querySelector('.sidebar') as HTMLElement)
      const sections = {
        dashboard: '质量总览',
        settings: '项目管理',
        services: '服务目录',
        'request-targets': '请求目标',
        apis: '接口管理',
        protocols: '多协议工作台',
        assets: '测试资产',
        workflows: '流程编排',
        data: '数据与 Mock',
        tasks: '任务执行',
        performance: '性能实验室',
        environments: '环境实验室',
        contracts: '契约中心',
        'test-engineering': '测试工程',
        contexts: '上下文检查器',
        impact: '影响分析',
        'change-regression': '变更回归',
        quality: '质量中心',
        release: '发布门禁',
        ai: 'AI 助手',
        'ai-changes': 'AI 变更集',
        'mcp-changes': 'MCP 变更集',
        reports: '测试报告',
        organization: '组织治理',
        fabric: '分布式执行面',
        platform: '平台管理',
      }
      const globalPaths: Record<string, string> = {
        organization: '/organization',
        fabric: '/execution-fabric',
        platform: '/platform',
      }
      const seen = new Set<string>()
      const browser = userEvent.setup()
      const groups: Record<string, string[]> = {
        项目与接口: ['apis', 'services', 'request-targets', 'protocols', 'settings'],
        测试设计: ['workflows', 'assets', 'data', 'contracts', 'test-engineering'],
        执行与环境: ['tasks', 'environments', 'performance'],
        质量分析: ['reports', 'impact', 'change-regression', 'quality', 'release'],
        'AI 与集成': ['ai', 'contexts', 'ai-changes', 'mcp-changes'],
        系统管理: ['organization', 'fabric', 'platform'],
      }
      for (const [section, label] of Object.entries(sections)) {
        const group = Object.keys(groups).find((name) => groups[name].includes(section))
        if (group) {
          const parent = navigation.getByRole('menuitem', { name: group })
          if (parent.getAttribute('aria-expanded') !== 'true') await browser.click(parent)
        }
        if (!isAdmin && ['fabric', 'platform'].includes(section)) {
          expect(navigation.queryByRole('link', { name: label })).not.toBeInTheDocument()
          continue
        }
        seen.add(section)
        expect(navigation.getByRole('link', { name: label })).toHaveAttribute(
          'href',
          globalPaths[section] ?? `/projects/${project.id}/${section}`,
        )
      }
      expect(seen.size).toBe(isAdmin ? 26 : 24)
    },
  )

  it('logs in, shows the lazy dashboard, and logs out', async () => {
    server.use(
      http.post('/api/v1/auth/refresh', () => HttpResponse.json({}, { status: 401 })),
      http.post('/api/v1/auth/login', () =>
        HttpResponse.json({ access_token: 'access-token', expires_in: 900, user }),
      ),
      http.post('/api/v1/auth/logout', () => new HttpResponse(null, { status: 204 })),
    )
    renderApp()
    const browser = userEvent.setup()

    expect(await screen.findByRole('heading', { name: '登录账号' })).toBeVisible()
    await browser.type(screen.getByLabelText('账号'), user.email)
    await browser.type(screen.getByLabelText('密码'), 'correct horse battery staple')
    await browser.click(screen.getByRole('button', { name: /登\s*录/ }))

    expect(await screen.findByRole('heading', { name: '质量指挥中心' })).toBeVisible()
    expect(screen.getByText('接口自动化测试平台')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: /退出/ }))
    expect(await screen.findByRole('heading', { name: '登录账号' })).toBeVisible()
  })

  it('restores and navigates project workspace tabs', async () => {
    authenticateExistingUser()
    localStorage.setItem(
      `flowtest:workspace-tabs:v1:${user.id}:${project.id}`,
      JSON.stringify(['apis', 'invalid-section']),
    )
    renderApp(`/projects/${project.id}/dashboard`)
    const browser = userEvent.setup()

    expect(await screen.findByRole('tab', { name: '质量总览' })).toBeVisible()
    const apiTab = screen.getByRole('tab', { name: '接口管理' })
    const close = apiTab.closest('.ant-tabs-tab')?.querySelector('.ant-tabs-tab-remove')
    expect(close).toBeInstanceOf(HTMLElement)
    fireEvent.click(close as HTMLElement)
    expect(screen.queryByRole('tab', { name: '接口管理' })).not.toBeInTheDocument()
    await browser.click(screen.getByRole('menuitem', { name: '项目与接口' }))
    await browser.click(screen.getByRole('link', { name: '接口管理' }))
    expect(await screen.findByRole('tab', { name: '接口管理' })).toBeVisible()
    await browser.click(screen.getByRole('tab', { name: '质量总览' }))
    expect(await screen.findByRole('heading', { name: '质量指挥中心' })).toBeVisible()
  })

  it('recovers from a corrupt workspace draft and closes the active tab safely', async () => {
    authenticateExistingUser()
    localStorage.setItem(`flowtest:workspace-tabs:v1:${user.id}:${project.id}`, '{corrupt')
    renderApp(`/projects/${project.id}/apis`)

    const apiTab = await screen.findByRole('tab', { name: '接口管理' })
    const close = apiTab.closest('.ant-tabs-tab')?.querySelector('.ant-tabs-tab-remove')
    expect(close).toBeInstanceOf(HTMLElement)
    fireEvent.click(close as HTMLElement)

    expect(await screen.findByRole('heading', { name: '质量指挥中心' })).toBeVisible()
  })

  it('ignores non-array workspace data when browser storage cannot be updated', async () => {
    authenticateExistingUser()
    localStorage.setItem(
      `flowtest:workspace-tabs:v1:${user.id}:${project.id}`,
      JSON.stringify({ section: 'apis' }),
    )
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('Storage is unavailable')
    })

    renderApp(`/projects/${project.id}/dashboard`)

    expect(await screen.findByRole('tab', { name: '质量总览' })).toBeVisible()
    expect(await screen.findByRole('heading', { name: '质量指挥中心' })).toBeVisible()
    setItem.mockRestore()
  })

  it('requires a password change after first login', async () => {
    server.use(
      http.post('/api/v1/auth/refresh', () => HttpResponse.json({}, { status: 401 })),
      http.post('/api/v1/auth/login', () =>
        HttpResponse.json({
          access_token: 'access-token',
          expires_in: 900,
          user: { ...user, requires_password_change: true },
        }),
      ),
      http.post('/api/v1/auth/change-password', () => new HttpResponse(null, { status: 204 })),
    )
    renderApp()
    const browser = userEvent.setup()

    await screen.findByRole('heading', { name: '登录账号' })
    await browser.type(screen.getByLabelText('账号'), user.email)
    await browser.type(screen.getByLabelText('密码'), 'initial-password')
    await browser.click(screen.getByRole('button', { name: /登\s*录/ }))
    expect(await screen.findByText('首次登录，请修改密码')).toBeVisible()

    await browser.type(screen.getByLabelText('当前密码'), 'initial-password')
    await browser.type(screen.getByLabelText('新密码'), 'new-password-123')
    await browser.type(screen.getByLabelText('确认新密码'), 'new-password-123')
    await browser.click(screen.getByRole('button', { name: /保\s*存并进入平台/ }))
    expect(await screen.findByRole('heading', { name: '质量指挥中心' })).toBeVisible()
  })

  it('restores a session with refresh rotation', async () => {
    server.use(
      http.post('/api/v1/auth/refresh', () =>
        HttpResponse.json({ access_token: 'rotated-token', expires_in: 900 }),
      ),
      http.get('/api/v1/auth/me', () => HttpResponse.json(user)),
    )

    renderApp()

    expect(await screen.findByRole('heading', { name: '质量指挥中心' })).toBeVisible()
    expect(useAuthStore.getState().token).toBe('rotated-token')
  })

  it('shows the configured OIDC login entry without exposing credentials', async () => {
    server.use(http.post('/api/v1/auth/refresh', () => HttpResponse.json({}, { status: 401 })))

    renderApp('/dashboard', [project], { enabled: true, provider: '公司统一身份' })

    expect(await screen.findByRole('link', { name: /使用 公司统一身份 登录/ })).toHaveAttribute(
      'href',
      '/api/v1/auth/oidc/login',
    )
  })

  it('restores a project-scoped deep link and preserves it in navigation', async () => {
    authenticateExistingUser()

    renderApp(`/projects/${project.id}/dashboard`)

    expect(await screen.findByRole('heading', { name: '质量指挥中心' })).toBeVisible()
    expect((await screen.findAllByText(project.name)).length).toBeGreaterThanOrEqual(2)
    await userEvent.setup().click(screen.getByRole('menuitem', { name: '项目与接口' }))
    expect(screen.getByRole('link', { name: '接口管理' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/apis`,
    )
    expect(screen.getByRole('link', { name: '服务目录' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/services`,
    )
  })

  it('opens the project-scoped service catalog route', async () => {
    authenticateExistingUser()
    server.use(
      http.get('/api/v1/v3/features', () => HttpResponse.json({ contract_hub: true })),
      http.get(`/api/v1/projects/${project.id}/contract-hub/services`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/contract-hub/summary`, () =>
        HttpResponse.json({
          service_count: 0,
          openapi_contract_count: 0,
          pact_contract_count: 0,
          pending_verification_count: 0,
          failed_verification_count: 0,
          breaking_change_count: 0,
          broker_available: false,
        }),
      ),
      http.get(`/api/v1/projects/${project.id}/contract-hub/service-graph`, () =>
        HttpResponse.json({ nodes: [], edges: [] }),
      ),
    )

    renderApp(`/projects/${project.id}/services`)

    expect(await screen.findByRole('heading', { name: '服务目录' })).toBeVisible()
    expect(await screen.findByText('暂无匹配服务')).toBeVisible()
  })

  it('redirects a project-free section to the first accessible project', async () => {
    authenticateExistingUser()
    renderApp('/settings')

    expect(await screen.findByRole('heading', { name: '项目治理' })).toBeVisible()
    expect(screen.getByRole('link', { name: '质量总览' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/dashboard`,
    )
  })

  it('shows an empty state when a project section has no accessible project', async () => {
    authenticateExistingUser()
    renderApp('/settings', [])

    expect(await screen.findByText('暂无可访问项目')).toBeVisible()
  })

  it('offers project creation when the account has no projects', async () => {
    authenticateExistingUser()
    const createdProject = { ...project, id: 'project-created', name: '新建订单项目' }
    renderApp('/dashboard', [])
    server.use(
      http.post('/api/v1/projects', async ({ request }) => {
        expect(await request.json()).toEqual({ name: '新建订单项目', description: '' })
        return HttpResponse.json(createdProject, { status: 201 })
      }),
      http.get(`/api/v1/projects/${createdProject.id}`, () => HttpResponse.json(createdProject)),
      http.get(`/api/v1/projects/${createdProject.id}/flaky-tests`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${createdProject.id}/release-decisions`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
    )
    const browser = userEvent.setup()
    await browser.click(await screen.findByRole('button', { name: '创建第一个项目' }))
    await browser.type(screen.getByLabelText('项目名称'), createdProject.name)
    await browser.click(screen.getByRole('button', { name: 'OK' }))

    expect(await screen.findByText(`当前查看：${createdProject.name}`)).toBeVisible()
  })

  it('redirects a bare project URL to its dashboard', async () => {
    authenticateExistingUser()
    renderApp(`/projects/${project.id}`)

    expect(await screen.findByRole('heading', { name: '质量指挥中心' })).toBeVisible()
    expect(await screen.findByText(`当前查看：${project.name}`)).toBeVisible()
  })
})

function renderApp(
  initialEntry = '/dashboard',
  projects = [project],
  oidcStatus = { enabled: false, provider: null as string | null },
) {
  server.use(
    http.get('/api/v1/auth/oidc/status', () => HttpResponse.json(oidcStatus)),
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: projects, total: projects.length, page: 1, page_size: 100 }),
    ),
    http.get('/api/v1/dashboard/summary', () =>
      HttpResponse.json({
        project_count: 1,
        api_count: 3,
        workflow_count: 2,
        today_total: 1,
        today_passed: 1,
        today_failed: 0,
        pass_rate: 100,
        trend: [],
      }),
    ),
    http.get('/api/v1/dashboard/recent-executions', () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 10 }),
    ),
    http.get('/api/v1/v3/features', () =>
      HttpResponse.json({
        contract_hub: true,
        impact_engine: false,
        quality_intelligence: false,
      }),
    ),
    http.get(`/api/v1/projects/${project.id}/flaky-tests`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
    ),
    http.get(`/api/v1/projects/${project.id}/release-decisions`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
    ),
    http.get(`/api/v1/projects/${project.id}/permissions`, () =>
      HttpResponse.json({ effective_role: 'owner', capabilities: [], matrix: {} }),
    ),
    http.get(`/api/v1/projects/${project.id}/security-policy`, () =>
      HttpResponse.json({ enabled: true, allowed_hosts: [], allowed_private_cidrs: [] }),
    ),
    http.get(`/api/v1/projects/${project.id}/retention-policy`, () =>
      HttpResponse.json({ retention_days: 90, maximum_days: 3650 }),
    ),
  )
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[initialEntry]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>
    </AntdApp>,
  )
}

function authenticateExistingUser() {
  setAccessToken('existing-token')
  useAuthStore.setState({
    initialized: true,
    initializing: false,
    token: 'existing-token',
    user,
  })
}
