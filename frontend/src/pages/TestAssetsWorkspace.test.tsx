import userEvent from '@testing-library/user-event'
import { useLocation, useNavigate, type NavigateFunction } from 'react-router-dom'
import { useEffect } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { App as AntdApp, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { useAuthStore } from '../features/auth/auth-store'
import type { Folder, TestCase, TestPlanRun } from '../lib/api'
import { environment, project, user, workflow } from '../test/fixtures'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { server } from '../test/server'
import { authenticateTestUser } from '../test/auth'
import { createIceTheme } from '../theme/ice-theme'
import TestAssetsPage from './TestAssetsPage'

const root = '/api/v1/projects/' + project.id
const folder: Folder = {
  id: 'folder-ui',
  project_id: project.id,
  parent_id: null,
  name: '核心回归',
  created_by_id: user.id,
  created_at: workflow.created_at,
  updated_at: workflow.updated_at,
}
const baseCase: TestCase = {
  id: 'case-in-folder',
  project_id: project.id,
  folder_id: folder.id,
  name: '目录用例',
  description: '',
  tags: [],
  is_template: false,
  current_version: 2,
  created_by_id: user.id,
  created_at: workflow.created_at,
  updated_at: workflow.updated_at,
  draft_definition: {
    workflow_id: workflow.id,
    workflow_version: 2,
    environment_id: environment.id,
    runtime_variables: { revision: 'draft' },
    runtime_headers: {},
  },
}
const laterCase = { ...baseCase, id: 'case-later-page', name: '跨页用例' }

beforeEach(() => authenticateTestUser(user))
afterEach(() => useAuthStore.setState({ user: null }))

function mockWorkspace(viewer = false, otherCaseCount: number = 98) {
  const records = [
    baseCase,
    { ...baseCase, id: 'case-unfiled', folder_id: null, name: '未分类用例' },
    ...Array.from({ length: otherCaseCount }, (_, index) => ({
      ...baseCase,
      id: 'case-other-' + index,
      folder_id: 'folder-other',
      name: '其他用例 ' + index,
      current_version: null,
    })),
    laterCase,
  ]
  const pages = vi.fn()
  const writes = vi.fn()
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
    ),
    http.get(root + '/folders', () =>
      HttpResponse.json([folder, { ...folder, id: 'folder-other', name: '其他回归' }]),
    ),
    http.get(root + '/permissions', () =>
      HttpResponse.json({
        effective_role: viewer ? 'viewer' : 'owner',
        capabilities: viewer ? ['read'] : ['read', 'edit', 'execute'],
        matrix: {},
      }),
    ),
    http.get(root + '/environments', () => HttpResponse.json([environment])),
    http.get(root + '/workflows', () =>
      HttpResponse.json({ items: [workflow], total: 1, page: 1, page_size: 100 }),
    ),
    http.get(root + '/test-cases', ({ request }) => {
      const params = new URL(request.url).searchParams
      const page = Number(params.get('page'))
      const size = Number(params.get('page_size'))
      const folderId = params.get('folder_id')
      const items = params.get('unfiled')
        ? records.filter((item) => item.folder_id === null)
        : folderId
          ? records.filter((item) => item.folder_id === folderId)
          : records
      pages(page, size, folderId)
      return HttpResponse.json({
        items: items.slice((page - 1) * size, page * size),
        total: items.length,
        page,
        page_size: size,
      })
    }),
    http.get(root + '/test-assets/directory-counts', () =>
      HttpResponse.json({
        case_total: records.length,
        suite_total: 0,
        published_case_total: 3,
        unfiled_cases: 1,
        unfiled_suites: 0,
        folders: [
          { folder_id: folder.id, cases: 2, suites: 0 },
          { folder_id: 'folder-other', cases: otherCaseCount, suites: 0 },
        ],
      }),
    ),
    http.get(root + '/test-suites', () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
    ),
    http.get(root + '/test-cases/runs/latest', () => HttpResponse.json([])),
    http.get(root + '/test-cases/:id/versions', ({ params }) =>
      HttpResponse.json(
        [2, 1].map((version) => ({
          id: 'version-' + version,
          test_case_id: params.id,
          version,
          definition: {
            ...baseCase.draft_definition,
            workflow_version: version,
            runtime_variables: { revision: 'published-' + version },
          },
          fingerprint: 'fingerprint-' + version,
          change_note: '',
          created_by_id: user.id,
          created_at: workflow.created_at,
        })),
      ),
    ),
    http.get(root + '/test-cases/:id', ({ params }) =>
      HttpResponse.json(records.find((item) => item.id === params.id)),
    ),
    http.get(root + '/test-plans', () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
    ),
    http.get(root + '/test-suites/runs/latest', () => HttpResponse.json([])),
    http.get(root + '/test-cases/:id/runs', () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
    ),
    http.post(root + '/*', () => {
      writes()
      return HttpResponse.json({}, { status: 409 })
    }),
  )
  return { pages, writes }
}

function renderWorkspace(initialEntry?: string, onNavigate?: (navigate: NavigateFunction) => void) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <ConfigProvider theme={createIceTheme(true)}>
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <ProjectTestProvider section="assets" initialEntry={initialEntry}>
            <TestAssetsPage />
            <AssetLocation onNavigate={onNavigate} />
          </ProjectTestProvider>
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
  return queryClient
}

it('loads the selected server directory page and uses aggregate counts without preloading every asset', async () => {
  const { pages, writes } = mockWorkspace()
  renderWorkspace('/projects/' + project.id + '/assets?folder=' + folder.id)
  expect((await screen.findByText('跨页用例')).closest('tr')).toBeVisible()
  expect(screen.getByText('目录用例').closest('tr')).toBeVisible()
  expect(screen.getByText('当前目录匹配 2 个用例、0 个套件。')).toBeVisible()
  expect(screen.queryByText('未分类用例')).not.toBeInTheDocument()
  expect(pages).toHaveBeenCalledExactlyOnceWith(1, 20, folder.id)
  const directory = within(screen.getByLabelText('浏览测试资产目录'))
  expect(directory.getByText('全部测试资产').closest('.ant-tree-treenode')).toHaveTextContent('101')
  expect(directory.getByText('核心回归').closest('.ant-tree-treenode')).toHaveTextContent('2')
  expect(writes).not.toHaveBeenCalled()
})

it('clears selection outside the new directory without moving records', async () => {
  const { writes } = mockWorkspace(false, 0)
  renderWorkspace('/projects/' + project.id + '/assets?folder=unfiled')
  const unfiled = (await screen.findByText('未分类用例')).closest('tr')!
  const toolbar = within(screen.getByText('仅选择当前页').closest<HTMLElement>('.asset-toolbar')!)
  fireEvent.click(unfiled.querySelector<HTMLInputElement>('input[type="checkbox"]')!)
  expect(toolbar.getByText(/批量移动 \(1\)/).closest('button')).toBeEnabled()
  fireEvent.click(within(screen.getByLabelText('浏览测试资产目录')).getByText('核心回归'))
  expect((await screen.findByText('目录用例')).closest('tr')).toBeVisible()
  expect(screen.queryByText('未分类用例')).not.toBeInTheDocument()
  expect(screen.getByText('跨页用例').closest('tr')).toBeVisible()
  expect(toolbar.getByText(/批量移动 \(0\)/).closest('button')).toBeDisabled()
  expect(toolbar.getByLabelText('测试用例批量目录').closest('.ant-select')).toHaveTextContent(
    '移动到目录',
  )
  expect(writes).not.toHaveBeenCalled()
})

it('clears batch selection when changing table pages', async () => {
  const { writes } = mockWorkspace()
  renderWorkspace()
  const row = (await screen.findByText('目录用例')).closest('tr')!
  const toolbar = within(screen.getByText('仅选择当前页').closest<HTMLElement>('.asset-toolbar')!)
  fireEvent.click(within(row).getByRole('checkbox'))
  expect(toolbar.getByRole('button', { name: /加入计划 \(1\)/ })).toBeEnabled()
  fireEvent.click(screen.getByTitle('2'))
  await waitFor(() =>
    expect(toolbar.getByRole('button', { name: /加入计划 \(0\)/ })).toBeDisabled(),
  )
  expect(screen.queryByText('目录用例')).not.toBeInTheDocument()
  expect(writes).not.toHaveBeenCalled()
})

it('opens a deep-linked older published version beyond the first server page without executing it', async () => {
  const { writes } = mockWorkspace()
  renderWorkspace(
    '/projects/' + project.id + '/assets?type=case&focus=' + laterCase.id + '&version=1',
  )
  const drawer = await screen.findByRole('dialog', { name: '测试资产详情' })
  await within(drawer).findByText('正在查看不可变的发布版本 v1。')
  expect(await within(drawer).findByText('published-1')).toBeVisible()
  expect(within(drawer).queryByText('draft')).not.toBeInTheDocument()
  await waitFor(() => expect(within(drawer).getByRole('button', { name: '执行' })).toBeEnabled())
  expect(writes).not.toHaveBeenCalled()
})

it('keeps a missing published version visible and blocks plan and execution actions', async () => {
  mockWorkspace()
  renderWorkspace(
    '/projects/' + project.id + '/assets?type=case&focus=' + baseCase.id + '&version=99',
  )
  const drawer = await screen.findByRole('dialog', { name: '测试资产详情' })
  await within(drawer).findByText('指定发布版本不存在，未切换到其他版本')
  expect(within(drawer).getByRole('button', { name: '加入计划' })).toBeDisabled()
  expect(within(drawer).getByRole('button', { name: '执行' })).toBeDisabled()
})

it('uses project capabilities for view-only asset access', async () => {
  const { writes } = mockWorkspace(true)
  renderWorkspace('/projects/' + project.id + '/assets?type=case&focus=' + baseCase.id)
  const drawer = await screen.findByRole('dialog', { name: '测试资产详情' })
  await within(drawer).findByText('published-2')
  expect(within(drawer).getByRole('button', { name: '编辑当前草稿' })).toBeDisabled()
  expect(within(drawer).getByRole('button', { name: '加入计划' })).toBeDisabled()
  expect(within(drawer).getByRole('button', { name: '执行' })).toBeDisabled()
  expect(writes).not.toHaveBeenCalled()
})

it('closes asset edit and execution actions after a failed permission refresh with owner cache', async () => {
  const { writes } = mockWorkspace(false, 0)
  const queryClient = renderWorkspace(
    root.replace('/api/v1', '') + '/assets?type=case&focus=' + baseCase.id,
  )
  const drawer = await screen.findByRole('dialog', { name: '测试资产详情' })
  await within(drawer).findByText('published-2')
  await waitFor(() =>
    expect(within(drawer).getByRole('button', { name: '编辑当前草稿' })).toBeEnabled(),
  )
  server.use(
    http.get(root + '/permissions', () =>
      HttpResponse.json(
        { error: { code: 'UNAVAILABLE', message: '权限重读失败', trace_id: 'asset-permission' } },
        { status: 503 },
      ),
    ),
  )
  await act(async () => {
    await queryClient.invalidateQueries({ queryKey: ['project-permission', project.id] })
  })
  await waitFor(() =>
    expect(within(drawer).getByRole('button', { name: '编辑当前草稿' })).toBeDisabled(),
  )
  expect(within(drawer).getByRole('button', { name: '执行' })).toBeDisabled()
  expect(writes).not.toHaveBeenCalled()
})

it('links only matching case-run evidence to the report and frozen workflow', async () => {
  mockWorkspace()
  const run = {
    id: 'plan-run-1',
    project_id: project.id,
    test_plan_id: 'plan-1',
    status: 'failed',
    created_at: workflow.created_at,
  } as TestPlanRun
  server.use(
    http.get(root + '/test-cases/' + baseCase.id + '/runs', () =>
      HttpResponse.json({
        total: 81,
        page: 1,
        page_size: 20,
        items: [
          {
            id: 'run-item-1',
            case_version: 1,
            source: 'plan',
            started_at: run.created_at,
            created_at: run.created_at,
            plan_run_id: run.id,
            plan_id: run.test_plan_id,
            workflow_id: workflow.id,
            workflow_version: 1,
            environment_id: environment.id,
            status: 'failed',
            execution_id: 'execution-case-1',
          },
        ],
      }),
    ),
  )
  renderWorkspace('/projects/' + project.id + '/assets?type=case&focus=' + baseCase.id)
  const drawer = await screen.findByRole('dialog', { name: '测试资产详情' })
  fireEvent.click(await within(drawer).findByRole('tab', { name: '执行与报告' }))
  const report = await within(drawer).findByRole('link', { name: '报告' })
  expect(report).toHaveAttribute(
    'href',
    '/projects/' + project.id + '/reports?execution=execution-case-1',
  )
  expect(within(drawer).getByRole('link', { name: '编排回看' })).toHaveAttribute(
    'href',
    '/projects/' + project.id + '/workflows?focus=' + workflow.id + '&execution=execution-case-1',
  )
  expect(within(drawer).getByText(/当前页 1 条 · 当前筛选共 81 条/)).toBeVisible()
})

it('runs the selected older case version directly without creating a plan', async () => {
  const { writes } = mockWorkspace()
  const submitted = vi.fn()
  server.use(
    http.post(root + '/test-cases/:id/runs', async ({ request }) => {
      submitted(await request.json())
      return HttpResponse.json(
        {
          case_id: laterCase.id,
          case_version: 1,
          workflow_id: workflow.id,
          workflow_version: 1,
          execution_id: 'execution-direct',
          source: 'direct',
          status: 'queued',
        },
        { status: 202 },
      )
    }),
  )
  renderWorkspace(
    '/projects/' + project.id + '/assets?type=case&focus=' + laterCase.id + '&version=1',
  )
  const drawer = await screen.findByRole('dialog', { name: '测试资产详情' })
  const execute = await within(drawer).findByRole('button', { name: /^执行$/ })
  await waitFor(() => expect(execute).toBeEnabled())
  fireEvent.click(execute)
  // Ant Design uses one test ID for modal titles; scope by the visible title.
  const confirmation = (await screen.findByText('运行测试用例：跨页用例')).closest<HTMLElement>(
    '[role=dialog]',
  )!
  const run = within(confirmation).getByRole('button', { name: '运行已发布版本' })
  await waitFor(() => expect(run).toBeEnabled())
  fireEvent.click(run)
  await screen.findByText('运行已提交')
  expect(submitted).toHaveBeenCalledWith({ source: 'published', version: 1 })
  expect(writes).not.toHaveBeenCalled()
})

it('keeps the new project run dialog intact when the previous project receipt arrives late', async () => {
  mockWorkspace(false, 0)
  const nextProject = { ...project, id: '00000000-0000-4000-8000-000000000019', name: '新项目' }
  const nextWorkflow = { ...workflow, project_id: nextProject.id, id: 'next-workflow' }
  const nextEnvironment = { ...environment, project_id: nextProject.id, id: 'next-environment' }
  const nextCase = {
    ...baseCase,
    id: 'next-case',
    project_id: nextProject.id,
    name: '新项目用例',
    folder_id: null,
    draft_definition: {
      ...baseCase.draft_definition,
      workflow_id: nextWorkflow.id,
      environment_id: nextEnvironment.id,
    },
  }
  const nextRoot = `/api/v1/projects/${nextProject.id}`
  let release!: () => void
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({
        items: [project, nextProject],
        total: 2,
        page: 1,
        page_size: 100,
      }),
    ),
    http.get(nextRoot, () => HttpResponse.json(nextProject)),
    http.get(`${nextRoot}/*`, ({ request }) => {
      const resource = new URL(request.url).pathname.slice(nextRoot.length)
      if (resource === '/permissions')
        return HttpResponse.json({
          effective_role: 'owner',
          capabilities: ['read', 'edit', 'execute'],
          matrix: {},
        })
      if (resource === '/environments') return HttpResponse.json([nextEnvironment])
      if (resource === '/workflows')
        return HttpResponse.json({ items: [nextWorkflow], total: 1, page: 1, page_size: 100 })
      if (resource === '/test-cases')
        return HttpResponse.json({ items: [nextCase], total: 1, page: 1, page_size: 20 })
      if (resource === '/test-suites')
        return HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 })
      if (resource.endsWith('/versions'))
        return HttpResponse.json([
          {
            id: 'next-version',
            test_case_id: nextCase.id,
            version: 2,
            definition: nextCase.draft_definition,
            fingerprint: 'b'.repeat(64),
            change_note: '',
            created_by_id: user.id,
            created_at: workflow.created_at,
          },
        ])
      if (resource === '/test-assets/directory-counts')
        return HttpResponse.json({
          case_total: 1,
          suite_total: 0,
          published_case_total: 1,
          unfiled_cases: 1,
          unfiled_suites: 0,
          folders: [],
        })
      return HttpResponse.json([])
    }),
    http.post(`${root}/test-cases/${baseCase.id}/runs`, async () => {
      await new Promise<void>((resolve) => {
        release = resolve
      })
      return HttpResponse.json(
        {
          case_id: baseCase.id,
          case_version: 2,
          workflow_id: workflow.id,
          workflow_version: 2,
          execution_id: 'old-project-execution',
          source: 'direct',
          status: 'queued',
          environment_id: environment.id,
          started_at: workflow.created_at,
          created_new_version: false,
        },
        { status: 202 },
      )
    }),
  )
  let navigate: NavigateFunction | undefined
  const client = renderWorkspace(undefined, (value) => {
    navigate = value
  })
  const firstRow = (await screen.findByText(baseCase.name)).closest('tr')!
  const firstRun = within(firstRow).getByText('运行').closest('button')!
  expect(firstRun).toHaveRole('button')
  await waitFor(() => expect(firstRun).toBeEnabled())
  fireEvent.click(firstRun)
  const firstDialog = (
    await screen.findByText(`运行测试用例：${baseCase.name}`)
  ).closest<HTMLElement>('[role=dialog]')!
  fireEvent.click(within(firstDialog).getByLabelText('运行已发布用例版本'))
  const submit = within(firstDialog).getByRole('button', { name: '运行已发布版本' })
  await waitFor(() => expect(submit).toBeEnabled())
  fireEvent.click(submit)
  await waitFor(() => expect(release).toBeDefined())
  try {
    expect(navigate).toBeDefined()
    await act(async () => {
      await navigate!(`/projects/${nextProject.id}/assets`)
    })
    const nextRow = (await screen.findByText(nextCase.name)).closest('tr')!
    const nextRun = within(nextRow).getByText('运行').closest('button')!
    expect(nextRun).toHaveRole('button')
    await waitFor(() => expect(nextRun).toBeEnabled())
    fireEvent.click(nextRun)
    const nextDialog = (
      await screen.findByText(`运行测试用例：${nextCase.name}`)
    ).closest<HTMLElement>('[role=dialog]')!
    await act(async () => release())
    await waitFor(() => expect(client.isMutating()).toBe(0))
    expect(nextDialog).toBeInTheDocument()
    expect(screen.queryByText('运行已提交')).not.toBeInTheDocument()
    expect(screen.getByTestId('asset-location')).toHaveAttribute(
      'data-pathname',
      `/projects/${nextProject.id}/assets`,
    )
  } finally {
    await act(async () => release())
  }
})

it('adds the selected fixed case version to an existing plan without executing it', async () => {
  const { writes } = mockWorkspace()
  const submitted = vi.fn()
  server.use(
    http.get(root + '/test-plans', () =>
      HttpResponse.json({
        items: [{ id: 'plan-existing', name: '已有回归计划', items: [] }],
        total: 1,
        page: 1,
        page_size: 20,
      }),
    ),
    http.post(root + '/test-plans/plan-existing/items', async ({ request }) => {
      submitted(await request.json())
      return new HttpResponse(null, { status: 204 })
    }),
  )
  renderWorkspace(
    '/projects/' + project.id + '/assets?type=case&focus=' + laterCase.id + '&version=1',
  )
  const drawer = await screen.findByRole('dialog', { name: '测试资产详情' })
  const join = await within(drawer).findByRole('button', { name: /加入计划/ })
  await waitFor(() => expect(join).toBeEnabled())
  fireEvent.click(join)
  const confirmation = (await screen.findByText('加入测试计划')).closest<HTMLElement>(
    '[role=dialog]',
  )!
  fireEvent.mouseDown(within(confirmation).getByRole('combobox', { name: '选择测试计划' }))
  fireEvent.click(
    await screen.findByText('已有回归计划', { selector: '.ant-select-item-option-content' }),
  )
  const confirm = within(confirmation).getByRole('button', { name: /确\s*定|OK/ })
  await waitFor(() => expect(confirm).toBeEnabled())
  fireEvent.click(confirm)
  await waitFor(() =>
    expect(submitted).toHaveBeenCalledWith({
      target_type: 'case',
      target_id: laterCase.id,
      target_version: 1,
    }),
  )
  expect(writes).not.toHaveBeenCalled()
})

function AssetLocation({ onNavigate }: { onNavigate?: (navigate: NavigateFunction) => void }) {
  const location = useLocation()
  const navigate = useNavigate()
  useEffect(() => {
    onNavigate?.(navigate)
  }, [navigate, onNavigate])
  return (
    <span hidden data-testid="asset-location" data-pathname={location.pathname}>
      {location.search}
    </span>
  )
}

it('shares task scope across server pages and folder counts and retains it in frozen-version links', async () => {
  mockWorkspace(false, 0)
  const requests: { resource: string; params: Record<string, string> }[] = []
  const latest = {
    status: 'failed',
    occurred_at: '2026-09-01T00:00:00Z',
    execution_id: 'old-execution',
    plan_id: null,
    plan_run_id: null,
    asset_version: 1,
    source: 'direct',
  }
  for (const resource of ['test-cases', 'test-suites', 'test-assets/directory-counts'])
    server.use(
      http.get(root + '/' + resource, ({ request }) => {
        const params = Object.fromEntries(new URL(request.url).searchParams)
        requests.push({ resource, params })
        if (resource === 'test-assets/directory-counts')
          return HttpResponse.json({
            case_total: 61,
            suite_total: 21,
            published_case_total: 61,
            unfiled_cases: 0,
            unfiled_suites: 0,
            folders: [{ folder_id: folder.id, cases: 61, suites: 21 }],
          })
        return HttpResponse.json({
          items: resource === 'test-cases' ? [{ ...baseCase, latest_run: latest }] : [],
          total: resource === 'test-cases' ? 61 : 21,
          page: Number(params.page),
          page_size: 20,
        })
      }),
    )
  server.use(
    http.get(root + '/test-assets/environment-options', () =>
      HttpResponse.json({
        items: [{ id: environment.id, name: environment.name }],
        total: 1,
        page: 1,
        page_size: 20,
      }),
    ),
  )
  renderWorkspace(
    `/projects/${project.id}/assets?folder=${folder.id}&assetPublication=published&assetResult=failed&assetEnvironment=${environment.id}&assetOrder=latest_run_desc&casePage=3&suitePage=2`,
  )
  expect(await screen.findByText('当前目录匹配 61 个用例、21 个套件。')).toBeVisible()
  await waitFor(() => expect(requests).toHaveLength(3))
  requests.forEach(({ params }) =>
    expect(params).toEqual(
      expect.objectContaining({
        publication: 'published',
        latest_result: 'failed',
        environment_id: environment.id,
        order: 'latest_run_desc',
      }),
    ),
  )
  expect(requests.find((item) => item.resource === 'test-cases')?.params.page).toBe('3')
  expect(requests.find((item) => item.resource === 'test-suites')?.params.page).toBe('2')
  const row = screen.getByText('目录用例').closest('tr')!
  const frozenVersion = within(row).getByRole('link', { name: '用例 v1' })
  expect(frozenVersion.getAttribute('href')).toContain('assetResult=failed')
  expect(frozenVersion.getAttribute('href')).toContain('version=1')
  fireEvent.click(frozenVersion)
  expect(await screen.findByText('正在查看不可变的发布版本 v1。')).toBeVisible()
  expect(screen.getByTestId('asset-location').textContent).toContain('casePage=3')
})

it('clears batch selection when the task filter changes or selected records disappear on refresh', async () => {
  const { writes } = mockWorkspace(false, 0)
  let refreshed = false
  server.use(
    http.get(root + '/test-cases', ({ request }) => {
      const params = new URL(request.url).searchParams
      const filtered = params.get('latest_result') === 'failed'
      return HttpResponse.json({
        items: filtered || refreshed ? [laterCase] : [baseCase, laterCase],
        total: filtered || refreshed ? 1 : 2,
        page: 1,
        page_size: 20,
      })
    }),
  )
  const client = renderWorkspace()
  const row = (await screen.findByText('目录用例')).closest('tr')!
  const toolbar = within(screen.getByText('仅选择当前页').closest<HTMLElement>('.asset-toolbar')!)
  fireEvent.click(within(row).getByRole('checkbox'))
  expect(toolbar.getByRole('button', { name: /批量移动 \(1\)/ })).toBeEnabled()
  refreshed = true
  await client.invalidateQueries({ queryKey: ['test-cases', project.id] })
  await waitFor(() => expect(screen.queryByText('目录用例')).not.toBeInTheDocument())
  expect(toolbar.getByRole('button', { name: /批量移动 \(0\)/ })).toBeDisabled()
  fireEvent.click(within(screen.getByText('跨页用例').closest('tr')!).getByRole('checkbox'))
  expect(toolbar.getByRole('button', { name: /批量移动 \(1\)/ })).toBeEnabled()
  await userEvent.click(screen.getByRole('combobox', { name: '资产最近结果' }))
  await userEvent.click(screen.getByText('失败', { selector: '.ant-select-item-option-content' }))
  await waitFor(() =>
    expect(screen.getByTestId('asset-location').textContent).toContain('assetResult=failed'),
  )
  expect(toolbar.getByRole('button', { name: /批量移动 \(0\)/ })).toBeDisabled()
  expect(writes).not.toHaveBeenCalled()
})

it('rejects invalid task scope without querying a broader catalog and recovers through reset', async () => {
  const { pages } = mockWorkspace(false, 0)
  renderWorkspace(`/projects/${project.id}/assets?assetResult=unknown`)
  expect(await screen.findByText('URL 中的最近结果无效')).toBeVisible()
  expect(pages).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '重置筛选' }))
  expect(await screen.findByText('目录用例')).toBeVisible()
  expect(pages).toHaveBeenCalled()
})
