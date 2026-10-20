import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from 'antd'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { project, user } from '../../test/fixtures'
import { authenticateTestUser } from '../../test/auth'
import { server } from '../../test/server'
import { useAuthStore } from '../auth/auth-store'
import AccessManagementPanel from './AccessManagementPanel'

const candidate = {
  id: '00000000-0000-4000-8000-000000000105',
  display_name: '第101位成员',
  email: 'candidate105@example.com',
  is_active: true,
}
const team = { id: '00000000-0000-4000-8000-000000000106', name: '第101个团队' }
const previousAuth = useAuthStore.getState()

function renderPanel(canManage = true) {
  return render(
    <App>
      <QueryClientProvider
        client={
          new QueryClient({
            defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
          })
        }
      >
        <AccessManagementPanel projectId={project.id} canManage={canManage} />
      </QueryClientProvider>
    </App>,
  )
}

describe('AccessManagementPanel', () => {
  beforeEach(() => {
    authenticateTestUser({ ...user, is_system_admin: false })
    server.use(
      http.get(`/api/v1/projects/${project.id}/members`, () =>
        HttpResponse.json([
          {
            id: 'member-1',
            project_id: project.id,
            user_id: user.id,
            display_name: '已有成员',
            email: user.email,
            role: 'owner',
          },
        ]),
      ),
      http.get(`/api/v1/projects/${project.id}/team-grants`, () => HttpResponse.json([])),
    )
  })
  afterEach(() => useAuthStore.setState(previousAuth))

  it('lets a non-admin Owner find and add a named user beyond the first 100 without reading global users', async () => {
    const globalUsers = vi.fn()
    const submitted = vi.fn()
    const searched = vi.fn()
    server.use(
      http.get('/api/v1/users', () => {
        globalUsers()
        return HttpResponse.json({}, { status: 403 })
      }),
      http.post(`/api/v1/projects/${project.id}/member-candidates/search`, async ({ request }) => {
        const input = (await request.json()) as { query: string }
        searched(input)
        return HttpResponse.json({
          items: input.query === 'candidate105' ? [candidate] : [],
          total: input.query === 'candidate105' ? 1 : 0,
          page: 1,
          page_size: 20,
        })
      }),
      http.put(`/api/v1/projects/${project.id}/members/${candidate.id}`, async ({ request }) => {
        submitted(await request.json())
        return HttpResponse.json({ ...candidate, id: 'new-member' })
      }),
    )
    renderPanel()
    expect(await screen.findByText('已有成员')).toBeVisible()
    const browser = userEvent.setup()
    await browser.click(screen.getByRole('combobox', { name: '项目用户' }))
    await browser.type(screen.getByRole('combobox', { name: '项目用户' }), 'candidate105')
    await browser.click(await screen.findByText('第101位成员 (candidate105@example.com)'))
    expect(searched).toHaveBeenCalledWith({ query: 'candidate105', page: 1, page_size: 20 })
    await browser.click(screen.getByRole('button', { name: /添加成员/ }))
    await waitFor(() =>
      expect(submitted).toHaveBeenCalledWith({ user_id: candidate.id, role: 'viewer' }),
    )
    expect(globalUsers).not.toHaveBeenCalled()
    expect(screen.queryByText('用户与团队')).not.toBeInTheDocument()
  })

  it('shows member read errors instead of an empty table, disables writes, and retains the filled identity for retry', async () => {
    let failed = true
    server.use(
      http.get(`/api/v1/projects/${project.id}/members`, () =>
        failed
          ? HttpResponse.json(
              {
                error: { code: 'UNAVAILABLE', message: '成员读取失败', trace_id: 'members-error' },
              },
              { status: 503 },
            )
          : HttpResponse.json([]),
      ),
    )
    renderPanel()
    expect(await screen.findByText('成员读取失败')).toBeVisible()
    expect(screen.queryByText('暂无数据')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /添加成员/ })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: '按 ID 输入' }))
    const id = screen.getByRole('textbox', { name: '项目用户 ID' })
    await userEvent.type(id, candidate.id)
    failed = false
    await userEvent.click(screen.getByRole('button', { name: '重试' }))
    await waitFor(() => expect(screen.getByRole('button', { name: /添加成员/ })).toBeEnabled())
    expect(id).toHaveValue(candidate.id)
  })

  it('searches teams on the server and keeps grant identity independent of the directory page', async () => {
    const granted = vi.fn()
    server.use(
      http.put(`/api/v1/projects/${project.id}/team-grants/${team.id}`, async ({ request }) => {
        granted(await request.json())
        return HttpResponse.json({
          id: 'grant-new',
          team_id: team.id,
          team_name: team.name,
          role: 'viewer',
        })
      }),
      http.get(`/api/v1/projects/${project.id}/team-grants`, () =>
        HttpResponse.json([
          { id: 'grant-1', team_id: 'other-team', team_name: '已有授权组', role: 'viewer' },
        ]),
      ),
      http.post('/api/v1/teams/search', async ({ request }) => {
        const input = (await request.json()) as { query: string }
        return HttpResponse.json({
          items: input.query === '101' ? [team] : [],
          total: input.query === '101' ? 1 : 0,
          page: 1,
          page_size: 20,
        })
      }),
    )
    renderPanel()
    await userEvent.click(screen.getByRole('tab', { name: '团队授权' }))
    expect(await screen.findByText('已有授权组')).toBeVisible()
    await userEvent.type(screen.getByRole('combobox', { name: '授权团队' }), '101')
    await userEvent.click(await screen.findByText('第101个团队'))
    await userEvent.click(screen.getByRole('button', { name: /授权团队/ }))
    await waitFor(() => expect(granted).toHaveBeenCalledWith({ team_id: team.id, role: 'viewer' }))
    expect(screen.getByText('已有授权组')).toBeVisible()
  })

  it('keeps viewers read-only and shows identity summaries', async () => {
    renderPanel(false)
    const table = await screen.findByRole('table')
    expect(await within(table).findByText('已有成员')).toBeVisible()
    expect(screen.queryByRole('button', { name: /添加成员/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '移除项目成员' })).not.toBeInTheDocument()
  })
})
