import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { App as AntdApp } from 'antd'
import { delay, http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useAuthStore } from '../auth/auth-store'
import { authenticateTestUser } from '../../test/auth'
import { project, user, workflow } from '../../test/fixtures'
import { server } from '../../test/server'
import AssetRunEvidence from './AssetRunEvidence'
import type { AssetRunDetail, AssetRunItem, CaseRunHistory } from './asset-workspace-service'

const root = `/api/v1/projects/${project.id}`
const caseRun: CaseRunHistory = {
  id: 'direct-run',
  execution_id: 'direct-run',
  case_version: 2,
  workflow_id: workflow.id,
  workflow_version: 1,
  environment_id: 'env-1',
  status: 'passed',
  source: 'direct',
  started_at: workflow.created_at,
  created_at: workflow.created_at,
  plan_run_id: null,
  plan_id: null,
}
const suiteItem: AssetRunItem = {
  id: 'suite-item',
  target_type: 'case',
  target_id: 'case-1',
  target_version: 1,
  target_snapshot: {
    target_type: 'case',
    target_id: 'case-1',
    target_version: 1,
    source_suite: { id: 'suite-1', version: 1 },
  },
  workflow_id: workflow.id,
  workflow_version: 1,
  environment_id: 'env-1',
  status: 'failed',
  workflow_execution_id: 'old-suite-execution',
  position: 0,
  max_retries: 1,
  attempts: 2,
  error_message: null,
}

beforeEach(() => authenticateTestUser(user))
afterEach(() => useAuthStore.setState({ user: null }))

function renderHistory(props: Partial<Parameters<typeof AssetRunEvidence>[0]> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <AssetRunEvidence
            projectId={project.id}
            kind="case"
            id="case-1"
            cases={[]}
            versions={[2, 1]}
            {...props}
          />
        </MemoryRouter>
      </QueryClientProvider>
    </AntdApp>,
  )
}

it('pages all case history and resets the page when filtering a frozen case version', async () => {
  const reads = vi.fn()
  server.use(
    http.get(root + '/test-cases/case-1/runs', ({ request }) => {
      const params = new URL(request.url).searchParams
      const page = Number(params.get('page'))
      const version = params.get('version')
      reads(page, version)
      return HttpResponse.json({
        items: [
          page === 1
            ? caseRun
            : {
                ...caseRun,
                id: 'old-run',
                execution_id: 'old-run',
                source: 'plan',
                case_version: 1,
                status: 'failed',
                plan_id: 'plan-1',
                plan_run_id: 'plan-run-1',
              },
        ],
        total: version ? 21 : 43,
        page,
        page_size: 20,
      })
    }),
  )
  renderHistory()
  expect(await screen.findByText(/当前筛选共 43 条/)).toBeVisible()
  expect(screen.getByRole('link', { name: '报告' })).toHaveAttribute(
    'href',
    `/projects/${project.id}/reports?execution=direct-run`,
  )
  fireEvent.click(screen.getByTitle('2'))
  await waitFor(() => expect(reads).toHaveBeenCalledWith(2, null))
  expect(await screen.findByText('测试计划')).toBeVisible()
  expect(screen.getByRole('link', { name: '编排回看' })).toHaveAttribute(
    'href',
    `/projects/${project.id}/workflows?focus=${workflow.id}&execution=old-run`,
  )
  fireEvent.mouseDown(screen.getByRole('combobox', { name: '历史资产版本' }))
  fireEvent.click(
    await screen.findByText('已发布 v1', { selector: '.ant-select-item-option-content' }),
  )
  await waitFor(() => expect(reads).toHaveBeenCalledWith(1, '1'))
  expect(await screen.findByText(/当前筛选共 21 条/)).toBeVisible()
})

it('preserves queued plan entries with no fabricated execution or report link', async () => {
  server.use(
    http.get(root + '/test-cases/case-1/runs', () =>
      HttpResponse.json({
        items: [
          {
            ...caseRun,
            id: 'queued-item',
            execution_id: null,
            status: 'queued',
            source: 'plan',
            started_at: null,
            plan_id: 'plan-queued',
            plan_run_id: 'plan-run-queued',
          },
        ],
        total: 1,
        page: 1,
        page_size: 20,
      }),
    ),
  )
  renderHistory({ version: 1 })
  expect(await screen.findByText('排队中')).toBeVisible()
  expect(screen.getByText('尚无流程报告')).toBeVisible()
  expect(screen.queryByRole('link', { name: '报告' })).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: '查看计划' })).toHaveAttribute(
    'href',
    `/projects/${project.id}/tasks?focus=plan-queued`,
  )
})

it('opens older suite evidence using only its frozen membership and server history page', async () => {
  const reads = vi.fn()
  const detail = {
    run: {
      id: 'old-suite-run',
      test_plan_id: 'plan-suite',
      created_at: workflow.created_at,
      status: 'failed',
    },
    items: [
      suiteItem,
      {
        ...suiteItem,
        id: 'other-suite',
        target_id: 'case-unrelated',
        workflow_execution_id: 'unrelated-execution',
        target_snapshot: {
          ...suiteItem.target_snapshot,
          source_suite: { id: 'suite-other', version: 3 },
        },
      },
    ],
  } as AssetRunDetail
  server.use(
    http.get(root + '/test-suites/suite-1/runs', ({ request }) => {
      reads(new URL(request.url).searchParams.get('page'))
      return HttpResponse.json({ items: [detail], total: 69, page: 1, page_size: 20 })
    }),
  )
  renderHistory({ kind: 'suite', id: 'suite-1' })
  expect(await screen.findByText(/当前筛选共 69 条/)).toBeVisible()
  expect(screen.getByRole('link', { name: '报告' })).toHaveAttribute(
    'href',
    `/projects/${project.id}/reports?execution=old-suite-execution`,
  )
  expect(screen.queryByText('case-unrelated')).not.toBeInTheDocument()
  fireEvent.click(screen.getByTitle('2'))
  await waitFor(() => expect(reads).toHaveBeenCalledWith('2'))
})

it('shows a read failure and reloads the same asset history without writes', async () => {
  let failed = true
  server.use(
    http.get(root + '/test-cases/case-1/runs', () =>
      failed
        ? HttpResponse.json(
            {
              error: { code: 'READ_FAILED', message: '历史暂时不可用', trace_id: 'history-trace' },
            },
            { status: 503 },
          )
        : HttpResponse.json({ items: [caseRun], total: 1, page: 1, page_size: 20 }),
    ),
  )
  renderHistory()
  expect(await screen.findByText('执行历史读取失败')).toBeVisible()
  expect(screen.queryByText('当前版本筛选下没有执行记录')).not.toBeInTheDocument()
  failed = false
  fireEvent.click(screen.getByRole('button', { name: '刷新历史' }))
  expect(await screen.findByRole('link', { name: '报告' })).toBeVisible()
})

it('does not replace a new asset history with a slower prior asset response', async () => {
  server.use(
    http.get(root + '/test-cases/:id/runs', async ({ params }) => {
      if (params.id === 'case-slow') await delay(120)
      return HttpResponse.json({
        items: [{ ...caseRun, id: String(params.id), execution_id: String(params.id) }],
        total: 1,
        page: 1,
        page_size: 20,
      })
    }),
  )
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const tree = (id: string) => (
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <AssetRunEvidence projectId={project.id} kind="case" id={id} cases={[]} />
        </MemoryRouter>
      </QueryClientProvider>
    </AntdApp>
  )
  const view = render(tree('case-slow'))
  view.rerender(tree('case-fast'))
  const report = await screen.findByRole('link', { name: '报告' })
  expect(report).toHaveAttribute('href', `/projects/${project.id}/reports?execution=case-fast`)
  await delay(150)
  expect(screen.getByRole('link', { name: '报告' })).toHaveAttribute(
    'href',
    `/projects/${project.id}/reports?execution=case-fast`,
  )
})
