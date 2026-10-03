import { createIceTheme } from '../theme/ice-theme'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  Artifact,
  CreatedNotificationWebhook,
  NotificationDelivery,
  NotificationWebhook,
  ReportExecution,
  ReportExecutionDetail,
  ReportTrend,
  WorkflowNodeObservation,
} from '../lib/api'
import { project, workflowExecutionDetail } from '../test/fixtures'
import { server } from '../test/server'
import ProjectTestProvider from '../test/ProjectTestProvider'
import ReportsPage from './ReportsPage'

const execution: ReportExecution = {
  id: '00000000-0000-4000-8000-000000000101',
  workflow_id: '00000000-0000-4000-8000-000000000060',
  workflow_name: '订单回归流程',
  workflow_version: 3,
  status: 'failed',
  failure_category: 'assertion',
  total_nodes: 4,
  passed_nodes: 2,
  failed_nodes: 1,
  skipped_nodes: 1,
  duration_ms: 2350,
  started_at: '2026-08-09T09:00:00Z',
  completed_at: '2026-08-09T09:00:02.350Z',
}

const detail: ReportExecutionDetail = {
  summary: execution,
  nodes: [
    {
      id: '00000000-0000-4000-8000-000000000102',
      node_id: 'assert-order',
      node_type: 'assert',
      name: '校验订单状态',
      status: 'failed',
      attempts: 1,
      duration_ms: 2,
      request: null,
      response: null,
      extraction: null,
      assertion: { passed: false, expected: 'paid', actual: 'pending' },
      input_mappings: null,
      error_code: 'WORKFLOW_ASSERTION_FAILED',
      error_message: '实际值不满足断言',
    },
  ],
  context: {},
  dataset_children: [],
}

const trend: ReportTrend = {
  points: [
    {
      date: '2026-08-09',
      total: 1,
      passed: 0,
      failed: 1,
      cancelled: 0,
      pass_rate: 0,
      average_duration_ms: 2350,
    },
  ],
  failures: [{ category: 'assertion', count: 1 }],
}

const webhook: NotificationWebhook = {
  id: '00000000-0000-4000-8000-000000000110',
  project_id: project.id,
  name: '质量平台',
  url: 'https://quality.example.test/hooks/flowtest',
  events: ['workflow.completed'],
  enabled: true,
  created_by_id: '00000000-0000-4000-8000-000000000001',
  created_at: '2026-08-09T09:00:00Z',
  updated_at: '2026-08-09T09:00:00Z',
}

const delivery: NotificationDelivery = {
  id: '00000000-0000-4000-8000-000000000111',
  webhook_id: webhook.id,
  event_type: 'workflow.completed',
  resource_id: execution.id,
  status: 'delivered',
  attempt: 1,
  response_status: 204,
  error_message: null,
  delivered_at: '2026-08-09T09:00:03Z',
  created_at: '2026-08-09T09:00:03Z',
}

const artifact: Artifact = {
  id: '00000000-0000-4000-8000-000000000120',
  project_id: project.id,
  filename: 'flowtest-report.html',
  content_type: 'text/html; charset=utf-8',
  size_bytes: 100,
  sha256: 'a'.repeat(64),
  purpose: 'report',
  created_at: '2026-08-09T09:00:04Z',
}

describe('ReportsPage', () => {
  beforeEach(() => {
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/reports/executions`, () =>
        HttpResponse.json({ items: [execution], total: 1, page: 1, page_size: 50 }),
      ),
      http.get(`/api/v1/projects/${project.id}/reports/trends`, () => HttpResponse.json(trend)),
      http.get(`/api/v1/projects/${project.id}/notification-webhooks`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${project.id}/notification-deliveries`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/workflow-executions/${execution.id}`, () =>
        HttpResponse.json({
          ...workflowExecutionDetail,
          execution: { ...workflowExecutionDetail.execution, id: execution.id },
        }),
      ),
    )
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:report'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  })

  it('queries failures on the server with the filtered total and resets pagination', async () => {
    const requests: Array<{ status: string | null; page: string | null }> = []
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/reports/executions`, ({ request }) => {
        const params = new URL(request.url).searchParams
        requests.push({ status: params.get('status'), page: params.get('page') })
        if (params.get('status') === 'failed')
          return HttpResponse.json({
            items: [{ ...execution, workflow_name: '更早失败流程' }],
            total: 61,
            page: Number(params.get('page')),
            page_size: 50,
          })
        return HttpResponse.json({
          items: [
            execution,
            { ...execution, id: 'passed-execution', workflow_name: '通过流程', status: 'passed' },
          ],
          total: 120,
          page: 1,
          page_size: 50,
        })
      }),
      http.get(`/api/v1/projects/${project.id}/reports/trends`, () => HttpResponse.json(trend)),
      http.get(`/api/v1/projects/${project.id}/notification-webhooks`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${project.id}/notification-deliveries`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
      ),
    )
    renderPage()
    const browser = userEvent.setup()
    expect(await screen.findByText('1/2 条本页记录')).toBeVisible()
    expect(screen.getByText('本页通过率')).toBeVisible()
    expect(screen.getByText('当前页 2 条 · 当前筛选共 120 条')).toBeVisible()
    await browser.click(screen.getByTitle('2'))
    await waitFor(() => expect(requests.at(-1)?.page).toBe('2'))
    await browser.click(screen.getByRole('combobox', { name: '执行状态' }))
    await browser.click(screen.getByText('仅失败', { selector: '.ant-select-item-option-content' }))
    expect(await screen.findByText('当前页 1 条 · 当前筛选共 61 条')).toBeVisible()
    expect(requests.at(-1)).toEqual({ status: 'failed', page: '1' })
    expect(screen.queryByText('通过流程 · v3')).not.toBeInTheDocument()
    expect(screen.getByText('更早失败流程 · v3')).toBeVisible()
  })

  it('drills into reports, exports HTML and manages signed notifications', async () => {
    const calls = { detail: 0, export: 0, created: 0, toggled: 0 }
    const createdWebhook: CreatedNotificationWebhook = {
      ...webhook,
      id: '00000000-0000-4000-8000-000000000112',
      name: '发布通知',
      secret: 'ftnotify_created-once',
    }
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/reports/executions`, () =>
        HttpResponse.json({ items: [execution], total: 1, page: 1, page_size: 50 }),
      ),
      http.get(`/api/v1/projects/${project.id}/reports/trends`, () => HttpResponse.json(trend)),
      http.get(`/api/v1/projects/${project.id}/notification-webhooks`, () =>
        HttpResponse.json([webhook]),
      ),
      http.get(`/api/v1/projects/${project.id}/notification-deliveries`, () =>
        HttpResponse.json({ items: [delivery], total: 1, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/reports/executions/${execution.id}`, () => {
        calls.detail += 1
        return HttpResponse.json(detail)
      }),
      http.post(
        `/api/v1/projects/${project.id}/reports/executions/${execution.id}/exports/html`,
        () => {
          calls.export += 1
          return HttpResponse.json(artifact, { status: 201 })
        },
      ),
      http.get(`/api/v1/projects/${project.id}/files/${artifact.id}`, () =>
        HttpResponse.arrayBuffer(new TextEncoder().encode('<html>report</html>').buffer),
      ),
      http.post(`/api/v1/projects/${project.id}/notification-webhooks`, async ({ request }) => {
        const body = (await request.json()) as { events: string[] }
        expect(body.events).toEqual(['workflow.completed', 'test_plan.completed'])
        calls.created += 1
        return HttpResponse.json(createdWebhook, { status: 201 })
      }),
      http.patch(
        `/api/v1/projects/${project.id}/notification-webhooks/${webhook.id}`,
        async ({ request }) => {
          expect(await request.json()).toEqual({ enabled: false })
          calls.toggled += 1
          return HttpResponse.json({ ...webhook, enabled: false })
        },
      ),
    )
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByRole('heading', { name: '测试报告' })).toBeVisible()
    expect(await screen.findByText('订单回归流程 · v3')).toBeVisible()
    expect(screen.getAllByText('断言失败').length).toBeGreaterThan(0)
    expect(screen.getByText('workflow.completed')).toBeVisible()

    await browser.click(screen.getByRole('button', { name: /详情/ }))
    expect(await screen.findByRole('region', { name: '执行报告详情' })).toBeInTheDocument()
    expect((await screen.findAllByText('校验订单状态')).length).toBeGreaterThan(0)
    await waitFor(() => expect(screen.getByText('期望值')).toBeVisible())
    expect(screen.getByText('实际值')).toBeVisible()
    expect(calls.detail).toBe(1)
    await browser.click(screen.getByRole('button', { name: '返回执行列表' }))

    await browser.click(screen.getByRole('button', { name: /HTML/ }))
    await waitFor(() => expect(calls.export).toBe(1))

    await browser.click(screen.getByRole('switch', { name: '启用 质量平台' }))
    await waitFor(() => expect(calls.toggled).toBe(1))

    await browser.click(screen.getByRole('button', { name: /配置通知/ }))
    await browser.type(screen.getByLabelText('名称'), '发布通知')
    await browser.type(screen.getByLabelText('HTTPS 地址'), 'https://notify.example.test/flowtest')
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    expect(await screen.findByText(createdWebhook.secret)).toBeInTheDocument()
    expect(calls.created).toBe(1)
  })

  it('links a report node to the same execution snapshot and preserves the execution in its URL', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/reports/executions/${execution.id}`, () =>
        HttpResponse.json(detail),
      ),
    )
    renderPage(`/projects/${project.id}/reports?execution=${execution.id}&node=assert-order`)
    const link = await screen.findByRole('link', { name: '定位画布' })
    expect(link).toHaveAttribute(
      'href',
      `/projects/${project.id}/workflows?focus=${execution.workflow_id}&execution=${execution.id}&node=assert-order`,
    )
    expect(screen.getByText('期望值')).toBeVisible()
    expect(screen.getByText('"pending"')).toBeVisible()
  })

  it('loads the next report page from the server', async () => {
    const pages: string[] = []
    server.use(
      http.get(`/api/v1/projects/${project.id}/reports/executions`, ({ request }) => {
        const page = new URL(request.url).searchParams.get('page')!
        pages.push(page)
        return HttpResponse.json({
          items: [{ ...execution, workflow_name: page === '2' ? '第二页流程' : '第一页流程' }],
          total: 120,
          page: Number(page),
          page_size: 50,
        })
      }),
    )
    renderPage()
    await screen.findByText('第一页流程 · v3')
    fireEvent.click(screen.getByTitle('2'))
    expect(await screen.findByText('第二页流程 · v3')).toBeVisible()
    expect(pages).toEqual(['1', '2'])
  })

  it('selects the exact request attempt and keeps it in the canvas link', async () => {
    const observation = (attempt: number): WorkflowNodeObservation => ({
      kind: 'http',
      attempt,
      request: {
        method: 'GET',
        url: `https://orders.example.test/${attempt}`,
        headers: {},
        body: null,
      },
      response: {
        status_code: attempt === 1 ? 503 : 200,
        headers: {},
        body: { selected_attempt: attempt },
        size_bytes: 20,
      },
      mappings: [],
      duration_ms: 20,
      started_at: execution.started_at,
      completed_at: '2026-08-15T08:00:01Z',
      error_code: null,
      error_message: null,
    })
    const apiNode = {
      ...detail.nodes[0],
      id: 'api-node',
      node_id: 'api',
      node_type: 'api',
      name: '查询订单',
      status: 'passed' as const,
      assertion: null,
      attempts: 2,
      observations: [observation(1), observation(2)],
    }
    server.use(
      http.get(`/api/v1/projects/${project.id}/reports/executions/${execution.id}`, () =>
        HttpResponse.json({ ...detail, nodes: [apiNode, detail.nodes[0]] }),
      ),
    )
    renderPage(`/projects/${project.id}/reports?execution=${execution.id}&node=api&attempt=1`)
    const link = await screen.findByRole('link', { name: '定位画布' })
    expect(link).toHaveAttribute(
      'href',
      `/projects/${project.id}/workflows?focus=${execution.workflow_id}&execution=${execution.id}&node=api&attempt=1`,
    )
    expect(screen.getByText(/"selected_attempt": 1/)).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: /校验订单状态/ }))
    expect(await screen.findByText('期望值')).toBeVisible()
    expect(screen.getByRole('link', { name: '定位画布' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/workflows?focus=${execution.workflow_id}&execution=${execution.id}&node=assert-order`,
    )
    expect(screen.queryByText(/"selected_attempt": 1/)).not.toBeInTheDocument()
  })

  it('restores the exact control instance in reports and carries it back to the canvas', async () => {
    const instanceId = '__nested_request__:third-item'
    const apiNode = {
      ...detail.nodes[0],
      node_id: 'loop',
      name: '订单循环',
      node_type: 'capability',
      assertion: null,
      output: {
        report_kind: 'iteration',
        report_paged: true,
        record_count: 3,
        input_count: 3,
        completed_count: 3,
        failed_count: 1,
      },
    }
    const path = `/api/v1/projects/${project.id}/workflow-executions/${execution.id}`
    server.use(
      http.get(`/api/v1/projects/${project.id}/reports/executions/${execution.id}`, () =>
        HttpResponse.json({ ...detail, nodes: [apiNode, detail.nodes[0]] }),
      ),
      http.get(`${path}/control-records`, () =>
        HttpResponse.json({
          items: [{ ordinal: 2, status: 'failed', test_verdict: 'failed' }],
          total: 3,
          page: 1,
          page_size: 20,
        }),
      ),
      http.get(`${path}/control-records/iteration/2`, () =>
        HttpResponse.json({
          kind: 'iteration',
          ordinal: 2,
          status: 'failed',
          test_verdict: 'failed',
          payload: {
            input_index: 2,
            status: 'failed',
            nodes: [{ node_id: 'check', instance_id: instanceId, status: 'failed' }],
          },
        }),
      ),
      http.get(`${path}/instances/${instanceId}`, () =>
        HttpResponse.json({
          id: 'checkpoint-3',
          node_id: instanceId,
          node_name: '第三项金额',
          status: 'failed',
          phase: 'main',
          attempt: 1,
          output: { item: 3 },
          result: { assertions: [{ name: '金额', passed: false, expected: 29900, actual: 29901 }] },
        }),
      ),
    )
    const params = new URLSearchParams({
      execution: execution.id,
      node: 'loop',
      control_kind: 'iteration',
      control_ordinal: '2',
      instance: instanceId,
      instance_attempt: '1',
    })
    renderPage(`/projects/${project.id}/reports?${params}`)
    const instance = await screen.findByRole('region', { name: '实例执行证据' })
    expect(within(instance).getByText('29901')).toBeVisible()
    const link = screen.getByRole('link', { name: '定位画布' })
    const selection = new URL(link.getAttribute('href')!, 'https://flowtest.test').searchParams
    expect(selection.get('control_ordinal')).toBe('2')
    expect(selection.get('instance')).toBe(instanceId)
    expect(selection.get('instance_attempt')).toBe('1')
    fireEvent.click(screen.getByRole('button', { name: /订单循环/ }))
    expect(screen.getByRole('region', { name: '实例执行证据' })).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: /校验订单状态/ }))
    await waitFor(() =>
      expect(screen.queryByRole('region', { name: '实例执行证据' })).not.toBeInTheDocument(),
    )
    expect(screen.getByRole('link', { name: '定位画布' }).getAttribute('href')).not.toContain(
      'instance=',
    )
  })

  it('downloads an external response body through the existing authorized file endpoint', async () => {
    const browser = userEvent.setup()
    let reads = 0
    const apiNode = {
      ...detail.nodes[0],
      node_id: 'large-api',
      assertion: null,
      response: {
        status_code: 200,
        headers: {},
        size_bytes: 3000000,
        body: {
          __flowtest_workflow_output_ref__: { artifact_id: artifact.id, size_bytes: 3000000 },
        },
      },
    }
    server.use(
      http.get(`/api/v1/projects/${project.id}/reports/executions/${execution.id}`, () =>
        HttpResponse.json({ ...detail, nodes: [apiNode] }),
      ),
      http.get(`/api/v1/projects/${project.id}/files/${artifact.id}`, () => {
        reads += 1
        return new HttpResponse('stored response', {
          headers: { 'Content-Type': 'application/json' },
        })
      }),
    )
    renderPage(`/projects/${project.id}/reports?execution=${execution.id}`)
    await browser.click(await screen.findByRole('button', { name: '下载响应体' }))
    await waitFor(() => expect(reads).toBe(1))
    expect(URL.createObjectURL).toHaveBeenCalled()
  })
})

function renderPage(initialEntry?: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <ConfigProvider theme={createIceTheme(true)}>
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <ProjectTestProvider section="reports" initialEntry={initialEntry}>
            <ReportsPage />
          </ProjectTestProvider>
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
}
