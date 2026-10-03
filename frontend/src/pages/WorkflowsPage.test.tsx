import { useAuthStore } from '../features/auth/auth-store'
import { authenticateTestUser } from '../test/auth'
import { user as authenticatedUser } from '../test/fixtures'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import WorkflowsPage, { DatasetRunSummary } from './WorkflowsPage'
import {
  apiDefinition,
  environment,
  project,
  workflow,
  workflowExecutionDetail,
  workflowRunningExecution,
  workflowVersion,
  workflowDefinition,
} from '../test/fixtures'
import { server } from '../test/server'
import ProjectProvider from '../features/projects/ProjectProvider'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { DraftSessionProvider } from '../features/drafts/DraftSessionProvider'

beforeEach(() => authenticateTestUser(authenticatedUser))
afterEach(() => {
  useAuthStore.setState({ user: null })
  localStorage.clear()
})

describe('WorkflowsPage', () => {
  beforeEach(() => {
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/environments`, () =>
        HttpResponse.json([environment]),
      ),
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({ items: [apiDefinition], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/files`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/services`, () => HttpResponse.json([])),
      http.get(
        `/api/v1/projects/${project.id}/environments/${environment.id}/service-endpoints`,
        () => HttpResponse.json([]),
      ),
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
      http.get(`/api/v1/projects/${project.id}/workflows`, () =>
        HttpResponse.json({ items: [workflow], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/workflow-executions`, () =>
        HttpResponse.json({
          items: [workflowExecutionDetail.execution],
          total: 1,
          page: 1,
          page_size: 20,
        }),
      ),
      http.post(`/api/v1/projects/${project.id}/workflows/${workflow.id}/versions`, () =>
        HttpResponse.json(workflowVersion),
      ),
      http.post(`/api/v1/projects/${project.id}/workflows/${workflow.id}/debug`, () =>
        HttpResponse.json(debugResult),
      ),
      http.post(
        `/api/v1/projects/${project.id}/workflow-executions/${workflowRunningExecution.id}/nodes/api/replay`,
        () => HttpResponse.json({ ...debugResult, mode: 'replay', target_node_id: 'api' }),
      ),
      http.patch(`/api/v1/projects/${project.id}/workflows/${workflow.id}`, async ({ request }) => {
        const payload = (await request.json()) as {
          expected_revision: number
          definition: { nodes: Array<{ id: string; name: string }> }
        }
        expect(payload.expected_revision).toBe(1)
        expect(payload.definition.nodes.find((node) => node.id === 'api')?.name).toBe('用户查询')
        return HttpResponse.json({ ...workflow, draft_revision: 2 })
      }),
      http.post(
        `/api/v1/projects/${project.id}/workflows/${workflow.id}/executions`,
        async ({ request }) => {
          expect(await request.json()).toEqual({ environment_id: environment.id, version: 1 })
          return HttpResponse.json(workflowRunningExecution, { status: 202 })
        },
      ),
      http.get(
        `/api/v1/projects/${project.id}/workflow-executions/${workflowRunningExecution.id}`,
        () =>
          HttpResponse.json({
            ...workflowExecutionDetail,
            execution: {
              ...workflowExecutionDetail.execution,
              snapshot: { workflow: { version: 2, definition: workflowDefinition } },
            },
          }),
      ),
    )
  })

  it('opens a linked case execution in the existing history detail', async () => {
    renderPage(
      `/projects/${project.id}/workflows?focus=${workflow.id}&execution=${workflowRunningExecution.id}`,
    )
    expect(await screen.findByText('正在查看历史执行快照')).toBeVisible()
    expect(screen.getByText(/不会随当前草稿变化/)).toBeVisible()
  })

  it('protects unapplied node inputs when closing a workflow tab', async () => {
    renderPage()
    await screen.findByText('已发布 v1')
    fireEvent.click(screen.getByTestId('rf__node-api'))
    fireEvent.change(screen.getByDisplayValue('查询用户'), {
      target: { value: '尚未应用的请求名称' },
    })
    const tab = screen.getByRole('tab', { name: new RegExp(workflow.name) })
    await waitFor(() => expect(tab).toHaveTextContent('·'))
    fireEvent.click(within(tab.parentElement!).getByRole('button'))
    const dialog = await screen.findByRole('dialog')
    await waitFor(() => expect(within(dialog).getByText('有尚未应用的节点配置')).toBeVisible())
    expect(within(dialog).getByRole('button', { name: '保存并关闭' })).toBeDisabled()
    fireEvent.click(within(dialog).getByRole('button', { name: /取\s*消/ }))
    expect(screen.getByDisplayValue('尚未应用的请求名称')).toBeVisible()
    fireEvent.click(within(tab.parentElement!).getByRole('button'))
    fireEvent.click(
      within(await screen.findByRole('dialog')).getByRole('button', {
        name: '丢弃并关闭',
      }),
    )
    await waitFor(() =>
      expect(screen.queryByDisplayValue('尚未应用的请求名称')).not.toBeInTheDocument(),
    )
    expect(screen.queryByRole('tab', { name: new RegExp(workflow.name) })).not.toBeInTheDocument()
  })

  it('asks before viewing history and preserves unapplied inputs when returning to the draft', async () => {
    renderPage()
    await screen.findByText('已发布 v1')
    fireEvent.click(screen.getByTestId('rf__node-api'))
    fireEvent.change(screen.getByDisplayValue('查询用户'), {
      target: { value: '历史切换前的未应用名称' },
    })
    fireEvent.click(screen.getByRole('button', { name: '打开执行历史' }))
    fireEvent.click(screen.getByTestId(`workflow-history-${workflowExecutionDetail.execution.id}`))
    const dialog = await screen.findByRole('dialog')
    await waitFor(() => expect(within(dialog).getByText('草稿尚未持久化')).toBeVisible())
    fireEvent.click(within(dialog).getByRole('button', { name: '留在当前页保存' }))
    expect(screen.getByDisplayValue('历史切换前的未应用名称')).toBeVisible()
    fireEvent.click(screen.getByTestId(`workflow-history-${workflowExecutionDetail.execution.id}`))
    fireEvent.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: '保留草稿并切换' }),
    )
    expect(await screen.findByText('正在查看历史执行快照')).toBeVisible()
    fireEvent.click(screen.getByRole('radio', { name: '编排' }))
    fireEvent.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: '保留草稿并切换' }),
    )
    expect(await screen.findByDisplayValue('历史切换前的未应用名称')).toBeVisible()
    expect(screen.getByText('配置尚未应用')).toBeVisible()
  })

  it('discovers workflows after the first hundred without dropping off-page object tabs', async () => {
    const catalog = [
      workflow,
      ...Array.from({ length: 100 }, (_, index) => ({
        ...workflow,
        id: `00000000-0000-4000-8000-${String(index + 100).padStart(12, '0')}`,
        name: `目录流程${index + 2}`,
      })),
    ]
    const later = catalog[100]
    const requests: { page: number; search: string }[] = []
    server.use(
      http.get(`/api/v1/projects/${project.id}/workflows`, ({ request }) => {
        const params = new URL(request.url).searchParams
        const page = Number(params.get('page') ?? 1)
        const search = params.get('search') ?? ''
        requests.push({ page, search })
        const matches = catalog.filter((candidate) => candidate.name.includes(search))
        return HttpResponse.json({
          items: matches.slice((page - 1) * 100, page * 100),
          total: matches.length,
          page,
          page_size: 100,
        })
      }),
      http.get(`/api/v1/projects/${project.id}/workflows/:id`, ({ params }) =>
        HttpResponse.json(catalog.find((candidate) => candidate.id === params.id)),
      ),
    )
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '切换工作流列表' }))
    expect(await screen.findByText('匹配 101 个流程，每页 100 项')).toBeVisible()
    const directory = screen.getByRole('navigation', { name: '流程目录分页' })
    fireEvent.click(within(directory).getByTitle('2'))
    const next = await screen.findByRole('button', { name: later.name })
    fireEvent.click(next)
    expect(await screen.findByRole('tab', { name: later.name })).toBeVisible()
    expect(screen.getByRole('tab', { name: workflow.name })).toBeVisible()
    fireEvent.change(screen.getByRole('searchbox', { name: '搜索工作流' }), {
      target: { value: later.name },
    })
    expect(await screen.findByText('匹配 1 个流程，每页 100 项')).toBeVisible()
    expect(screen.getByRole('tab', { name: workflow.name })).toBeVisible()
    expect(screen.getByRole('tab', { name: later.name })).toHaveAttribute('aria-selected', 'true')
    expect(requests).toContainEqual({ page: 2, search: '' })
    expect(requests).toContainEqual({ page: 1, search: later.name })
  })

  it('falls back to an available workflow when the focused workflow was archived', async () => {
    let missingRequests = 0
    server.use(
      http.get(`/api/v1/projects/${project.id}/workflows/archived`, () => {
        missingRequests += 1
        return HttpResponse.json({ error: { code: 'WORKFLOW_NOT_FOUND' } }, { status: 404 })
      }),
    )
    renderPage(`/projects/${project.id}/workflows?focus=archived`)

    expect(await screen.findByText('已发布 v1')).toBeVisible()
    expect(screen.getByLabelText('工作流画布')).toBeVisible()
    expect(missingRequests).toBe(0)
  })

  it('opens a report deep link in the frozen execution and locates its node', async () => {
    renderPage(
      `/projects/${project.id}/workflows?focus=${workflow.id}&execution=${workflowRunningExecution.id}&node=api&attempt=1`,
    )
    expect(await screen.findByText('正在查看历史执行快照')).toBeVisible()
    expect(screen.getByText('执行版本 v2')).toBeVisible()
    expect(screen.queryByRole('button', { name: '保存草稿' })).not.toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: '查询用户', level: 5 })).toBeVisible()
    fireEvent.click(screen.getByTestId('rf__node-api'))
    expect(screen.getByRole('link', { name: '查看完整报告' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/reports?execution=${workflowRunningExecution.id}&node=api&attempt=1`,
    )
  })

  it('keeps the execution snapshot readable after its workflow was removed', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/workflows`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/workflows/${workflow.id}`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'WORKFLOW_NOT_FOUND',
              message: '流程已删除',
              trace_id: 'history-removed',
            },
          },
          { status: 404 },
        ),
      ),
    )
    renderPage(
      `/projects/${project.id}/workflows?focus=${workflow.id}&execution=${workflowRunningExecution.id}&node=api`,
    )
    expect(await screen.findByRole('heading', { name: '查询用户', level: 5 })).toBeVisible()
    expect(screen.getByText('执行版本 v2')).toBeVisible()
    expect(screen.getByTestId('rf__node-api')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '保存草稿' })).not.toBeInTheDocument()
  })

  it('debugs the selected workflow without changing its definition', async () => {
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByRole('heading', { name: '流程编排', level: 1 })).toBeVisible()
    expect((await screen.findAllByText(workflow.name))[0]).toBeVisible()
    expect(screen.getByText('已发布 v1')).toBeVisible()
    expect(screen.getByLabelText('工作流画布')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: /更多/ }))
    await browser.click(screen.getByRole('button', { name: /调试至断点/ }))
    expect(await screen.findByText('已运行至断点前')).toBeInTheDocument()
    expect(screen.getByText('断点调试结果')).toBeVisible()
  })

  it('adds and removes a node, then explicitly applies and saves configuration', async () => {
    renderPage()
    const browser = userEvent.setup()
    await screen.findAllByText(workflow.name)
    await browser.click(screen.getByRole('button', { name: 'plus 添加节点' }))
    await browser.click(screen.getByRole('button', { name: /添加接口请求/ }))
    await browser.click(screen.getByRole('button', { name: '返回画布' }))
    fireEvent.click(await screen.findByText('接口请求 2'))
    await browser.click(screen.getByRole('button', { name: /删除节点/ }))
    fireEvent.click(screen.getByTestId('rf__node-api'))
    const nameInput = screen.getByDisplayValue('查询用户')
    fireEvent.change(nameInput, { target: { value: '用户查询' } })
    expect(nameInput).toHaveValue('用户查询')
    await browser.click(screen.getByRole('button', { name: '应用节点配置' }))
    await browser.click(screen.getByRole('button', { name: /保存草稿/ }))
    expect(await screen.findByText('草稿已保存')).toBeInTheDocument()
  })

  it('publishes and runs an immutable workflow version', async () => {
    renderPage()
    const browser = userEvent.setup()
    await screen.findAllByText(workflow.name)
    await browser.click(screen.getByRole('button', { name: '工作流更多操作' }))
    await browser.click(screen.getByRole('button', { name: /发布服务器草稿/ }))
    await browser.click(
      within(screen.getByRole('dialog')).getByRole('button', {
        name: '发布服务器草稿',
      }),
    )
    expect(await screen.findByText('工作流 v2 已发布')).toBeInTheDocument()

    await browser.click(screen.getByRole('button', { name: '运行已发布版本' }))
    expect(await screen.findByText('工作流已开始运行')).toBeInTheDocument()
    expect(await screen.findByText('工作流执行通过')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /保存草稿/ })).toBeEnabled()
    expect(screen.getAllByText('查询用户').length).toBeGreaterThan(0)
    expect(screen.getAllByText('2').length).toBeGreaterThan(0)
    fireEvent.click(screen.getByTestId('workflow-replay-api'))
    expect(await screen.findByText('节点重放完成')).toBeInTheDocument()
    expect(screen.getByText('节点重放结果')).toBeVisible()

    fireEvent.click(screen.getByTestId('workflow-runtime-tab-history'))
    fireEvent.click(screen.getByTestId(`workflow-history-${workflowExecutionDetail.execution.id}`))
    expect(await screen.findByText('正在查看历史执行快照')).toBeVisible()
    expect(screen.getByText(/不会随当前草稿变化/)).toBeVisible()
    expect(screen.queryByRole('button', { name: /保存草稿/ })).not.toBeInTheDocument()
  })

  it.each([false, true])(
    'starts a derived run for selected failed input indices after resource verification (paged=%s)',
    async (paged) => {
      const source = workflowExecutionDetail.execution
      let submitted: unknown
      let attempts = 0
      server.use(
        http.get(`/api/v1/projects/${project.id}/workflow-executions/${source.id}`, () =>
          HttpResponse.json({
            ...workflowExecutionDetail,
            execution: {
              ...source,
              snapshot: { workflow: { version: 2, definition: workflowDefinition } },
            },
            nodes: [
              ...workflowExecutionDetail.nodes,
              {
                id: '00000000-0000-4000-8000-000000000079',
                node_id: 'loop',
                node_type: 'capability',
                name: '集合遍历',
                phase: 'main',
                status: 'passed',
                attempts: 1,
                output: paged
                  ? {
                      input_count: 3,
                      failed_count: 2,
                      report_kind: 'iteration',
                      report_paged: true,
                      record_count: 3,
                    }
                  : {
                      input_count: 3,
                      failed_count: 2,
                      items: [
                        { input_index: 0, test_verdict: 'failed', nodes: [] },
                        { input_index: 1, test_verdict: 'failed', nodes: [] },
                        { input_index: 2, test_verdict: 'passed', nodes: [] },
                      ],
                    },
                error_code: null,
                error_message: null,
              },
            ],
          }),
        ),
        http.get(
          `/api/v1/projects/${project.id}/workflow-executions/${source.id}/control-records`,
          () =>
            HttpResponse.json({
              items: [
                { ordinal: 0, status: 'failed', test_verdict: 'failed' },
                { ordinal: 1, status: 'failed', test_verdict: 'failed' },
              ],
              total: 2,
              page: 1,
              page_size: 20,
            }),
        ),
        http.post(
          `/api/v1/projects/${project.id}/workflow-executions/${source.id}/failed-items/rerun`,
          async ({ request }) => {
            submitted = await request.json()
            attempts += 1
            if (attempts === 1) {
              return HttpResponse.json(
                {
                  error: {
                    code: 'RERUN_NESTED_CONTROL_UNSUPPORTED',
                    message: '嵌套控制块的失败项重跑仍需实例级来源校验',
                    details: null,
                    trace_id: 'rerun-e2e',
                  },
                },
                { status: 409 },
              )
            }
            return HttpResponse.json(
              {
                ...workflowRunningExecution,
                derived_from_execution_id: source.id,
                rerun_loop_node_id: 'loop',
                rerun_input_indices: [1],
              },
              { status: 202 },
            )
          },
        ),
      )
      renderPage()
      const browser = userEvent.setup()
      await screen.findAllByText(workflow.name)
      await browser.click(screen.getByRole('button', { name: '打开执行历史' }))
      await browser.click(screen.getByTestId('workflow-runtime-tab-history'))
      await browser.click(screen.getByTestId(`workflow-history-${source.id}`))
      expect(await screen.findByText('正在查看历史执行快照')).toBeVisible()
      await browser.click(screen.getByTestId('workflow-runtime-tab-run'))
      await browser.click(await screen.findByRole('button', { name: /派生重跑失败项/ }))
      const dialog = await screen.findByRole('dialog', { name: '派生重跑失败项' })
      expect(within(dialog).getByText(/原报告保留/)).toBeInTheDocument()
      await browser.click(within(dialog).getByRole('combobox', { name: '选择失败轮次' }))
      await browser.click(await screen.findByText('第 2 项（input_index 1）'))
      await browser.click(within(dialog).getByRole('combobox', { name: '上游资源状态' }))
      await browser.click(screen.getByText('已确认资源仍有效'))
      await browser.type(
        within(dialog).getByRole('textbox', { name: '外部状态查证说明' }),
        '已核对外部资源状态，当前仍有效',
      )
      const createRun = within(dialog).getByRole('button', { name: '创建派生运行' })
      expect(createRun).toBeEnabled()
      await browser.click(createRun)
      await waitFor(() =>
        expect(
          within(screen.getByRole('dialog', { name: '派生重跑失败项' })).getByText(
            '嵌套控制块的失败项重跑仍需实例级来源校验',
          ),
        ).toBeInTheDocument(),
      )
      const retryDialog = screen.getByRole('dialog', { name: '派生重跑失败项' })
      expect(within(retryDialog).getByText('第 2 项（input_index 1）')).toBeInTheDocument()
      await browser.click(within(retryDialog).getByRole('button', { name: '创建派生运行' }))
      await waitFor(() =>
        expect(submitted).toEqual({
          loop_node_id: 'loop',
          input_indices: [1],
          upstream_resource_status: 'confirmed_valid',
          write_retry_strategy: 'reject',
          verification_note: '已核对外部资源状态，当前仍有效',
        }),
      )
      expect(attempts).toBe(2)
    },
  )

  it('opens a dataset child report from the batch summary', () => {
    const parent = workflowExecutionDetail.execution
    const child = {
      ...parent,
      id: '00000000-0000-4000-8000-000000000089',
      parent_execution_id: parent.id,
      dataset_row_index: 0,
      status: 'failed' as const,
    }
    let selectedId: string | null = null
    render(<DatasetRunSummary items={[child]} onView={(id) => (selectedId = id)} />)
    expect(screen.getByText('数据集子执行')).toBeVisible()
    expect(screen.getByText('1')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '查看子执行' }))
    expect(selectedId).toBe(child.id)
  })

  it('compares the latest two immutable workflow versions', async () => {
    const versionedWorkflow = { ...workflow, current_version: 2 }
    let diffRequested = false
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/environments`, () =>
        HttpResponse.json([environment]),
      ),
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({ items: [apiDefinition], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/files`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
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
      http.get(`/api/v1/projects/${project.id}/workflows`, () =>
        HttpResponse.json({ items: [versionedWorkflow], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/workflow-executions`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
      ),
      http.get(
        '/api/v1/projects/:projectId/workflows/:workflowId/versions/:fromVersion/diff/:toVersion',
        () => {
          diffRequested = true
          return HttpResponse.json({
            from_version: 1,
            to_version: 2,
            changes: [{ path: 'nodes.api.name', before: '查询用户', after: '查询当前用户' }],
          })
        },
      ),
    )
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByText('已发布 v2')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: /更多/ }))
    await browser.click(screen.getByRole('button', { name: /版本 Diff/ }))
    expect(diffRequested).toBe(true)
    expect(screen.getByText(/nodes\.api\.name/)).toHaveTextContent('查询当前用户')
  })
})

function renderPage(initialEntry?: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <RouterProvider
            router={createMemoryRouter(
              [
                {
                  path: '*',
                  element: (
                    <ProjectProvider>
                      <DraftSessionProvider>
                        <WorkflowsPage />
                      </DraftSessionProvider>
                    </ProjectProvider>
                  ),
                },
              ],
              { initialEntries: [initialEntry ?? `/projects/${project.id}/workflows`] },
            )}
          />
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
}

const debugResult = {
  status: 'passed',
  mode: 'breakpoint',
  target_node_id: 'api',
  context: {},
  nodes: [
    {
      node_id: 'start',
      node_type: 'start',
      name: '开始',
      status: 'passed',
      attempts: 1,
      output: null,
      error_code: null,
      error_message: null,
      started_at: '2026-08-09T08:00:00Z',
      completed_at: '2026-08-09T08:00:01Z',
    },
  ],
}
