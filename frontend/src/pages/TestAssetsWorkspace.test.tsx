import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

function mockWorkspace(viewer = false) {
  const records = [
    baseCase,
    { ...baseCase, id: 'case-unfiled', folder_id: null, name: '未分类用例' },
    ...Array.from({ length: 98 }, (_, index) => ({
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
      const page = Number(new URL(request.url).searchParams.get('page'))
      pages(page)
      return HttpResponse.json({
        items: records.slice((page - 1) * 100, page * 100),
        total: records.length,
        page,
        page_size: 100,
      })
    }),
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
    http.get(root + '/test-plan-runs', () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
    ),
    http.post(root + '/*', () => {
      writes()
      return HttpResponse.json({}, { status: 409 })
    }),
  )
  return { pages, writes }
}

function renderWorkspace(initialEntry?: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <ConfigProvider theme={createIceTheme(true)}>
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <ProjectTestProvider section="assets" initialEntry={initialEntry}>
            <TestAssetsPage />
          </ProjectTestProvider>
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
}

it('browses every asset page without moving records and clears selection outside the new directory', async () => {
  const { pages, writes } = mockWorkspace()
  renderWorkspace('/projects/' + project.id + '/assets?folder=unfiled')
  const unfiled = (await screen.findByText('未分类用例')).closest('tr')!
  const toolbar = within(screen.getByText('仅选择当前页').closest<HTMLElement>('.asset-toolbar')!)
  expect(screen.getByText('筛选命中 101 个用例、0 个套件。')).toBeVisible()
  expect(pages).toHaveBeenCalledWith(2)
  fireEvent.click(within(unfiled).getByRole('checkbox'))
  expect(toolbar.getByRole('button', { name: /批量移动 \(1\)/ })).toBeEnabled()
  fireEvent.click(
    within(screen.getByRole('navigation', { name: '浏览测试资产目录' })).getByRole('button', {
      name: /核心回归/,
    }),
  )
  expect(screen.queryByText('未分类用例')).not.toBeInTheDocument()
  expect(screen.getByText('目录用例')).toBeVisible()
  expect(screen.getByText('跨页用例')).toBeVisible()
  expect(toolbar.getByRole('button', { name: /批量移动 \(0\)/ })).toBeDisabled()
  expect(
    toolbar.getByRole('combobox', { name: '测试用例批量目录' }).closest('.ant-select'),
  ).toHaveTextContent('移动到目录')
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
    http.get(root + '/test-plan-runs', () =>
      HttpResponse.json({ items: [run], total: 81, page: 1, page_size: 20 }),
    ),
    http.get(root + '/test-plan-runs/' + run.id, () =>
      HttpResponse.json({
        run,
        items: [
          {
            id: 'run-item-1',
            target_type: 'case',
            target_id: baseCase.id,
            target_version: 1,
            target_snapshot: { target_type: 'case', target_id: baseCase.id, target_version: 1 },
            workflow_id: workflow.id,
            workflow_version: 1,
            environment_id: environment.id,
            status: 'failed',
            workflow_execution_id: 'execution-case-1',
            position: 0,
            max_retries: 0,
            attempts: 1,
            error_message: null,
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
  expect(within(drawer).getByText(/最近 1 次计划运行 \/ 全部 81 次/)).toBeVisible()
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
