import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import type { CreatedServiceToken, CreatedTestPlan, ServiceToken, TestPlanRun } from '../lib/api'
import { environment, project, user, workflow } from '../test/fixtures'
import { server } from '../test/server'
import ProjectTestProvider from '../test/ProjectTestProvider'
import TestPlansPage from './TestPlansPage'

const plan: CreatedTestPlan = {
  id: '00000000-0000-4000-8000-000000000080',
  project_id: project.id,
  name: '每日回归',
  description: '',
  enabled: true,
  schedule_interval_seconds: 3600,
  next_run_at: '2026-08-09T10:00:00Z',
  created_by_id: user.id,
  created_at: '2026-08-09T09:00:00Z',
  updated_at: '2026-08-09T09:00:00Z',
  webhook_secret: 'fthook_created-once',
  items: [
    {
      id: '00000000-0000-4000-8000-000000000081',
      workflow_id: workflow.id,
      environment_id: environment.id,
      workflow_version: 1,
      position: 0,
      max_retries: 1,
      runtime_variables: {},
      runtime_headers: {},
    },
  ],
}

const queuedRun: TestPlanRun = {
  id: '00000000-0000-4000-8000-000000000090',
  project_id: project.id,
  test_plan_id: plan.id,
  requested_by_id: user.id,
  status: 'queued',
  trigger_type: 'manual',
  cancel_requested_at: null,
  started_at: null,
  completed_at: null,
  error_message: null,
  created_at: '2026-08-09T09:01:00Z',
}

const serviceToken: CreatedServiceToken = {
  id: '00000000-0000-4000-8000-000000000091',
  project_id: project.id,
  name: 'CI Token',
  token_prefix: 'abcdef123456',
  token: 'ftci_abcdef123456_created-once',
  scopes: ['execute:workflow', 'execute:test-plan'],
  expires_at: null,
  last_used_at: null,
  revoked_at: null,
  created_at: '2026-08-09T09:01:00Z',
}

describe('TestPlansPage', () => {
  it('creates, queues and cancels plans, and reveals one-time credentials', async () => {
    const requests = { created: 0, run: 0, cancelled: 0, token: 0 }
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/workflows`, () =>
        HttpResponse.json({ items: [workflow], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/environments`, () =>
        HttpResponse.json([environment]),
      ),
      http.get(`/api/v1/projects/${project.id}/test-plans`, () =>
        HttpResponse.json({ items: [plan], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/test-plan-runs`, () =>
        HttpResponse.json({ items: [queuedRun], total: 1, page: 1, page_size: 50 }),
      ),
      http.get(`/api/v1/projects/${project.id}/service-tokens`, () =>
        HttpResponse.json([withoutRawToken(serviceToken)]),
      ),
      http.post(`/api/v1/projects/${project.id}/service-tokens`, () => {
        requests.token += 1
        return HttpResponse.json(serviceToken, { status: 201 })
      }),
      http.post(`/api/v1/projects/${project.id}/test-plans`, async ({ request }) => {
        const body = (await request.json()) as { schedule_interval_seconds: number }
        expect(body.schedule_interval_seconds).toBe(1800)
        requests.created += 1
        return HttpResponse.json(plan, { status: 201 })
      }),
      http.post(`/api/v1/projects/${project.id}/test-plans/${plan.id}/runs`, () => {
        requests.run += 1
        return HttpResponse.json(queuedRun, { status: 202 })
      }),
      http.post(`/api/v1/projects/${project.id}/test-plan-runs/${queuedRun.id}/cancel`, () => {
        requests.cancelled += 1
        return HttpResponse.json({ ...queuedRun, status: 'cancelled' })
      }),
    )
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByRole('heading', { name: '任务执行' })).toBeVisible()
    expect(await screen.findByText('每日回归')).toBeVisible()
    expect(screen.getByText('每 60 分钟')).toBeVisible()
    expect(screen.getByText('尚未使用')).toBeVisible()

    await browser.click(screen.getByRole('button', { name: /生成 CI Token/ }))
    expect(await screen.findByText(serviceToken.token)).toBeInTheDocument()
    expect(requests.token).toBe(1)
    await browser.keyboard('{Escape}')

    await browser.click(screen.getByRole('button', { name: /新建计划/ }))
    await browser.type(screen.getByLabelText('计划名称'), '部署回归')
    await chooseSelect(browser, '工作流', workflow.name)
    await chooseSelect(browser, '环境', environment.name)
    await browser.type(screen.getByLabelText('定时间隔（分钟，留空为手动）'), '30')
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    expect(await screen.findByText(plan.webhook_secret)).toBeInTheDocument()
    expect(requests.created).toBe(1)
    await browser.keyboard('{Escape}')

    await browser.click(screen.getByRole('button', { name: /运行/ }))
    await waitFor(() => expect(requests.run).toBe(1))
    await browser.click(screen.getByRole('button', { name: /取消/ }))
    await waitFor(() => expect(requests.cancelled).toBe(1))
  }, 20_000)
})

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <ProjectTestProvider section="tasks">
          <TestPlansPage />
        </ProjectTestProvider>
      </QueryClientProvider>
    </AntdApp>,
  )
}

async function chooseSelect(
  browser: ReturnType<typeof userEvent.setup>,
  label: string,
  option: string,
) {
  await browser.click(screen.getByLabelText(label))
  await browser.click(
    await screen.findByText(option, { selector: '.ant-select-item-option-content' }),
  )
}

function withoutRawToken(created: CreatedServiceToken): ServiceToken {
  const { token, ...stored } = created
  void token
  return stored
}
