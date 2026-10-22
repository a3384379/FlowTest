import {
  QueryClient,
  QueryClientProvider,
  QueryObserver,
  type QueryKey,
} from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { useEffect } from 'react'
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'

import { useAuthStore } from '../features/auth/auth-store'
import { useApiConsole } from '../features/api-console/use-api-console'
import { DraftSessionProvider } from '../features/drafts/DraftSessionProvider'
import ProjectProvider from '../features/projects/ProjectProvider'
import { getProjectPermission, listManagedProjects } from '../features/projects/project-service'
import { useProjectCapabilities } from '../features/projects/use-project-capabilities'
import { useProjectContext } from '../features/projects/use-project-context'
import { useReports } from '../features/reports/use-reports'
import { useTestAssets } from '../features/test-assets/use-test-assets'
import { useWorkflows } from '../features/workflows/use-workflows'
import {
  apiClient,
  SessionBoundaryError,
  setOrganizationId,
  type Page,
  type Project,
  type ProjectPermission,
} from '../lib/api'
import { authenticateTestUser } from '../test/auth'
import { project, user } from '../test/fixtures'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { server } from '../test/server'
import ProjectsPage from './ProjectsPage'

const originalAuth = useAuthStore.getState()
const otherOrganization = '00000000-0000-4000-8000-000000000801'
const otherProject = '00000000-0000-4000-8000-000000000802'
const viewerTeam = '00000000-0000-4000-8000-000000000803'

afterEach(() => useAuthStore.setState(originalAuth))

describe('Project access session boundary', () => {
  it.each([null, 503])(
    'reconciles legal self-removal without reading under another organization (return read=%s)',
    async (returnStatus) => {
      const fixture = accessFixture(returnStatus)
      const client = await seedAuthority()
      const untouched = seedOtherProject(client)
      const view = renderAccess(client)
      await removeSelf(fixture)
      const projectsObserver = new QueryObserver(client, {
        queryKey: ['projects'],
        queryFn: listManagedProjects,
      })
      const stopObserving = projectsObserver.subscribe(() => undefined)
      try {
        await waitFor(() => expect(client.getQueryState(['projects'])?.fetchStatus).toBe('idle'))
        view.unmount()
        act(() => setOrganizationId(otherOrganization))
        await act(async () => fixture.release())
        await waitFor(() => expect(client.isMutating()).toBe(0))

        expect(fixture.applied()).toBe(true)
        expect(fixture.writes()).toBe(1)
        expect(client.getMutationCache().getAll().at(-1)?.state.error).toBeInstanceOf(
          SessionBoundaryError,
        )
        for (const key of originalAuthorityKeys()) {
          expect(client.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(true)
          expect(client.getQueryState(key)?.fetchStatus, JSON.stringify(key)).toBe('idle')
        }
        for (const [key, value] of untouched) {
          expect(client.getQueryData(key)).toBe(value)
          expect(client.getQueryState(key)?.isInvalidated).toBe(false)
        }
        expect(fixture.wrongOrganizationReads()).toEqual([])
        expect(screen.queryByText('成员与团队配置已更新')).not.toBeInTheDocument()
      } finally {
        stopObserving()
      }

      act(() => setOrganizationId(null))
      renderAccess(client)
      if (returnStatus) {
        expect((await screen.findAllByText('权限重读失败'))[0]).toBeVisible()
        await waitFor(() => expect(queryButtonByText('添加成员')).not.toBeInTheDocument())
        expect(getButtonByText('保存安全策略')).toBeDisabled()
        expect(screen.getByTestId('capability-consumer')).toHaveTextContent('readonly')
        fixture.allowReads()
        await userEvent.click(screen.getByLabelText('重试'))
      }
      expect(await screen.findByText('当前身份：Viewer')).toBeVisible()
      expect(queryButtonByText('添加成员')).not.toBeInTheDocument()
      expect(queryButtonByText('新建目录')).not.toBeInTheDocument()
      expect(getButtonByText('保存安全策略')).toBeDisabled()
      await waitFor(() =>
        expect(screen.getByTestId('capability-consumer')).toHaveTextContent('readonly'),
      )
      await waitFor(() =>
        expect(screen.getByTestId('project-role-consumer')).toHaveTextContent('viewer'),
      )
      expect(client.getQueryData(['project-permissions', project.id])).toMatchObject({
        effective_role: 'viewer',
        capabilities: ['read'],
      })
      expect(fixture.writes()).toBe(1)
      expect(fixture.wrongOrganizationReads()).toEqual([])
    },
  )

  it.each([null, 503])(
    'closes explicitly invalidated permission consumers until authority returns (status=%s)',
    async (returnStatus) => {
      const fixture = accessFixture(returnStatus)
      const client = await seedAuthority()
      const view = renderAccess(client, true)
      await removeSelf(fixture)
      view.unmount()
      act(() => setOrganizationId(otherOrganization))
      await act(async () => fixture.release())
      await waitFor(() => expect(client.isMutating()).toBe(0))
      expect(client.getMutationCache().getAll().at(-1)?.state.error).toBeInstanceOf(
        SessionBoundaryError,
      )
      fixture.holdAllPermissions()
      act(() => setOrganizationId(null))
      renderAccess(client, true)
      try {
        await waitFor(() => expect(fixture.permissionStarted()).toBe(true))
        for (const key of permissionReadKeys()) {
          expect(client.getQueryState(key)?.isInvalidated).toBe(true)
          expect(client.getQueryState(key)?.status).toBe('success')
          expect(client.getQueryState(key)?.fetchStatus).toBe('fetching')
        }
        expect.soft(screen.getByTestId('capability-consumer')).toHaveTextContent('readonly')
        expect
          .soft(screen.getByTestId('workflow-capability-consumer'))
          .toHaveTextContent('readonly')
        expect.soft(screen.getByTestId('assets-capability-consumer')).toHaveTextContent('readonly')
        expect.soft(screen.getByTestId('reports-capability-consumer')).toHaveTextContent('readonly')
        expect.soft(queryButtonByText('添加成员')).not.toBeInTheDocument()
        expect.soft(getButtonByText('保存安全策略')).toBeDisabled()
        await act(async () => fixture.releasePermission())
        if (returnStatus) {
          expect((await screen.findAllByText('权限重读失败'))[0]).toBeVisible()
          expect(queryButtonByText('添加成员')).not.toBeInTheDocument()
          expect(getButtonByText('保存安全策略')).toBeDisabled()
          fixture.allowReads()
          await act(async () => {
            await Promise.all(
              permissionReadKeys().map((queryKey) =>
                client.refetchQueries({ queryKey, exact: true }),
              ),
            )
          })
        }
        expect(await screen.findByText('当前身份：Viewer')).toBeVisible()
        for (const id of permissionConsumerIds())
          expect(screen.getByTestId(id)).toHaveTextContent('readonly')
        expect(fixture.writes()).toBe(1)
        expect(fixture.wrongOrganizationReads()).toEqual([])
      } finally {
        fixture.releasePermission()
      }
    },
  )

  it('keeps permission consumers enabled during a naturally stale background refresh', async () => {
    const fixture = accessFixture(null)
    const client = await seedAuthority()
    renderAccess(client, true)
    expect(await screen.findByText('当前身份：项目 Owner')).toBeVisible()
    for (const id of permissionConsumerIds())
      await waitFor(() => expect(screen.getByTestId(id)).toHaveTextContent('editable'))
    for (const queryKey of permissionReadKeys())
      client.setQueryData(queryKey, client.getQueryData(queryKey), {
        updatedAt: Date.now() - 30_000,
      })
    fixture.holdAllPermissions()
    let refresh!: Promise<void[]>
    try {
      act(() => {
        refresh = Promise.all(
          permissionReadKeys().map((queryKey) => client.refetchQueries({ queryKey, exact: true })),
        )
      })
      await waitFor(() => expect(fixture.permissionStarted()).toBe(true))
      for (const key of permissionReadKeys()) {
        expect(client.getQueryState(key)?.isInvalidated).toBe(false)
        expect(client.getQueryState(key)?.fetchStatus).toBe('fetching')
      }
      for (const id of permissionConsumerIds())
        expect(screen.getByTestId(id)).toHaveTextContent('editable')
      expect(getButtonByText('添加成员')).toBeEnabled()
      expect(getButtonByText('保存安全策略')).toBeEnabled()
      await act(async () => {
        fixture.releasePermission()
        await refresh
      })
      for (const id of permissionConsumerIds())
        expect(screen.getByTestId(id)).toHaveTextContent('editable')
      expect(fixture.writes()).toBe(0)
    } finally {
      fixture.releasePermission()
      await refresh
    }
  })

  it('keeps the ordinary unmount success path reading the original permissions', async () => {
    const fixture = accessFixture(null)
    const client = await seedAuthority()
    const view = renderAccess(client)
    await removeSelf(fixture)
    view.unmount()
    await act(async () => fixture.release())
    await waitFor(() => expect(client.isMutating()).toBe(0))
    expect(client.getQueryData(['project-permissions', project.id, user.id])).toMatchObject({
      effective_role: 'viewer',
    })
    expect(client.getMutationCache().getAll().at(-1)?.state.status).toBe('success')
    expect(fixture.writes()).toBe(1)
    expect(screen.queryByText('成员与团队配置已更新')).not.toBeInTheDocument()
  })

  it('locks reopened access controls while the original member command is still pending', async () => {
    const fixture = accessFixture(null)
    const client = await seedAuthority()
    const view = renderAccess(client)
    await removeSelf(fixture)
    view.unmount()
    act(() => setOrganizationId(otherOrganization))
    act(() => setOrganizationId(null))
    renderAccess(client)
    try {
      expect(await screen.findByText('当前身份：项目 Owner')).toBeVisible()
      expect(client.isMutating()).toBe(1)
      expect(screen.getByLabelText('项目用户')).toBeDisabled()
      expect(screen.getByLabelText('项目成员角色')).toBeDisabled()
      const ownRow = (await screen.findByText(user.email)).closest('tr')!
      expect(within(ownRow).getByLabelText('移除项目成员')).toBeDisabled()
      expect(getButtonByText('保存安全策略')).toBeDisabled()
      await act(async () => fixture.release())
      await waitFor(() => expect(client.isMutating()).toBe(0))
      expect(await screen.findByText('当前身份：Viewer')).toBeVisible()
      expect(fixture.writes()).toBe(1)
      expect(fixture.wrongOrganizationReads()).toEqual([])
    } finally {
      await act(async () => fixture.release())
      await waitFor(() => expect(client.isMutating()).toBe(0))
    }
  })

  it('does not restore old Owner capabilities from a pre-write GET after returning', async () => {
    const fixture = accessFixture(null)
    const client = await seedAuthority()
    const view = renderAccess(client)
    expect(await screen.findByText('当前身份：项目 Owner')).toBeVisible()
    let confirmOldReceipt!: () => void
    const oldReceipt = new Promise<void>((resolve) => {
      confirmOldReceipt = resolve
    })
    const receiptObserver = apiClient.interceptors.response.use((response) => {
      if (
        response.config.url === `/projects/${project.id}/permissions` &&
        (response.data as ProjectPermission).effective_role === 'owner' &&
        fixture.applied()
      )
        confirmOldReceipt()
      return response
    })
    fixture.holdPermission()
    let background!: Promise<void>
    act(() => {
      background = client.refetchQueries({
        queryKey: ['project-permissions', project.id, user.id],
        exact: true,
      })
    })
    await waitFor(() => expect(fixture.permissionStarted()).toBe(true))
    try {
      await removeSelf(fixture)
      view.unmount()
      act(() => setOrganizationId(otherOrganization))
      await act(async () => fixture.release())
      await waitFor(() => expect(client.isMutating()).toBe(0))
      expect(client.getMutationCache().getAll().at(-1)?.state.error).toBeInstanceOf(
        SessionBoundaryError,
      )
      expect(
        client.getQueryState(['project-permissions', project.id, user.id])?.isInvalidated,
      ).toBe(true)
      expect(client.getQueryState(['project-permissions', project.id, user.id])?.fetchStatus).toBe(
        'idle',
      )
      act(() => setOrganizationId(null))
      renderAccess(client)
      expect(await screen.findByText('当前身份：Viewer')).toBeVisible()
      await act(async () => {
        fixture.releasePermission()
        await background
        await oldReceipt
      })
      expect(fixture.writes()).toBe(1)
      expect(fixture.wrongOrganizationReads()).toEqual([])
      await waitFor(() =>
        expect(screen.getByTestId('capability-consumer')).toHaveTextContent('readonly'),
      )
      expect(client.getQueryData(['project-permissions', project.id, user.id])).toMatchObject({
        effective_role: 'viewer',
        capabilities: ['read'],
      })
    } finally {
      fixture.release()
      fixture.releasePermission()
      await background
      apiClient.interceptors.response.eject(receiptObserver)
    }
  })

  it.each([null, 503])(
    'keeps a persistent provider readonly while restoring explicit invalidation (role read=%s)',
    async (roleStatus) => {
      const fixture = accessFixture(null)
      const client = await seedAuthority()
      renderPersistentAccess(client)
      await removeSelf(fixture)
      const browser = userEvent.setup()
      await browser.click(screen.getByText('进入组织', { selector: 'a' }))
      await screen.findByText('组织边界页')
      await waitFor(() => expect(useAuthStore.getState().organizationId).toBe(otherOrganization))
      await act(async () => fixture.release())
      await waitFor(() => expect(client.isMutating()).toBe(0))
      expect(client.getMutationCache().getAll().at(-1)?.state.error).toBeInstanceOf(
        SessionBoundaryError,
      )
      fixture.holdRoleReads(roleStatus)
      try {
        await browser.click(screen.getByText('返回项目', { selector: 'a' }))
        expect(await screen.findByText('当前身份：Viewer')).toBeVisible()
        await waitFor(() => expect(fixture.roleReadsStarted()).toBeGreaterThan(0))
        expect(screen.getByTestId('project-role-consumer')).toHaveTextContent('unknown')
        expect(screen.getByTestId('api-role-consumer')).toHaveTextContent('readonly')
        expect(fixture.wrongOrganizationReads()).toEqual([])
        await act(async () => fixture.releaseRoleReads())
        if (roleStatus) {
          await waitFor(() =>
            expect(client.getQueryState(['project', project.id])?.status).toBe('error'),
          )
          expect(screen.getByTestId('project-role-consumer')).toHaveTextContent('unknown')
        } else {
          await waitFor(() =>
            expect(screen.getByTestId('project-role-consumer')).toHaveTextContent('viewer'),
          )
          expect(client.getQueryData(['projects'])).toMatchObject({ items: [{ role: 'viewer' }] })
        }
        expect(screen.getByTestId('api-role-consumer')).toHaveTextContent('readonly')
        expect(fixture.writes()).toBe(1)
        expect(fixture.wrongOrganizationReads()).toEqual([])
      } finally {
        fixture.releaseRoleReads()
      }
    },
  )
})

function queryButtonByText(label: string): HTMLButtonElement | null {
  return screen.queryByText(label)?.closest('button') ?? null
}

function getButtonByText(label: string): HTMLButtonElement {
  const button = screen.getByText(label).closest('button')
  if (!button) throw new Error(`Missing button: ${label}`)
  return button
}

function permissionReadKeys(): QueryKey[] {
  return [
    ['project-permissions', project.id],
    ['project-permissions', project.id, user.id],
    ['project-permission', project.id],
  ]
}

function permissionConsumerIds(): string[] {
  return [
    'capability-consumer',
    'workflow-capability-consumer',
    'assets-capability-consumer',
    'reports-capability-consumer',
  ]
}

function originalAuthorityKeys(): QueryKey[] {
  return [
    ['project-permissions', project.id],
    ['project-permissions', project.id, user.id],
    ['project-permission', project.id],
    ['project', project.id],
    ['projects'],
    ['project-members', project.id],
    ['project-team-grants', project.id],
    ['project-audit', project.id, 1, ''],
    ['access-directory', { kind: 'project-user', projectId: project.id }, '', 1],
  ]
}

async function seedAuthority() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 15_000 },
      mutations: { retry: false },
    },
  })
  for (const queryKey of originalAuthorityKeys()) {
    if (String(queryKey[0]).startsWith('project-permission'))
      await client.fetchQuery({ queryKey, queryFn: () => getProjectPermission(project.id) })
    else if (queryKey[0] === 'project-audit')
      client.setQueryData(queryKey, { items: [], total: 0, page: 1, page_size: 50 })
    else if (queryKey[0] === 'access-directory')
      client.setQueryData(queryKey, { options: [], total: 0 })
  }
  return client
}

function seedOtherProject(client: QueryClient): [QueryKey, unknown][] {
  const entries: [QueryKey, unknown][] = [
    [['project-permissions', otherProject, user.id], { effective_role: 'owner' }],
    [['project-permission', otherProject], { effective_role: 'owner' }],
    [['project', otherProject], { ...project, id: otherProject }],
    [['project-members', otherProject], []],
    [['project-team-grants', otherProject], []],
    [['project-audit', otherProject, 1, ''], { items: [] }],
    [
      ['access-directory', { kind: 'project-user', projectId: otherProject }, '', 1],
      { options: [], total: 0 },
    ],
    [['team-members', viewerTeam], [{ user_id: user.id }]],
  ]
  for (const [key, value] of entries) client.setQueryData(key, value)
  return entries
}

function PermissionConsumers() {
  const capabilities = useProjectCapabilities()
  const { currentProject } = useProjectContext()
  return (
    <>
      <span data-testid="capability-consumer">
        {capabilities.canEdit ? 'editable' : 'readonly'}
      </span>
      <span data-testid="project-role-consumer">{currentProject?.role ?? 'unknown'}</span>
    </>
  )
}

function ApiRoleConsumer() {
  const api = useApiConsole()
  return <span data-testid="api-role-consumer">{api.canEdit ? 'editable' : 'readonly'}</span>
}

function OrganizationBoundary() {
  useEffect(() => {
    setOrganizationId(otherOrganization)
    return () => setOrganizationId(null)
  }, [])
  return <span>组织边界页</span>
}

function renderPersistentAccess(client: QueryClient) {
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App>
        <QueryClientProvider client={client}>
          <MemoryRouter initialEntries={[`/projects/${project.id}/settings`]}>
            <ProjectProvider>
              <Link to="/organization">进入组织</Link>
              <Link to={`/projects/${project.id}/settings`}>返回项目</Link>
              <Routes>
                <Route path="/organization" element={<OrganizationBoundary />} />
                <Route
                  path="/projects/:projectId/settings"
                  element={
                    <>
                      <ProjectsPage />
                      <PermissionConsumers />
                      <ApiRoleConsumer />
                    </>
                  }
                />
              </Routes>
            </ProjectProvider>
          </MemoryRouter>
        </QueryClientProvider>
      </App>
    </ConfigProvider>,
  )
}

function OtherPermissionConsumers() {
  const workflow = useWorkflows()
  const assets = useTestAssets()
  const reports = useReports()
  return (
    <>
      <span data-testid="workflow-capability-consumer">
        {workflow.canEdit ? 'editable' : 'readonly'}
      </span>
      <span data-testid="assets-capability-consumer">
        {assets.canEdit ? 'editable' : 'readonly'}
      </span>
      <span data-testid="reports-capability-consumer">
        {reports.canManageNotifications ? 'editable' : 'readonly'}
      </span>
    </>
  )
}

function renderAccess(client: QueryClient, withPermissionConsumers = false) {
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App>
        <QueryClientProvider client={client}>
          <ProjectTestProvider section="settings">
            <ProjectsPage />
            <PermissionConsumers />
            {withPermissionConsumers && (
              <DraftSessionProvider>
                <OtherPermissionConsumers />
              </DraftSessionProvider>
            )}
          </ProjectTestProvider>
        </QueryClientProvider>
      </App>
    </ConfigProvider>,
  )
}

async function removeSelf(fixture: ReturnType<typeof accessFixture>) {
  expect(await screen.findByText('当前身份：项目 Owner')).toBeVisible()
  const ownRow = (await screen.findByText(user.email)).closest('tr')!
  const browser = userEvent.setup()
  const remove = within(ownRow).getByLabelText('移除项目成员')
  expect(remove).toBeEnabled()
  remove.focus()
  expect(remove).toHaveFocus()
  await browser.keyboard('{Enter}')
  await screen.findByText('OK')
  const confirm = getButtonByText('OK')
  expect(confirm).toBeEnabled()
  confirm.focus()
  expect(confirm).toHaveFocus()
  await browser.keyboard('{Enter}')
  await waitFor(() => expect(fixture.writes()).toBe(1))
}

function accessFixture(returnStatus: number | null) {
  authenticateTestUser({ ...user, is_system_admin: false })
  setOrganizationId(null)
  let release!: () => void
  const pending = new Promise<void>((resolve) => {
    release = resolve
  })
  let applied = false
  let writes = 0
  let status = returnStatus
  let holdPermission = false
  let holdAllPermissions = false
  let permissionStarted = false
  let releasePermission!: () => void
  const pendingPermission = new Promise<void>((resolve) => {
    releasePermission = resolve
  })
  let holdRoleReads = false
  let roleStatus: number | null = null
  let roleReadsStarted = 0
  let releaseRoleReads!: () => void
  const pendingRoleReads = new Promise<void>((resolve) => {
    releaseRoleReads = resolve
  })
  const wrongOrganizationReads: string[] = []
  const base = `/api/v1/projects/${project.id}`
  const member = {
    id: 'self-membership',
    project_id: project.id,
    user_id: user.id,
    display_name: user.display_name,
    email: user.email,
    role: 'owner',
  }
  const remainingOwner = {
    ...member,
    id: 'remaining-owner',
    user_id: '00000000-0000-4000-8000-000000000804',
    display_name: '另一位项目所有者',
    email: 'remaining-owner@example.test',
  }
  const currentProject = (): Project => ({ ...project, role: applied ? 'viewer' : 'owner' })
  const recordRead = (request: Request) => {
    if (request.headers.get('X-Organization-ID') === otherOrganization)
      wrongOrganizationReads.push(request.url)
  }
  const readRole = async (data: Project | Page<Project>) => {
    if (applied && holdRoleReads) {
      roleReadsStarted += 1
      await pendingRoleReads
    }
    return applied && roleStatus
      ? HttpResponse.json(
          {
            error: { code: 'UNAVAILABLE', message: '项目角色读取失败', trace_id: 'role-read-fail' },
          },
          { status: roleStatus },
        )
      : HttpResponse.json(data)
  }
  server.use(
    http.get('/api/v1/credentials', () => HttpResponse.json([])),
    http.get('/api/v1/graphql/schemas', () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
    ),
    http.get('/api/v1/grpc/descriptors', () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
    ),
    http.get('/api/v1/event-sources', () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
    ),
    http.get('/api/v1/projects', ({ request }) => {
      recordRead(request)
      return readRole({ items: [currentProject()], total: 1, page: 1, page_size: 100 })
    }),
    http.get(base, ({ request }) => {
      recordRead(request)
      return readRole(currentProject())
    }),
    http.get(`${base}/*`, ({ request }) => {
      recordRead(request)
    }),
    http.get(`${base}/permissions`, async () => {
      const response =
        applied && status
          ? HttpResponse.json(
              { error: { code: 'UNAVAILABLE', message: '权限重读失败', trace_id: 'read-failure' } },
              { status },
            )
          : HttpResponse.json({
              effective_role: applied ? 'viewer' : 'owner',
              capabilities: applied
                ? ['read']
                : ['read', 'edit', 'execute', 'manage_members', 'manage_security', 'view_audit'],
              matrix: { owner: [], editor: [], viewer: [] },
            })
      if (holdPermission || holdAllPermissions) {
        holdPermission = false
        permissionStarted = true
        await pendingPermission
      }
      return response
    }),
    http.get(`${base}/members`, () =>
      HttpResponse.json(applied ? [remainingOwner] : [member, remainingOwner]),
    ),
    http.get(`${base}/team-grants`, () =>
      HttpResponse.json([
        {
          id: 'viewer-team-grant',
          project_id: project.id,
          team_id: viewerTeam,
          team_name: '当前用户所属只读团队',
          role: 'viewer',
        },
      ]),
    ),
    http.delete(`${base}/members/${user.id}`, async () => {
      writes += 1
      await pending
      applied = true
      return new HttpResponse(null, { status: 204 })
    }),
    http.get(`${base}/folders`, () => HttpResponse.json([])),
    http.get(`${base}/configuration`, () => HttpResponse.json({ variables: [], headers: [] })),
    http.get(`${base}/environments`, () => HttpResponse.json([])),
    http.get(`${base}/apis`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 50 }),
    ),
    http.get(`${base}/files`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 50 }),
    ),
    http.get(`${base}/services`, () => HttpResponse.json([])),
    http.get(`${base}/workflows`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
    ),
    http.get(`${base}/test-cases`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
    ),
    http.get(`${base}/test-suites`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
    ),
    http.get(`${base}/test-assets/directory-counts`, () =>
      HttpResponse.json({ total: 0, unfiled: 0, folders: [] }),
    ),
    http.get(`${base}/reports/executions`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
    ),
    http.get(`${base}/reports/trends`, () =>
      HttpResponse.json({ summary: { pending: 0 }, points: [], failures: [] }),
    ),
    http.get(`${base}/notification-webhooks`, () => HttpResponse.json([])),
    http.get(`${base}/notification-deliveries`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
    ),
    http.get(`${base}/secrets`, () => HttpResponse.json([])),
    http.get(`${base}/security-policy`, () =>
      HttpResponse.json({ enabled: true, allowed_hosts: [], allowed_private_cidrs: [] }),
    ),
    http.get(`${base}/outbound-policy`, () =>
      HttpResponse.json({ outbound_concurrency_limit: 2, outbound_requests_per_minute: null }),
    ),
    http.get(`${base}/retention-policy`, () =>
      HttpResponse.json({ retention_days: 90, maximum_days: 3650 }),
    ),
    http.get(`${base}/audit-logs`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 50 }),
    ),
  )
  return {
    release,
    holdPermission: () => {
      holdPermission = true
    },
    holdAllPermissions: () => {
      holdAllPermissions = true
    },
    permissionStarted: () => permissionStarted,
    releasePermission,
    holdRoleReads: (status: number | null) => {
      holdRoleReads = true
      roleStatus = status
    },
    roleReadsStarted: () => roleReadsStarted,
    releaseRoleReads,
    applied: () => applied,
    writes: () => writes,
    wrongOrganizationReads: () => wrongOrganizationReads,
    allowReads: () => {
      status = null
    },
  }
}
