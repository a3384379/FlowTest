import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
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
} from '../lib/api'
import { project } from '../test/fixtures'
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
    expect(await screen.findByText('执行报告详情')).toBeInTheDocument()
    expect(await screen.findByText('校验订单状态')).toBeInTheDocument()
    expect(calls.detail).toBe(1)
    await browser.keyboard('{Escape}')

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
  }, 20_000)
})

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <ProjectTestProvider section="reports">
          <ReportsPage />
        </ProjectTestProvider>
      </QueryClientProvider>
    </AntdApp>,
  )
}
