import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import ProjectProvider from '../features/projects/ProjectProvider'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { project } from '../test/fixtures'
import { server } from '../test/server'
import AIAssistantPage from './AIAssistantPage'

const job = {
  id: 'audit-job',
  project_id: project.id,
  job_type: 'failure_analysis',
  status: 'failed',
  input_sha256: 'fixed-input',
  model_name: 'audit-model',
  error_code: 'AI_QUEUE_UNAVAILABLE',
  error_message: '独立队列暂不可用',
  created_at: '2026-10-21T01:00:00Z',
  updated_at: '2026-10-21T01:00:03Z',
  completed_at: '2026-10-21T01:00:03Z',
}
function setupRequests() {
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
    ),
    http.get('/api/v1/ai/status', () =>
      HttpResponse.json({ enabled: true, model: 'audit-model', sample_sharing_enabled: false }),
    ),
    http.get('/api/v1/ai/jobs', () =>
      HttpResponse.json({ items: [job], total: 1, page: 1, page_size: 20 }),
    ),
    http.get('/api/v1/ai/jobs/:id', () => HttpResponse.json(job)),
    http.get('/api/v1/ai/jobs/:id/suggestions', () => HttpResponse.json([])),
  )
}
function setup(initialEntry?: string) {
  setupRequests()
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App>
        <QueryClientProvider client={client}>
          <ProjectTestProvider section="ai" initialEntry={initialEntry}>
            <AIAssistantPage />
          </ProjectTestProvider>
        </QueryClientProvider>
      </App>
    </ConfigProvider>,
  )
}
describe('AI audit remediation', () => {
  it('shows queue failure details, time and the absence of a supplied trace without reading suggestions', async () => {
    let suggestionReads = 0
    setup()
    server.use(
      http.get('/api/v1/ai/jobs/:id/suggestions', () => {
        suggestionReads++
        return HttpResponse.json([])
      }),
    )
    expect(await screen.findByText('AI_QUEUE_UNAVAILABLE')).toBeVisible()
    expect(screen.getByText('独立队列暂不可用')).toBeVisible()
    expect(screen.getByText('未提供 Trace ID')).toBeVisible()
    expect(screen.getByText('2026-10-21T01:00:03Z')).toBeVisible()
    expect(suggestionReads).toBe(0)
  })
  it('previews failure-analysis input and submits the same payload without requiring schema or collecting samples', async () => {
    let payload: unknown
    setup()
    server.use(
      http.post('/api/v1/ai/jobs', async ({ request }) => {
        payload = await request.json()
        return HttpResponse.json({ ...job, status: 'pending' }, { status: 202 })
      }),
    )
    await userEvent.click(await screen.findByRole('button', { name: /新建 AI 任务/ }))
    const dialog = screen.getByRole('dialog', { name: '新建 AI 建议任务' })
    await userEvent.click(within(dialog).getByLabelText('任务类型'))
    await userEvent.click(
      screen.getByText('失败归因', { selector: '.ant-select-item-option-content' }),
    )
    fireEvent.change(within(dialog).getByLabelText('失败现象'), {
      target: { value: '支付接口返回500' },
    })
    await userEvent.click(within(dialog).getByRole('button', { name: '预览提交材料' }))
    const expected = {
      project_id: project.id,
      job_type: 'failure_analysis',
      metadata: { failure_summary: '支付接口返回500' },
    }
    expect(JSON.parse(screen.getByLabelText('最终提交负载').textContent!)).toEqual(expected)
    expect(payload).toBeUndefined()
    await userEvent.click(within(dialog).getByRole('button', { name: '确认提交任务' }))
    await waitFor(() => expect(payload).toEqual(expected))
  })
  it('restores a reviewed suggestion from URL and links the actual workflow draft without writing', async () => {
    let writes = 0
    setup(`/projects/${project.id}/ai?job=audit-job&suggestion=reviewed`)
    server.use(
      http.get('/api/v1/ai/jobs/:id', () =>
        HttpResponse.json({ ...job, status: 'completed', error_code: null, error_message: null }),
      ),
      http.get('/api/v1/ai/jobs/:id/suggestions', () =>
        HttpResponse.json([
          {
            id: 'reviewed',
            job_id: job.id,
            suggestion_type: 'workflow',
            title: '已审核流程',
            content: { name: '订单草稿', definition: { nodes: [], edges: [] } },
            review_status: 'accepted',
            review_note: '人工确认流程',
            accepted_resource_type: 'workflow',
            accepted_resource_id: 'draft-workflow',
          },
        ]),
      ),
      http.post('/api/v1/ai/*', () => {
        writes++
        return HttpResponse.json({})
      }),
    )
    await waitFor(() => expect(screen.getByLabelText('审核备注')).toBeVisible())
    expect(screen.getByLabelText('审核备注')).toHaveValue('人工确认流程')
    expect(screen.getByRole('link', { name: '打开流程草稿' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/workflows?focus=draft-workflow`,
    )
    expect(writes).toBe(0)
  })
  it('keeps fixed public materials explicit, preserves them across catalog pages and previews the actual ON policy', async () => {
    let sourceReads = 0,
      writes = 0
    const metadata = {
      source_kind: 'api',
      source_id: 'api-v3',
      name: '公开接口v3',
      version: 3,
      protocol: 'http',
      method: 'GET',
      path: '/v3',
    }
    const document = { path: '/v3', description: '保留人工明确选择的原文' }
    setup()
    server.use(
      http.get(`/api/v1/projects/${project.id}/redaction-policy`, () =>
        HttpResponse.json({ mode: 'on', source: 'project', policy_version: 7 }),
      ),
      http.get(`/api/v1/ai/projects/${project.id}/sources`, ({ request }) => {
        sourceReads++
        const page = Number(new URL(request.url).searchParams.get('page'))
        return HttpResponse.json({
          items: page === 1 ? [{ id: 'api-v3', name: '公开接口v3', kind: 'api', version: 3 }] : [],
          total: 21,
          page,
          page_size: 20,
        })
      }),
      http.get(`/api/v1/ai/projects/${project.id}/sources/api/api-v3`, ({ request }) => {
        expect(new URL(request.url).searchParams.get('version')).toBe('3')
        return HttpResponse.json({
          project_id: project.id,
          metadata,
          schema_document: document,
          notices: [],
        })
      }),
      http.post('/api/v1/ai/jobs', () => {
        writes++
        return HttpResponse.json(job)
      }),
    )
    await waitFor(() => expect(screen.getByRole('button', { name: /新建 AI 任务/ })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: /新建 AI 任务/ }))
    expect(sourceReads).toBe(0)
    await waitFor(() => expect(screen.getByText(/当前自动脱敏策略：ON/)).toBeVisible())
    await userEvent.click(screen.getByRole('button', { name: /从项目选择公开材料/ }))
    const sourceCard = (
      await screen.findByText('选择公开来源', { selector: '.ant-card-head-title' })
    ).closest('.ant-card') as HTMLElement
    const viewButton = await within(sourceCard).findByRole('button', {
      name: '查看材料',
      hidden: true,
    })
    expect(sourceCard.closest('.ant-collapse-content-hidden')).toBeNull()
    expect(viewButton).toBeEnabled()
    fireEvent.click(viewButton)
    const materialPanel = await within(sourceCard).findByLabelText('公开来源材料')
    const useButton = within(materialPanel).getByRole('button', {
      name: '使用此固定材料',
      hidden: true,
    })
    expect(useButton).toBeEnabled()
    fireEvent.click(within(sourceCard).getByRole('button', { name: 'right', hidden: true }))
    await waitFor(() => expect(sourceReads).toBe(2))
    fireEvent.click(useButton)
    expect(screen.getByText(/已选择：公开接口v3/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '预览提交材料' }))
    expect(JSON.parse(screen.getByLabelText('最终提交负载').textContent!)).toEqual({
      project_id: project.id,
      job_type: 'schema_cases',
      metadata: { source: metadata },
      schema_document: document,
    })
    expect(writes).toBe(0)
  })
  it('protects dirty review notes and invalid structured edits until corrected or explicitly discarded', async () => {
    let writes = 0
    setup(`/projects/${project.id}/ai?job=audit-job&suggestion=pending`)
    server.use(
      http.get('/api/v1/ai/jobs/:id', () => HttpResponse.json({ ...job, status: 'completed' })),
      http.get('/api/v1/ai/jobs/:id/suggestions', () =>
        HttpResponse.json([
          {
            id: 'pending',
            job_id: job.id,
            suggestion_type: 'assertion',
            title: '待审核断言',
            content: { expression: 'status_code', operator: 'equals', expected: 200 },
            review_status: 'pending',
            review_note: '',
          },
        ]),
      ),
      http.post('/api/v1/ai/*', () => {
        writes++
        return HttpResponse.json({})
      }),
    )
    await waitFor(() => expect(screen.getByLabelText('审核备注')).toBeVisible())
    await waitFor(() => expect(screen.getByLabelText('审核备注')).not.toHaveAttribute('readonly'))
    fireEvent.change(screen.getByLabelText('审核备注'), { target: { value: '尚未保存的备注' } })
    fireEvent.change(screen.getByLabelText('预期值 JSON'), { target: { value: 'broken-json' } })
    fireEvent.change(screen.getByLabelText('断言表达式'), { target: { value: 'response.status' } })
    await userEvent.click(screen.getByRole('button', { name: '确认接受' }))
    expect(screen.getAllByText('预期值必须是有效 JSON').length).toBeGreaterThan(0)
    expect(writes).toBe(0)
    await userEvent.click(screen.getByRole('button', { name: /取\s*消/ }))
    const discard = (
      await screen.findByText('审核内容尚未保存', { selector: '.ant-modal-title' })
    ).closest('.ant-modal') as HTMLElement
    await waitFor(() => expect(discard).toBeVisible())
    await userEvent.click(within(discard).getByRole('button', { name: '继续编辑' }))
    expect(screen.getByLabelText('审核备注')).toHaveValue('尚未保存的备注')
    expect(screen.getByLabelText('预期值 JSON')).toHaveValue('broken-json')
    await userEvent.click(screen.getByRole('button', { name: /取\s*消/ }))
    await userEvent.click(
      within(
        screen
          .getByText('审核内容尚未保存', { selector: '.ant-modal-title' })
          .closest('.ant-modal') as HTMLElement,
      ).getByRole('button', {
        name: '放弃修改',
      }),
    )
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(writes).toBe(0)
  })
  it.each(['断言建议', 'Workflow 草稿'])(
    'previews task-specific %s fields without a schema placeholder',
    async (label) => {
      setup()
      await waitFor(() =>
        expect(screen.getByRole('button', { name: /新建 AI 任务/ })).toBeEnabled(),
      )
      await userEvent.click(screen.getByRole('button', { name: /新建 AI 任务/ }))
      const dialog = screen.getByRole('dialog', { name: '新建 AI 建议任务' })
      await userEvent.click(within(dialog).getByLabelText('任务类型'))
      await userEvent.click(
        screen.getByText(label, { selector: '.ant-select-item-option-content' }),
      )
      if (label === '断言建议') {
        fireEvent.change(within(dialog).getByLabelText('断言目标'), {
          target: { value: '验证订单' },
        })
        fireEvent.change(within(dialog).getByLabelText('待验证字段路径'), {
          target: { value: 'response.body.id' },
        })
        fireEvent.change(within(dialog).getByLabelText('预期 HTTP 状态码（可选）'), {
          target: { value: '201' },
        })
      } else {
        fireEvent.change(within(dialog).getByLabelText('流程目标'), {
          target: { value: '订单流程' },
        })
        fireEvent.change(within(dialog).getByLabelText('期望步骤（每行一步）'), {
          target: { value: ' 创建订单 \n 查询订单 ' },
        })
        fireEvent.change(within(dialog).getByLabelText('完成条件'), {
          target: { value: '订单存在' },
        })
      }
      await userEvent.click(within(dialog).getByRole('button', { name: '预览提交材料' }))
      const payload = JSON.parse(screen.getByLabelText('最终提交负载').textContent!)
      expect(payload).not.toHaveProperty('schema_document')
      expect(payload).not.toHaveProperty('sample')
      expect(payload.metadata).toEqual(
        label === '断言建议'
          ? { assertion_goal: '验证订单', response_path: 'response.body.id', expected_status: 201 }
          : {
              workflow_goal: '订单流程',
              workflow_steps: ['创建订单', '查询订单'],
              completion_condition: '订单存在',
            },
      )
    },
  )
  it('preserves a failed review draft and explicitly reloads the authoritative saved result without repeating acceptance', async () => {
    let accepted = false,
      writes = 0
    const pending = {
      id: 'pending',
      job_id: job.id,
      suggestion_type: 'workflow',
      title: '待审核流程',
      content: { name: '草稿', definition: { nodes: [], edges: [] } },
      review_status: 'pending',
      review_note: '',
    }
    setup(`/projects/${project.id}/ai?job=audit-job&suggestion=pending`)
    server.use(
      http.get('/api/v1/ai/jobs/:id', () => HttpResponse.json({ ...job, status: 'completed' })),
      http.get('/api/v1/ai/jobs/:id/suggestions', () =>
        HttpResponse.json([
          accepted
            ? {
                ...pending,
                review_status: 'accepted',
                review_note: '服务端已保存备注',
                accepted_resource_type: 'workflow',
                accepted_resource_id: 'saved-draft',
              }
            : pending,
        ]),
      ),
      http.post('/api/v1/ai/suggestions/pending/accept', () => {
        writes++
        return HttpResponse.json(
          { error: { code: 'UNAVAILABLE', message: '审核返回暂不可用', trace_id: 'review-trace' } },
          { status: 503 },
        )
      }),
    )
    await waitFor(() => expect(screen.getByLabelText('审核备注')).not.toHaveAttribute('readonly'))
    fireEvent.change(screen.getByLabelText('审核备注'), { target: { value: '需要保留的备注' } })
    await userEvent.click(screen.getByRole('button', { name: '确认接受' }))
    expect(await screen.findByText(/审核结果未确认，输入已保留/)).toBeInTheDocument()
    expect(screen.getByLabelText('审核备注')).toHaveValue('需要保留的备注')
    expect(writes).toBe(1)
    accepted = true
    await userEvent.click(screen.getByRole('button', { name: '刷新审核状态' }))
    await waitFor(() => expect(screen.getByLabelText('审核备注')).toHaveValue('服务端已保存备注'))
    expect(screen.getByLabelText('审核备注')).toHaveAttribute('readonly')
    expect(screen.getByRole('link', { name: '打开流程草稿' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/workflows?focus=saved-draft`,
    )
    expect(writes).toBe(1)
  })
  it('blocks route changes and browser unload while review edits are dirty, then leaves only after explicit discard', async () => {
    setupRequests()
    let writes = 0
    server.use(
      http.get('/api/v1/ai/jobs/:id', ({ params }) =>
        HttpResponse.json({ ...job, id: params.id, status: 'completed' }),
      ),
      http.get('/api/v1/ai/jobs/:id/suggestions', ({ params }) =>
        HttpResponse.json(
          params.id === job.id
            ? [
                {
                  id: 'pending',
                  job_id: job.id,
                  suggestion_type: 'failure_analysis',
                  title: '待审归因',
                  content: { category: 'upstream', confidence: 0.8 },
                  review_status: 'pending',
                  review_note: '',
                },
              ]
            : [],
        ),
      ),
      http.post('/api/v1/ai/*', () => {
        writes++
        return HttpResponse.json({})
      }),
    )
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    const router = createMemoryRouter(
      [
        {
          path: '/projects/:projectId/*',
          element: (
            <ProjectProvider>
              <AIAssistantPage />
            </ProjectProvider>
          ),
        },
      ],
      { initialEntries: [`/projects/${project.id}/ai?job=${job.id}&suggestion=pending`] },
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
    await waitFor(() => expect(screen.getByLabelText('审核备注')).not.toHaveAttribute('readonly'))
    fireEvent.change(screen.getByLabelText('审核备注'), {
      target: { value: '导航前必须保留的备注' },
    })
    const unload = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(unload)
    expect(unload.defaultPrevented).toBe(true)
    const destination = `/projects/${project.id}/ai?job=other`
    await act(async () => {
      await router.navigate(destination)
    })
    let title = await screen.findByText('审核内容尚未保存', { selector: '.ant-modal-title' })
    await userEvent.click(
      within(title.closest('.ant-modal') as HTMLElement).getByRole('button', { name: '继续编辑' }),
    )
    expect(screen.getByLabelText('审核备注')).toHaveValue('导航前必须保留的备注')
    expect(new URLSearchParams(router.state.location.search).get('job')).toBe(job.id)
    await act(async () => {
      await router.navigate(destination)
    })
    title = await screen.findByText('审核内容尚未保存', { selector: '.ant-modal-title' })
    await userEvent.click(
      within(title.closest('.ant-modal') as HTMLElement).getByRole('button', {
        name: '放弃修改并离开',
      }),
    )
    await waitFor(() =>
      expect(router.state.location.pathname + router.state.location.search).toBe(destination),
    )
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(writes).toBe(0)
  })
  it('protects a new task on navigation but allows its explicitly confirmed submission to select the returned job', async () => {
    setupRequests()
    let writes = 0
    server.use(
      http.get('/api/v1/ai/jobs/:id', ({ params }) =>
        HttpResponse.json({ ...job, id: params.id, status: 'pending' }),
      ),
      http.post('/api/v1/ai/jobs', () => {
        writes++
        return HttpResponse.json({ ...job, id: 'created-job', status: 'pending' }, { status: 202 })
      }),
    )
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    const router = createMemoryRouter(
      [
        {
          path: '/projects/:projectId/*',
          element: (
            <ProjectProvider>
              <AIAssistantPage />
            </ProjectProvider>
          ),
        },
      ],
      { initialEntries: [`/projects/${project.id}/ai`] },
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
    await waitFor(() => expect(screen.getByRole('button', { name: /新建 AI 任务/ })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: /新建 AI 任务/ }))
    const dialog = screen.getByRole('dialog', { name: '新建 AI 建议任务' })
    await userEvent.click(within(dialog).getByLabelText('任务类型'))
    await userEvent.click(
      screen.getByText('失败归因', { selector: '.ant-select-item-option-content' }),
    )
    fireEvent.change(within(dialog).getByLabelText('失败现象'), {
      target: { value: '明确提交的现象' },
    })
    await userEvent.click(within(dialog).getByRole('button', { name: '预览提交材料' }))
    const unload = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(unload)
    expect(unload.defaultPrevented).toBe(true)
    await act(async () => {
      await router.navigate(`/projects/${project.id}/ai?job=other`)
    })
    const title = await screen.findByText('提交材料尚未保存', { selector: '.ant-modal-title' })
    await userEvent.click(
      within(title.closest('.ant-modal') as HTMLElement).getByRole('button', { name: '继续编辑' }),
    )
    expect(screen.getByLabelText('最终提交负载')).toHaveTextContent('明确提交的现象')
    await userEvent.click(within(dialog).getByRole('button', { name: '确认提交任务' }))
    await waitFor(() =>
      expect(new URLSearchParams(router.state.location.search).get('job')).toBe('created-job'),
    )
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(writes).toBe(1)
  })
})
