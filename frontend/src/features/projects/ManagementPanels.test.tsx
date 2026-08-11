import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'

import AccessManagementPanel from './AccessManagementPanel'
import AssetManagementPanel from './AssetManagementPanel'
import { useAuthStore } from '../auth/auth-store'
import { server } from '../../test/server'

const projectId = 'project-management'

describe('project management panels', () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: {
        id: 'admin-1',
        email: 'admin@example.com',
        display_name: 'Admin',
        is_active: true,
        is_system_admin: true,
        requires_password_change: false,
        oidc_provider: null,
        oidc_subject: null,
        last_login_at: null,
      },
    })
  })

  it('renders direct members, team grants, and organization membership', async () => {
    server.use(
      http.get('/api/v1/users', () =>
        HttpResponse.json({ items: [user], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${projectId}/members`, () =>
        HttpResponse.json([
          {
            id: 'member-1',
            project_id: projectId,
            user_id: user.id,
            role: 'owner',
            created_at: '2026-08-09T00:00:00Z',
            updated_at: '2026-08-09T00:00:00Z',
          },
        ]),
      ),
      http.get('/api/v1/teams', () =>
        HttpResponse.json({ items: [team], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${projectId}/team-grants`, () =>
        HttpResponse.json([
          {
            id: 'grant-1',
            project_id: projectId,
            team_id: team.id,
            role: 'editor',
            created_by_id: 'admin-1',
            created_at: '2026-08-09T00:00:00Z',
            updated_at: '2026-08-09T00:00:00Z',
          },
          {
            id: 'grant-unknown',
            project_id: projectId,
            team_id: 'team-unknown',
            role: 'viewer',
            created_by_id: 'admin-1',
            created_at: '2026-08-09T00:00:00Z',
            updated_at: '2026-08-09T00:00:00Z',
          },
        ]),
      ),
      http.get(`/api/v1/teams/${team.id}/members`, () =>
        HttpResponse.json([
          {
            id: 'team-member-1',
            team_id: team.id,
            user_id: user.id,
            created_at: '2026-08-09T00:00:00Z',
            updated_at: '2026-08-09T00:00:00Z',
          },
          {
            id: 'team-member-unknown',
            team_id: team.id,
            user_id: 'user-unknown',
            created_at: '2026-08-09T00:00:00Z',
            updated_at: '2026-08-09T00:00:00Z',
          },
        ]),
      ),
    )
    renderPanel(<AccessManagementPanel projectId={projectId} canManage />)
    expect(await screen.findByText(user.id)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: '团队授权' }))
    expect(await screen.findByText(team.name)).toBeInTheDocument()
    expect(screen.getByText('editor')).toBeInTheDocument()
    expect(screen.getByText('team-unknown')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: '用户与团队' }))
    expect(await screen.findByRole('button', { name: '创建用户' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '添加到团队' })).toBeInTheDocument()
    expect(screen.getByText(user.email)).toBeInTheDocument()
    expect(screen.getByText('user-unknown')).toBeInTheDocument()
  })

  it('renders folder, configuration, environment, and write-only secret editors', async () => {
    server.use(
      http.get(`/api/v1/projects/${projectId}/folders`, () =>
        HttpResponse.json([
          folder,
          { ...folder, id: 'folder-child', name: '支付接口', parent_id: folder.id },
          { ...folder, id: 'folder-orphan', name: '孤立目录', parent_id: 'folder-missing' },
        ]),
      ),
      http.get(`/api/v1/projects/${projectId}/configuration`, () =>
        HttpResponse.json({
          project_id: projectId,
          variables: { region: 'cn' },
          headers: { 'X-Project': 'FlowTest' },
        }),
      ),
      http.get(`/api/v1/projects/${projectId}/environments`, () =>
        HttpResponse.json([environment]),
      ),
      http.get(`/api/v1/projects/${projectId}/secrets`, () =>
        HttpResponse.json([
          {
            id: 'secret-1',
            project_id: projectId,
            environment_id: environment.id,
            name: 'API_TOKEN',
            created_by_id: 'admin-1',
            created_at: '2026-08-09T00:00:00Z',
            updated_at: '2026-08-09T00:00:00Z',
          },
          {
            id: 'secret-global',
            project_id: projectId,
            environment_id: null,
            name: 'GLOBAL_TOKEN',
            created_by_id: 'admin-1',
            created_at: '2026-08-09T00:00:00Z',
            updated_at: '2026-08-09T00:00:00Z',
          },
        ]),
      ),
    )
    renderPanel(<AssetManagementPanel projectId={projectId} canEdit />)
    expect((await screen.findAllByText(folder.name)).length).toBeGreaterThanOrEqual(2)

    fireEvent.click(screen.getByRole('tab', { name: '项目变量与 Header' }))
    expect(await screen.findByDisplayValue(/"region": "cn"/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: '环境' }))
    expect(await screen.findByRole('button', { name: '创建环境' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: 'Secret' }))
    expect(await screen.findByText('API_TOKEN')).toBeInTheDocument()
    expect(screen.getByText('GLOBAL_TOKEN')).toBeInTheDocument()
    expect(screen.getAllByText('全项目').length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText('已加密 · 不可读回')).toHaveLength(2)
  })

  it('creates folders through the typed editor', async () => {
    let creations = 0
    registerAssetQueries()
    server.use(
      http.post(`/api/v1/projects/${projectId}/folders`, async ({ request }) => {
        expect(await request.json()).toMatchObject({ name: '支付接口' })
        creations += 1
        return HttpResponse.json({ ...folder, id: 'folder-2', name: '支付接口' }, { status: 201 })
      }),
    )
    renderPanel(<AssetManagementPanel projectId={projectId} canEdit />)
    expect(await screen.findByText(folder.name)).toBeInTheDocument()
    const folderName = screen.getByPlaceholderText('目录名称')
    fireEvent.change(folderName, { target: { value: '支付接口' } })
    fireEvent.click(screen.getByRole('button', { name: /新建目录/ }))
    await waitFor(() => expect(creations).toBe(1))
  })

  it('validates and saves project configuration records', async () => {
    let updates = 0
    registerAssetQueries()
    server.use(
      http.put(`/api/v1/projects/${projectId}/configuration`, async ({ request }) => {
        expect(await request.json()).toEqual({
          variables: {},
          headers: { 'X-Project': 'FlowTest' },
        })
        updates += 1
        return HttpResponse.json({ project_id: projectId, variables: {}, headers: {} })
      }),
    )
    renderPanel(<AssetManagementPanel projectId={projectId} canEdit />)
    expect(await screen.findByText(folder.name)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: '项目变量与 Header' }))
    const panel = screen.getByRole('tabpanel')
    const records = within(panel).getAllByRole('textbox')
    fireEvent.change(records[0], { target: { value: '["invalid"]' } })
    fireEvent.click(within(panel).getByRole('button', { name: '保存项目配置' }))
    expect(await screen.findByText('请输入字符串键值对 JSON 对象')).toBeInTheDocument()
    for (const invalidRecord of ['null', '"text"', '{"attempts":3}']) {
      fireEvent.change(records[0], { target: { value: invalidRecord } })
      fireEvent.click(within(panel).getByRole('button', { name: '保存项目配置' }))
      expect(updates).toBe(0)
    }
    fireEvent.change(records[0], { target: { value: '' } })
    fireEvent.change(records[1], { target: { value: '{"X-Project":"FlowTest"}' } })
    fireEvent.click(within(panel).getByRole('button', { name: '保存项目配置' }))
    await waitFor(() => expect(updates).toBe(1))
  })

  it('creates environments and write-only secrets', async () => {
    const calls = { environment: 0, secret: 0 }
    registerAssetQueries()
    server.use(
      http.post(`/api/v1/projects/${projectId}/environments`, async ({ request }) => {
        expect(await request.json()).toMatchObject({ name: '开发环境' })
        calls.environment += 1
        return HttpResponse.json({ ...environment, id: 'environment-2', name: '开发环境' })
      }),
      http.put(`/api/v1/projects/${projectId}/secrets`, async ({ request }) => {
        expect(await request.json()).toEqual({
          name: 'API_TOKEN',
          value: 'secret-value',
          environment_id: null,
        })
        calls.secret += 1
        return HttpResponse.json({
          id: 'secret-1',
          project_id: projectId,
          environment_id: null,
          name: 'API_TOKEN',
          created_by_id: 'admin-1',
          created_at: '2026-08-09T00:00:00Z',
          updated_at: '2026-08-09T00:00:00Z',
        })
      }),
    )
    renderPanel(<AssetManagementPanel projectId={projectId} canEdit />)
    expect(await screen.findByText(folder.name)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: '环境' }))
    let panel = screen.getByRole('tabpanel')
    const environmentInputs = within(panel).getAllByRole('textbox')
    fireEvent.change(environmentInputs[0], { target: { value: '开发环境' } })
    fireEvent.change(environmentInputs[1], { target: { value: 'https://dev.example.com' } })
    fireEvent.click(within(panel).getByRole('button', { name: '创建环境' }))
    await waitFor(() => expect(calls.environment).toBe(1))

    fireEvent.click(screen.getByRole('tab', { name: 'Secret' }))
    panel = screen.getByRole('tabpanel')
    fireEvent.change(within(panel).getByPlaceholderText('Secret 名称'), {
      target: { value: 'API_TOKEN' },
    })
    fireEvent.change(within(panel).getByPlaceholderText('仅写入，不可读回'), {
      target: { value: 'secret-value' },
    })
    fireEvent.click(within(panel).getByRole('button', { name: '写入 Secret' }))
    await waitFor(() => expect(calls.secret).toBe(1))
  })

  it('hides mutation controls from a non-admin viewer', async () => {
    useAuthStore.setState({
      user: {
        id: 'viewer-1',
        email: 'viewer@example.com',
        display_name: 'Viewer',
        is_active: true,
        is_system_admin: false,
        requires_password_change: false,
        oidc_provider: null,
        oidc_subject: null,
        last_login_at: null,
      },
    })
    server.use(
      http.get(`/api/v1/projects/${projectId}/members`, () => HttpResponse.json([])),
      http.get('/api/v1/teams', () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${projectId}/team-grants`, () => HttpResponse.json([])),
    )
    renderPanel(<AccessManagementPanel projectId={projectId} canManage={false} />)
    expect((await screen.findAllByText('No data')).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: '添加成员' })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: '用户与团队' })).not.toBeInTheDocument()
  })
})

function renderPanel(panel: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>{panel}</QueryClientProvider>
    </AntdApp>,
  )
}

function registerAssetQueries() {
  server.use(
    http.get(`/api/v1/projects/${projectId}/folders`, () => HttpResponse.json([folder])),
    http.get(`/api/v1/projects/${projectId}/configuration`, () =>
      HttpResponse.json({ project_id: projectId, variables: {}, headers: {} }),
    ),
    http.get(`/api/v1/projects/${projectId}/environments`, () => HttpResponse.json([environment])),
    http.get(`/api/v1/projects/${projectId}/secrets`, () => HttpResponse.json([])),
  )
}

const user = {
  id: 'user-1',
  email: 'member@example.com',
  display_name: 'Member',
  is_active: true,
  is_system_admin: false,
  requires_password_change: false,
  oidc_provider: null,
  oidc_subject: null,
  last_login_at: null,
}

const team = {
  id: 'team-1',
  name: 'Quality Team',
  description: '',
  created_by_id: 'admin-1',
  created_at: '2026-08-09T00:00:00Z',
  updated_at: '2026-08-09T00:00:00Z',
}

const folder = {
  id: 'folder-1',
  project_id: projectId,
  parent_id: null,
  name: '订单接口',
  created_by_id: 'admin-1',
  created_at: '2026-08-09T00:00:00Z',
  updated_at: '2026-08-09T00:00:00Z',
}

const environment = {
  id: 'environment-1',
  project_id: projectId,
  name: '测试环境',
  base_url: 'https://api.example.com',
  variables: { region: 'cn' },
  headers: {},
}
