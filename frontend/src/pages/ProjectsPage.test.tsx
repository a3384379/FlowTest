import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { project, user } from '../test/fixtures'
import { authenticateTestUser } from '../test/auth'
import { useAuthStore } from '../features/auth/auth-store'
import { server } from '../test/server'
import ProjectTestProvider from '../test/ProjectTestProvider'
import ProjectsPage from './ProjectsPage'
import { getProjectPermission } from '../features/projects/project-service'
import type { ProjectPermission } from '../lib/api'

const originalAuth = useAuthStore.getState()
afterEach(() => useAuthStore.setState(originalAuth))

describe('ProjectsPage', () => {
  it.each(['viewer', 'editor'] as const)(
    'refreshes the real permission and project roles after a legal self-demotion to %s',
    async (nextRole) => {
      const fixture = accessRefreshFixture()
      const queryClient = new QueryClient({
        defaultOptions: {
          queries: { retry: false, staleTime: 15_000 },
          mutations: { retry: false },
        },
      })
      const permissionKeys = [
        ['project-permission', project.id],
        ['project-permissions', project.id, user.id],
      ]
      for (const queryKey of permissionKeys)
        await queryClient.fetchQuery({ queryKey, queryFn: () => getProjectPermission(project.id) })
      const unrelated = { effective_role: 'owner', capabilities: ['read', 'edit'] }
      queryClient.setQueryData(['project-permissions', 'other-project', user.id], unrelated)
      renderPage(queryClient)
      await submitSelfRole(nextRole)
      expect(
        await screen.findByText(`当前身份：${nextRole === 'viewer' ? 'Viewer' : 'Editor'}`),
      ).toBeVisible()
      expect(screen.queryByRole('button', { name: /添加成员/ })).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: '保存安全策略' })).toBeDisabled()
      if (nextRole === 'editor')
        expect(await screen.findByRole('button', { name: /新建目录/ })).toBeEnabled()
      else expect(screen.queryByRole('button', { name: /新建目录/ })).not.toBeInTheDocument()
      expect(fixture.writes).toHaveBeenCalledExactlyOnceWith({ user_id: user.id, role: nextRole })
      expect(queryClient.getQueryData(['projects'])).toMatchObject({ items: [{ role: nextRole }] })
      expect(queryClient.getQueryData(['project', project.id])).toMatchObject({ role: nextRole })
      for (const queryKey of permissionKeys)
        expect(queryClient.getQueryData(queryKey)).toMatchObject({
          effective_role: nextRole,
          capabilities: nextRole === 'viewer' ? ['read'] : ['read', 'edit', 'execute'],
        })
      expect(queryClient.getQueryData(['project-permissions', 'other-project', user.id])).toBe(
        unrelated,
      )
      await waitFor(() => expect(screen.getByText('成员与团队配置已更新')).toBeVisible())
    },
  )

  it.each([403, 503])(
    'keeps sensitive writes closed when permission refresh returns %s and allows retry',
    async (status) => {
      let failRefresh = true
      const fixture = accessRefreshFixture({ refreshStatus: () => (failRefresh ? status : null) })
      renderPage()
      await submitSelfRole('viewer')
      expect((await screen.findAllByText('权限重读失败'))[0]).toBeVisible()
      await waitFor(() =>
        expect(screen.queryByRole('button', { name: /添加成员/ })).not.toBeInTheDocument(),
      )
      expect(screen.getByRole('button', { name: '保存安全策略' })).toBeDisabled()
      expect(screen.queryByText('成员与团队配置已更新')).not.toBeInTheDocument()
      failRefresh = false
      await userEvent.click(screen.getByRole('button', { name: '重试' }))
      expect(await screen.findByText('当前身份：Viewer')).toBeVisible()
      expect(fixture.writes).toHaveBeenCalledTimes(1)
    },
  )

  it('keeps access input and security writes locked until the new permission read completes', async () => {
    let release = () => {}
    const pending = new Promise<void>((resolve) => {
      release = resolve
    })
    const fixture = accessRefreshFixture({ waitRefresh: () => pending })
    renderPage()
    try {
      await submitSelfRole('viewer')
      await waitFor(() => expect(fixture.refreshes).toHaveBeenCalled())
      expect(screen.getByRole('button', { name: '保存安全策略' })).toBeDisabled()
      expect(screen.getByLabelText('项目用户 ID')).toBeDisabled()
      expect(screen.queryByText('成员与团队配置已更新')).not.toBeInTheDocument()
      await act(async () => {
        release()
      })
      expect(await screen.findByText('当前身份：Viewer')).toBeVisible()
      expect(fixture.writes).toHaveBeenCalledTimes(1)
    } finally {
      release()
    }
  })

  it('retains the owner and identity when the server rejects demotion of the last owner', async () => {
    const fixture = accessRefreshFixture({ lastOwner: true })
    renderPage()
    await submitSelfRole('viewer')
    await waitFor(() => expect(screen.getByText('项目至少需要保留一名 Owner')).toBeVisible())
    expect(screen.getByText('当前身份：项目 Owner')).toBeVisible()
    expect(screen.getByLabelText('项目用户 ID')).toHaveValue(user.id)
    expect(screen.getByRole('button', { name: /添加成员/ })).toBeEnabled()
    expect(fixture.writes).toHaveBeenCalledTimes(1)
  })

  it('waits for slow permission refresh after a project directory refresh has failed', async () => {
    let release!: () => void
    const pending = new Promise<void>((resolve) => {
      release = resolve
    })
    const fixture = accessRefreshFixture({ waitRefresh: () => pending })
    server.use(
      http.get('/api/v1/projects', () =>
        fixture.writes.mock.calls.length
          ? HttpResponse.json(
              {
                error: {
                  code: 'UNAVAILABLE',
                  message: '项目摘要重读失败',
                  trace_id: 'summary-fail',
                },
              },
              { status: 503 },
            )
          : HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
    )
    const { queryClient } = renderPage()
    try {
      await submitSelfRole('viewer')
      await waitFor(() => expect(queryClient.getQueryState(['projects'])?.status).toBe('error'))
      await act(async () => {})
      expect(screen.getByRole('button', { name: '保存安全策略' })).toBeDisabled()
      expect(screen.getByLabelText('项目用户 ID')).toBeDisabled()
      expect(queryClient.isMutating()).toBe(1)
      expect(fixture.writes).toHaveBeenCalledTimes(1)
      await act(async () => release())
      expect(await screen.findByText('当前身份：Viewer')).toBeVisible()
      await waitFor(() => expect(queryClient.isMutating()).toBe(0))
      expect(screen.queryByText('成员与团队配置已更新')).not.toBeInTheDocument()
    } finally {
      release()
    }
  })

  it('waits for the current permission when another matching permission key fails first', async () => {
    accessRefreshFixture()
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: 15_000 } },
    })
    const inactiveKey = ['project-permissions', project.id, user.id]
    await queryClient.fetchQuery({
      queryKey: inactiveKey,
      queryFn: () => getProjectPermission(project.id),
    })
    renderPage(queryClient)
    await screen.findByText('当前身份：项目 Owner')
    let release!: () => void
    const pending = new Promise<void>((resolve) => {
      release = resolve
    })
    let refreshReads = 0
    server.use(
      http.get(`/api/v1/projects/${project.id}/permissions`, async () => {
        refreshReads += 1
        if (refreshReads === 1)
          return HttpResponse.json(
            {
              error: {
                code: 'UNAVAILABLE',
                message: '备用权限重读失败',
                trace_id: 'permission-key-fail',
              },
            },
            { status: 503 },
          )
        await pending
        return HttpResponse.json({ effective_role: 'viewer', capabilities: ['read'], matrix: {} })
      }),
    )
    try {
      await submitSelfRole('viewer')
      await waitFor(() => expect(queryClient.getQueryState(inactiveKey)?.status).toBe('error'))
      expect(refreshReads).toBe(2)
      await act(async () => {})
      expect(screen.getByRole('button', { name: '保存安全策略' })).toBeDisabled()
      expect(screen.getByLabelText('项目用户 ID')).toBeDisabled()
      expect(queryClient.isMutating()).toBe(1)
      await act(async () => release())
      expect(await screen.findByText('当前身份：Viewer')).toBeVisible()
      await waitFor(() => expect(queryClient.isMutating()).toBe(0))
      expect(screen.queryByText('成员与团队配置已更新')).not.toBeInTheDocument()
    } finally {
      release()
    }
  })

  it('shows failed governance reads and prevents submitting unloaded policy defaults', async () => {
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/*`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'UNAVAILABLE',
              message: '项目治理数据暂不可用',
              trace_id: 'governance-trace',
            },
          },
          { status: 503 },
        ),
      ),
    )
    renderPage()
    expect(await screen.findByText(/项目治理数据暂不可用/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试' })).toBeEnabled()
    expect(screen.getByRole('button', { name: /保存安全策略/ })).toBeDisabled()
  })

  it('shows the permission matrix, updates network policy and renders audit trace', async () => {
    const saved = vi.fn()
    const savedRetention = vi.fn()
    const savedRedaction = vi.fn()
    const savedOutbound = vi.fn()
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/permissions`, () =>
        HttpResponse.json({
          effective_role: 'owner',
          capabilities: [
            'read',
            'edit',
            'execute',
            'manage_members',
            'manage_security',
            'view_audit',
          ],
          matrix: {
            owner: ['read', 'edit', 'execute', 'manage_members', 'manage_security', 'view_audit'],
            editor: ['read', 'edit', 'execute'],
            viewer: ['read'],
          },
        }),
      ),
      http.get(`/api/v1/projects/${project.id}/members`, () => HttpResponse.json([])),
      http.get('/api/v1/teams', () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/team-grants`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${project.id}/folders`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${project.id}/configuration`, () =>
        HttpResponse.json({ variables: [], headers: [] }),
      ),
      http.get(`/api/v1/projects/${project.id}/environments`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${project.id}/secrets`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${project.id}/security-policy`, () =>
        HttpResponse.json({
          enabled: true,
          allowed_hosts: ['api.example.com'],
          allowed_private_cidrs: ['10.20.0.0/16'],
        }),
      ),
      http.put(`/api/v1/projects/${project.id}/security-policy`, async ({ request }) => {
        const body = await request.json()
        saved(body)
        return HttpResponse.json(body)
      }),
      http.get(`/api/v1/projects/${project.id}/outbound-policy`, () =>
        HttpResponse.json({
          outbound_concurrency_limit: 2,
          outbound_requests_per_minute: null,
        }),
      ),
      http.put(`/api/v1/projects/${project.id}/outbound-policy`, async ({ request }) => {
        const body = await request.json()
        savedOutbound(body)
        return HttpResponse.json(body)
      }),
      http.get(`/api/v1/projects/${project.id}/retention-policy`, () =>
        HttpResponse.json({ retention_days: 90, maximum_days: 3650 }),
      ),
      http.put(`/api/v1/projects/${project.id}/retention-policy`, async ({ request }) => {
        const body = (await request.json()) as { retention_days: number }
        savedRetention(body)
        return HttpResponse.json({ ...body, maximum_days: 3650 })
      }),
      http.get(`/api/v1/projects/${project.id}/redaction-policy`, () =>
        HttpResponse.json({ mode: 'off', source: 'installation', policy_version: 1 }),
      ),
      http.put(`/api/v1/projects/${project.id}/redaction-policy`, async ({ request }) => {
        const body = (await request.json()) as { mode: 'off' | 'on' }
        savedRedaction(body)
        return HttpResponse.json({ ...body, source: 'project', policy_version: 2 })
      }),
      http.get(`/api/v1/projects/${project.id}/audit-logs`, () =>
        HttpResponse.json({
          items: [
            {
              id: 'audit-1',
              actor_user_id: 'user-1',
              project_id: project.id,
              action: 'project.security_policy_updated',
              resource_type: 'project',
              resource_id: project.id,
              details: { trace_id: 'trace-governance' },
              created_at: '2026-08-09T10:00:00Z',
            },
          ],
          total: 1,
          page: 1,
          page_size: 50,
        }),
      ),
    )
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByRole('heading', { name: '项目治理' })).toBeVisible()
    expect(await screen.findByText('当前身份：项目 Owner')).toBeVisible()
    expect(await screen.findByText('project.security_policy_updated')).toBeVisible()
    expect(await screen.findByText('trace-governance')).toBeVisible()

    const hosts = await screen.findByLabelText('允许域名（每行一个）')
    await browser.clear(hosts)
    await browser.type(hosts, 'api.example.com{enter}*.internal.example.com')
    await browser.click(screen.getByRole('button', { name: '保存安全策略' }))
    await waitFor(() =>
      expect(saved).toHaveBeenCalledWith({
        enabled: true,
        allowed_hosts: ['api.example.com', '*.internal.example.com'],
        allowed_private_cidrs: ['10.20.0.0/16'],
      }),
    )
    const retention = await screen.findByRole('spinbutton', { name: '保留天数' })
    await browser.clear(retention)
    await browser.type(retention, '120')
    await browser.click(screen.getByRole('button', { name: '保存保留策略' }))
    await waitFor(() => expect(savedRetention).toHaveBeenCalledWith({ retention_days: 120 }))
    const concurrency = await screen.findByRole('spinbutton', { name: '同时请求上限' })
    await browser.clear(concurrency)
    await browser.type(concurrency, '3')
    await browser.click(screen.getByRole('button', { name: '保存出站限额' }))
    await waitFor(() =>
      expect(savedOutbound).toHaveBeenCalledWith({
        outbound_concurrency_limit: 3,
        outbound_requests_per_minute: null,
      }),
    )
    expect(screen.getByText('来源：安装默认')).toBeVisible()
    await browser.click(screen.getByRole('switch', { name: '开启项目脱敏' }))
    await waitFor(() => expect(savedRedaction).toHaveBeenCalledWith({ mode: 'on' }))
  })
})

function renderPage(
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  }),
) {
  const view = render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <ProjectTestProvider section="settings">
          <ProjectsPage />
        </ProjectTestProvider>
      </QueryClientProvider>
    </AntdApp>,
  )
  return { ...view, queryClient }
}

function accessRefreshFixture(
  options: {
    refreshStatus?: () => number | null
    waitRefresh?: () => Promise<void>
    lastOwner?: boolean
  } = {},
) {
  authenticateTestUser({ ...user, is_system_admin: false })
  let role: 'owner' | 'editor' | 'viewer' = 'owner'
  const writes = vi.fn()
  const refreshes = vi.fn()
  const matrix: ProjectPermission['matrix'] = {
    owner: ['read', 'edit', 'execute', 'manage_members', 'manage_security', 'view_audit'],
    editor: ['read', 'edit', 'execute'],
    viewer: ['read'],
  }
  const member = () => ({
    id: 'member-self',
    project_id: project.id,
    user_id: user.id,
    display_name: '当前项目所有者',
    email: user.email,
    role,
  })
  const base = `/api/v1/projects/${project.id}`
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [{ ...project, role }], total: 1, page: 1, page_size: 100 }),
    ),
    http.get(base, () => HttpResponse.json({ ...project, role })),
    http.get(`${base}/permissions`, async () => {
      if (role !== 'owner') {
        refreshes()
        await options.waitRefresh?.()
      }
      const status = role !== 'owner' ? options.refreshStatus?.() : null
      return status
        ? HttpResponse.json(
            {
              error: {
                code: 'UNAVAILABLE',
                message: '权限重读失败',
                trace_id: 'access-refresh-trace',
              },
            },
            { status },
          )
        : HttpResponse.json({ effective_role: role, capabilities: matrix[role], matrix })
    }),
    http.get(`${base}/members`, () =>
      HttpResponse.json([
        member(),
        ...(options.lastOwner
          ? []
          : [
              {
                ...member(),
                id: 'member-other',
                user_id: '00000000-0000-4000-8000-000000000902',
                display_name: '另一位项目所有者',
                role: 'owner',
              },
            ]),
      ]),
    ),
    http.put(`${base}/members/${user.id}`, async ({ request }) => {
      const input = (await request.json()) as { user_id: string; role: typeof role }
      writes(input)
      if (options.lastOwner)
        return HttpResponse.json(
          {
            error: {
              code: 'LAST_PROJECT_OWNER',
              message: '项目至少需要保留一名 Owner',
              trace_id: 'last-owner-trace',
            },
          },
          { status: 409 },
        )
      role = input.role
      return HttpResponse.json(member())
    }),
    http.get(`${base}/team-grants`, () => HttpResponse.json([])),
    http.get(`${base}/folders`, () => HttpResponse.json([])),
    http.get(`${base}/configuration`, () => HttpResponse.json({ variables: [], headers: [] })),
    http.get(`${base}/environments`, () => HttpResponse.json([])),
    http.get(`${base}/secrets`, () => HttpResponse.json([])),
    http.get(`${base}/security-policy`, () =>
      HttpResponse.json({
        enabled: true,
        allowed_hosts: ['api.example.test'],
        allowed_private_cidrs: [],
      }),
    ),
    http.get(`${base}/outbound-policy`, () =>
      HttpResponse.json({ outbound_concurrency_limit: 2, outbound_requests_per_minute: null }),
    ),
    http.get(`${base}/retention-policy`, () =>
      HttpResponse.json({ retention_days: 90, maximum_days: 3650 }),
    ),
    http.get(`${base}/redaction-policy`, () =>
      HttpResponse.json({ mode: 'off', source: 'installation', policy_version: 1 }),
    ),
    http.get(`${base}/audit-logs`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 50 }),
    ),
  )
  return { writes, refreshes }
}

async function submitSelfRole(role: 'viewer' | 'editor') {
  expect(await screen.findByText('当前身份：项目 Owner')).toBeVisible()
  const browser = userEvent.setup()
  await browser.click(screen.getByRole('button', { name: '按 ID 输入' }))
  await browser.click(screen.getByLabelText('项目用户 ID'))
  await browser.paste(user.id)
  if (role === 'editor') {
    await browser.click(screen.getByRole('combobox', { name: '项目成员角色' }))
    await browser.click(screen.getByText('editor', { selector: '.ant-select-item-option-content' }))
  }
  await browser.click(screen.getByRole('button', { name: /添加成员/ }))
}
