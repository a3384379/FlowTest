import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import {
  createMemoryRouter,
  Link,
  MemoryRouter,
  RouterProvider,
  useLocation,
} from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

import { SessionBoundaryError, setOrganizationId, type ApiDetail } from '../../lib/api'
import { authenticateTestUser } from '../../test/auth'
import { apiDefinition, project, user } from '../../test/fixtures'
import { server } from '../../test/server'
import { useAuthStore } from '../auth/auth-store'
import { DraftSessionProvider } from '../drafts/DraftSessionProvider'
import WorkspaceObjectTabs from '../navigation/WorkspaceObjectTabs'
import {
  readWorkspaceTabs,
  routeWorkspaceTab,
  writeWorkspaceTabs,
} from '../navigation/workspace-tab-store'
import ProjectTestProvider from '../../test/ProjectTestProvider'
import ProjectProvider from '../projects/ProjectProvider'
import APIWorkbench from './APIWorkbench'
import { apiDefinitionKey, apiDetailKey } from './api-query-keys'
import { useApiConsole } from './use-api-console'

const secondApi = '00000000-0000-4000-8000-000000000031'
const otherOrganization = '00000000-0000-4000-8000-000000000801'
const renamed = '接口B权威新名称'
const apiHref = (id: string) => `/projects/${project.id}/apis?focus=${id}`
const draftKey = (id: string) =>
  `flowtest:api-draft:v1:${encodeURIComponent(`${user.id}:${project.id}`)}:${encodeURIComponent(id)}`

function heldResponse() {
  let release!: () => void
  const promise = new Promise<void>((resolve) => {
    release = resolve
  })
  return { promise, release }
}

function detail(id: string, name: string, version = 4): ApiDetail {
  return {
    definition: { ...apiDefinition, id, name, current_version: 4 },
    version: {
      id: `${id}-v${version}`,
      api_definition_id: id,
      version,
      method: 'GET',
      path: `/server-${id.slice(-1)}-v${version}`,
      query_parameters: [],
      headers: {},
      body_kind: 'none',
      body: null,
      auth_kind: 'none',
      auth_config: {},
      extraction_rules: [],
      assertions: [],
      created_at: '2026-10-22T00:00:00Z',
    },
  }
}

type DefinitionRead = { id: string; organization: string | null; version: string | null }

async function resumeOriginalScope(
  client: QueryClient,
  recoveryError: boolean,
  reads: DefinitionRead[],
  readsBeforeReturn: number,
) {
  const epoch = useAuthStore.getState().epoch
  act(() => {
    setOrganizationId(null)
    useAuthStore.setState({ user: { ...user, id: 'other-user' }, epoch: epoch + 1 })
  })
  expect(client.getQueryState(apiDefinitionKey(project.id, secondApi))?.fetchStatus).toBe('idle')
  expect(reads.filter((read) => read.id === secondApi)).toHaveLength(readsBeforeReturn)
  act(() => useAuthStore.setState({ user, epoch }))
  if (!recoveryError) return
  await waitFor(() =>
    expect(client.getQueryState(apiDefinitionKey(project.id, secondApi))?.status).toBe('error'),
  )
  expect(screen.getByRole('tab', { name: /接口 · 接口B旧名称/ })).toBeVisible()
  act(() => setOrganizationId(otherOrganization))
  act(() => setOrganizationId(null))
}

function assertBoundaryReceipt(
  client: QueryClient,
  historical: ApiDetail | undefined,
  reads: DefinitionRead[],
) {
  expect(client.getMutationCache().getAll().at(-1)?.state.error).toBeInstanceOf(
    SessionBoundaryError,
  )
  expect(client.getQueryState(apiDefinitionKey(project.id, secondApi))?.isInvalidated).toBe(true)
  expect(client.getQueryState(apiDetailKey(project.id, secondApi, 4))?.isInvalidated).toBe(true)
  expect(client.getQueryData<ApiDetail>(apiDetailKey(project.id, secondApi, 4))).toEqual(historical)
  expect(reads.some((read) => read.organization === otherOrganization)).toBe(false)
}

async function expectSettledTab(
  businessError: boolean,
  boundary: boolean,
  recoveryError: boolean,
  reads: DefinitionRead[],
  readsBeforeReturn: number,
) {
  await screen.findByRole('tab', {
    name: businessError ? /接口 · 接口B旧名称/ : /接口 · 接口B权威新名称/,
  })
  if (boundary)
    expect(reads.filter((read) => read.id === secondApi)).toHaveLength(
      readsBeforeReturn + (recoveryError ? 2 : 1),
    )
}

function Workspace() {
  const location = useLocation()
  const selected = new URLSearchParams(location.search).get('focus') ?? apiDefinition.id
  const state = useApiConsole(selected)
  return (
    <>
      <WorkspaceObjectTabs userId={user.id} projectId={project.id} />
      <Link to={apiHref(apiDefinition.id)}>打开接口A</Link>
      <Link to={`${apiHref(secondApi)}&version=4&execution=retained-run`}>打开接口B</Link>
      <button onClick={() => state.setSelectedVersion(4)}>固定版本4</button>
      <button onClick={() => void state.renameApi(secondApi, renamed).catch(() => undefined)}>
        重命名非活跃接口B
      </button>
      <output aria-label="当前接口">
        {state.apiId}:{state.selectedVersion ?? 'latest'}
      </output>
      <APIWorkbench
        detail={state.apiDetail.data}
        editable
        loading={state.apiDetail.isLoading}
        saving={false}
        previewing={false}
        onSave={state.saveVersion}
        onPreview={state.previewRequest}
        onRename={() => undefined}
        draftScope={`${user.id}:${project.id}`}
      />
    </>
  )
}

afterEach(() => {
  localStorage.clear()
  useAuthStore.setState({ user: null, organizationId: null })
  server.events.removeAllListeners('request:start')
  vi.useRealTimers()
})

it.each([
  { scenario: 'success', boundary: false, businessError: false, recoveryError: false },
  { scenario: 'organization boundary', boundary: true, businessError: false, recoveryError: false },
  { scenario: 'failed recovery read', boundary: true, businessError: false, recoveryError: true },
  {
    scenario: 'ordinary business error',
    boundary: false,
    businessError: true,
    recoveryError: false,
  },
])(
  'preserves inactive labels, pinned versions and drafts after $scenario',
  async ({ boundary, businessError, recoveryError }) => {
    authenticateTestUser(user)
    useAuthStore.setState({ organizationId: null })
    const browser = userEvent.setup()
    const patch = heldResponse()
    const oldRead = heldResponse()
    let name = '接口B旧名称'
    let patches = 0
    let applied = false
    let holdNextHistorical = false
    let oldReadStarted = false
    let recoveryFailed = false
    const wrongOrganizationApiReads: string[] = []
    server.events.on('request:start', ({ request }) => {
      if (
        request.method === 'GET' &&
        new URL(request.url).pathname.startsWith(`/api/v1/projects/${project.id}/apis`) &&
        request.headers.get('X-Organization-Id') === otherOrganization
      ) {
        wrongOrganizationApiReads.push(request.url)
      }
    })
    const reads: DefinitionRead[] = []
    async function waitForHistoricalRead(id: string, version: string | null) {
      if (id !== secondApi || version !== '4' || !holdNextHistorical) return
      holdNextHistorical = false
      oldReadStarted = true
      await oldRead.promise
    }
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({
          items: [detail(apiDefinition.id, '接口A').definition, detail(secondApi, name).definition],
          total: 2,
          page: 1,
          page_size: 50,
        }),
      ),
      http.get(`/api/v1/projects/${project.id}/environments`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${project.id}/services`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${project.id}/files`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/executions`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/apis/:id/versions`, () =>
        HttpResponse.json([{ version: 4 }, { version: 1 }]),
      ),
      http.get(`/api/v1/projects/${project.id}/apis/:id`, async ({ request, params }) => {
        const id = String(params.id)
        const version = new URL(request.url).searchParams.get('version')
        reads.push({ id, organization: request.headers.get('X-Organization-Id'), version })
        const snapshot = detail(id, id === secondApi ? name : '接口A', Number(version ?? 4))
        await waitForHistoricalRead(id, version)
        if (id === secondApi && applied && !version && recoveryError && !recoveryFailed) {
          recoveryFailed = true
          return HttpResponse.json(
            {
              error: { code: 'UNAVAILABLE', message: '读取暂不可用', trace_id: 'rename-recovery' },
            },
            { status: 503 },
          )
        }
        return HttpResponse.json(snapshot)
      }),
      http.patch(`/api/v1/projects/${project.id}/apis/${secondApi}`, async ({ request }) => {
        patches += 1
        expect(await request.json()).toEqual({ name: renamed })
        await patch.promise
        if (businessError) {
          return HttpResponse.json(
            { error: { code: 'CONFLICT', message: '接口不能重命名', trace_id: 'rename-failed' } },
            { status: 409 },
          )
        }
        applied = true
        name = renamed
        return HttpResponse.json(detail(secondApi, name).definition)
      }),
    )
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: 15_000 }, mutations: { retry: false } },
    })
    const otherKey = apiDefinitionKey('other-project', secondApi)
    const unrelated = detail(secondApi, '另一个项目的接口B').definition
    client.setQueryData(otherKey, unrelated)
    const router = createMemoryRouter(
      [
        {
          path: '*',
          element: (
            <ProjectProvider>
              <DraftSessionProvider>
                <Workspace />
              </DraftSessionProvider>
            </ProjectProvider>
          ),
        },
      ],
      { initialEntries: [apiHref(apiDefinition.id)] },
    )
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <App>
          <QueryClientProvider client={client}>
            <RouterProvider router={router} />
          </QueryClientProvider>
        </App>
      </ConfigProvider>,
    )
    await screen.findByRole('tab', { name: '接口 · 接口A' })
    fireEvent.change(await screen.findByLabelText('请求路径'), {
      target: { value: '/local-draft-a' },
    })
    await browser.click(screen.getByRole('link', { name: '打开接口B' }))
    await screen.findByRole('tab', { name: '接口 · 接口B旧名称' })
    await browser.click(screen.getByRole('button', { name: '固定版本4' }))
    await waitFor(() =>
      expect(screen.getByLabelText('当前接口')).toHaveTextContent(`${secondApi}:4`),
    )
    fireEvent.change(screen.getByLabelText('请求路径'), { target: { value: '/local-draft-b' } })
    const historicalB = client.getQueryData<ApiDetail>(apiDetailKey(project.id, secondApi, 4))
    await browser.click(screen.getByRole('link', { name: '打开接口A' }))
    await browser.click(screen.getByRole('button', { name: '固定版本4' }))
    await waitFor(() =>
      expect(screen.getByLabelText('当前接口')).toHaveTextContent(`${apiDefinition.id}:4`),
    )
    expect(screen.getByLabelText('请求路径')).toHaveValue('/local-draft-a')
    const draftA = localStorage.getItem(draftKey(apiDefinition.id))
    const draftB = localStorage.getItem(draftKey(secondApi))
    expect(draftA).toContain('/local-draft-a')
    expect(draftB).toContain('/local-draft-b')
    const stableA = client.getQueryData(apiDefinitionKey(project.id, apiDefinition.id))
    holdNextHistorical = true
    let background!: Promise<void>
    act(() => {
      background = client.refetchQueries({
        queryKey: apiDetailKey(project.id, secondApi, 4),
        exact: true,
        type: 'all',
      })
    })
    await waitFor(() => expect(oldReadStarted).toBe(true))
    await browser.click(screen.getByRole('button', { name: '重命名非活跃接口B' }))
    await waitFor(() => expect(patches).toBe(1))
    if (boundary) act(() => setOrganizationId(otherOrganization))
    await act(async () => {
      patch.release()
    })
    await waitFor(() => expect(client.isMutating()).toBe(0))
    expect(applied).toBe(!businessError)
    if (boundary) assertBoundaryReceipt(client, historicalB, reads)
    if (!businessError) {
      expect(client.getQueryState(apiDetailKey(project.id, secondApi, 4))?.fetchStatus).toBe('idle')
    }
    await act(async () => {
      oldRead.release()
      await background
    })
    const readsBeforeReturn = reads.filter((read) => read.id === secondApi).length
    if (boundary) await resumeOriginalScope(client, recoveryError, reads, readsBeforeReturn)
    await expectSettledTab(businessError, boundary, recoveryError, reads, readsBeforeReturn)
    const settledReads = reads.length
    await act(async () => {
      await client.invalidateQueries({
        queryKey: apiDefinitionKey(project.id, secondApi),
        exact: true,
      })
    })
    expect(reads).toHaveLength(settledReads)
    expect(wrongOrganizationApiReads).toEqual([])
    expect(reads.some((read) => read.organization === otherOrganization)).toBe(false)
    expect(patches).toBe(1)
    expect(client.getQueryData(otherKey)).toEqual(unrelated)
    expect(client.getQueryState(otherKey)?.isInvalidated).toBe(false)
    expect(client.getQueryData(apiDefinitionKey(project.id, apiDefinition.id))).toEqual(stableA)
    expect(client.getQueryData(apiDetailKey(project.id, secondApi, 4))).toEqual(historicalB)
    expect(screen.getByLabelText('当前接口')).toHaveTextContent(`${apiDefinition.id}:4`)
    expect(screen.getByLabelText('请求路径')).toHaveValue('/local-draft-a')
    expect(localStorage.getItem(draftKey(apiDefinition.id))).toBe(draftA)
    expect(localStorage.getItem(draftKey(secondApi))).toBe(draftB)
    expect(
      readWorkspaceTabs(user.id, project.id).tabs.find((tab) => tab.objectId === secondApi)?.href,
    ).toContain('version=4&execution=retained-run')
  },
)

it.each([0, 6 * 60_000])(
  'recovers persisted inactive tabs after %s ms away without any original-project read in the other organization',
  async (awayMs) => {
    authenticateTestUser(user)
    useAuthStore.setState({ organizationId: null })
    const response = heldResponse()
    let writes = 0
    let name = '接口B旧名称'
    const wrongScopeReads: string[] = []
    const authoritativeReads: string[] = []
    server.events.on('request:start', ({ request }) => {
      if (
        request.method === 'GET' &&
        new URL(request.url).pathname.startsWith(`/api/v1/projects/${project.id}`) &&
        request.headers.get('X-Organization-Id') === otherOrganization
      )
        wrongScopeReads.push(request.url)
    })
    server.use(
      http.patch(`/api/v1/projects/${project.id}/apis/${secondApi}`, async () => {
        writes += 1
        await response.promise
        name = renamed
        return HttpResponse.json(detail(secondApi, name).definition)
      }),
      http.get(`/api/v1/projects/${project.id}/apis/${secondApi}`, ({ request }) => {
        authoritativeReads.push(request.url)
        return HttpResponse.json(detail(secondApi, name))
      }),
    )
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: 15_000 }, mutations: { retry: false } },
    })
    const emptyPage = { items: [], total: 0, page: 1, page_size: 100 }
    client.setQueryData(['projects'], { ...emptyPage, items: [project], total: 1 })
    client.setQueryData(['project', project.id], project)
    client.setQueryData(['environments', project.id], [])
    client.setQueryData(['apis', project.id, 1, '', null, 'all'], {
      ...emptyPage,
      items: [apiDefinition],
      total: 1,
    })
    client.setQueryData(['api-versions', project.id, apiDefinition.id], [])
    client.setQueryData(
      apiDetailKey(project.id, apiDefinition.id),
      detail(apiDefinition.id, '接口A'),
    )
    client.setQueryData(
      [
        'api-executions',
        JSON.stringify([user.id, useAuthStore.getState().epoch, null]),
        project.id,
        apiDefinition.id,
        1,
      ],
      emptyPage,
    )
    client.setQueryData(['artifacts', project.id], emptyPage)
    client.setQueryData(['project-redaction-policy', project.id], {
      mode: 'off',
      source: 'installation',
      policy_version: 1,
    })
    client.setQueryData(['request-services', project.id], [])
    client.setQueryData(apiDefinitionKey(project.id, secondApi), detail(secondApi, name).definition)
    writeWorkspaceTabs(user.id, project.id, [
      routeWorkspaceTab(project.id, apiHref(apiDefinition.id))!,
      routeWorkspaceTab(project.id, `${apiHref(secondApi)}&version=4`)!,
    ])
    const wrapper = ({ children }: { children: ReactNode }) => (
      <App>
        <QueryClientProvider client={client}>
          <ProjectTestProvider section="apis" initialEntry={apiHref(apiDefinition.id)}>
            {children}
          </ProjectTestProvider>
        </QueryClientProvider>
      </App>
    )
    const hook = renderHook(() => useApiConsole(apiDefinition.id), { wrapper })
    await waitFor(() => expect(hook.result.current.canEdit).toBe(true))
    let command!: Promise<unknown>
    act(() => {
      command = hook.result.current.renameApi(secondApi, renamed).catch((error: unknown) => error)
    })
    await waitFor(() => expect(writes).toBe(1))
    hook.unmount()
    act(() => setOrganizationId(otherOrganization))
    if (awayMs) vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    await act(async () => {
      response.release()
      expect(await command).toBeInstanceOf(SessionBoundaryError)
    })
    if (awayMs) {
      await vi.advanceTimersByTimeAsync(awayMs)
      vi.useRealTimers()
    }
    render(
      <App>
        <QueryClientProvider client={client}>
          <MemoryRouter initialEntries={[apiHref(apiDefinition.id)]}>
            <DraftSessionProvider>
              <WorkspaceObjectTabs userId={user.id} projectId={project.id} />
            </DraftSessionProvider>
          </MemoryRouter>
        </QueryClientProvider>
      </App>,
    )
    expect(client.isFetching()).toBe(0)
    expect(authoritativeReads).toEqual([])
    expect(wrongScopeReads).toEqual([])
    act(() => setOrganizationId(null))
    await screen.findByRole('tab', { name: '接口 · 接口B权威新名称' })
    expect(authoritativeReads).toHaveLength(1)
    expect(wrongScopeReads).toEqual([])
    expect(writes).toBe(1)
    expect(screen.getByRole('tab', { selected: true })).toHaveTextContent('接口 · 接口A')
    expect(
      readWorkspaceTabs(user.id, project.id).tabs.find((tab) => tab.objectId === secondApi)?.href,
    ).toContain('version=4')
  },
)
