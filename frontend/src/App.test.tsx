import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'

import App from './App'
import { useAuthStore } from './features/auth/auth-store'
import { setAccessToken } from './lib/api'
import { project, user } from './test/fixtures'
import { server } from './test/server'

describe('App authentication', () => {
  beforeEach(() => {
    setAccessToken(null)
    useAuthStore.setState({
      initialized: false,
      initializing: false,
      token: null,
      user: null,
    })
  })

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
    await browser.type(screen.getByLabelText('邮箱'), user.email)
    await browser.type(screen.getByLabelText('密码'), 'correct horse battery staple')
    await browser.click(screen.getByRole('button', { name: /登\s*录/ }))

    expect(await screen.findByRole('heading', { name: '工作台' })).toBeVisible()
    expect(screen.getByText('接口自动化测试平台')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: /退出/ }))
    expect(await screen.findByRole('heading', { name: '登录账号' })).toBeVisible()
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
    await browser.type(screen.getByLabelText('邮箱'), user.email)
    await browser.type(screen.getByLabelText('密码'), 'initial-password')
    await browser.click(screen.getByRole('button', { name: /登\s*录/ }))
    expect(await screen.findByText('首次登录，请修改密码')).toBeVisible()

    await browser.type(screen.getByLabelText('当前密码'), 'initial-password')
    await browser.type(screen.getByLabelText('新密码'), 'new-password-123')
    await browser.type(screen.getByLabelText('确认新密码'), 'new-password-123')
    await browser.click(screen.getByRole('button', { name: /保\s*存并进入平台/ }))
    expect(await screen.findByRole('heading', { name: '工作台' })).toBeVisible()
  })

  it('restores a session with refresh rotation', async () => {
    server.use(
      http.post('/api/v1/auth/refresh', () =>
        HttpResponse.json({ access_token: 'rotated-token', expires_in: 900 }),
      ),
      http.get('/api/v1/auth/me', () => HttpResponse.json(user)),
    )

    renderApp()

    expect(await screen.findByRole('heading', { name: '工作台' })).toBeVisible()
    expect(useAuthStore.getState().token).toBe('rotated-token')
  })

  it('restores a project-scoped deep link and preserves it in navigation', async () => {
    authenticateExistingUser()

    renderApp(`/projects/${project.id}/dashboard`)

    expect(await screen.findByRole('heading', { name: '工作台' })).toBeVisible()
    expect((await screen.findAllByText(project.name)).length).toBeGreaterThanOrEqual(2)
    expect(screen.getByRole('link', { name: '接口管理' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/apis`,
    )
  })

  it('redirects a project-free section to the first accessible project', async () => {
    authenticateExistingUser()
    renderApp('/settings')

    expect(await screen.findByRole('heading', { name: '项目治理' })).toBeVisible()
    expect(screen.getByRole('link', { name: '首页' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/dashboard`,
    )
  })

  it('shows an empty state when a project section has no accessible project', async () => {
    authenticateExistingUser()
    renderApp('/settings', [])

    expect(await screen.findByText('暂无可访问项目')).toBeVisible()
  })

  it('redirects a bare project URL to its dashboard', async () => {
    authenticateExistingUser()
    renderApp(`/projects/${project.id}`)

    expect(await screen.findByRole('heading', { name: '工作台' })).toBeVisible()
    expect(await screen.findByText(`当前查看：${project.name}`)).toBeVisible()
  })
})

function renderApp(initialEntry = '/dashboard', projects = [project]) {
  server.use(
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
    http.get(`/api/v1/projects/${project.id}/permissions`, () =>
      HttpResponse.json({ effective_role: 'owner', capabilities: [], matrix: {} }),
    ),
    http.get(`/api/v1/projects/${project.id}/security-policy`, () =>
      HttpResponse.json({ allowed_hosts: [], allowed_private_cidrs: [] }),
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
