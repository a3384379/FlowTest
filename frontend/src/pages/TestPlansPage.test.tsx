import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import type {
  CreatedServiceToken,
  CreatedTestPlan,
  ServiceToken,
  TestCase,
  TestPlanRun,
  TestSuite,
} from '../lib/api'
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
  schedule_cron: null,
  schedule_timezone: 'Asia/Shanghai',
  queue_priority: 5,
  next_run_at: '2026-08-09T10:00:00Z',
  created_by_id: user.id,
  created_at: '2026-08-09T09:00:00Z',
  updated_at: '2026-08-09T09:00:00Z',
  webhook_secret: 'fthook_created-once',
  items: [
    {
      id: '00000000-0000-4000-8000-000000000081',
      target_type: 'workflow',
      target_id: workflow.id,
      target_version: 1,
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
  queue_priority: 5,
  queue_name: 'general',
  baseline_run_id: null,
  quality_summary: {},
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

const testCase: TestCase = {
  id: '00000000-0000-4000-8000-000000000092',
  project_id: project.id,
  folder_id: null,
  name: '登录用例',
  description: '',
  tags: [],
  is_template: false,
  draft_definition: {
    workflow_id: workflow.id,
    workflow_version: 1,
    environment_id: environment.id,
    runtime_variables: {},
    runtime_headers: {},
  },
  current_version: 2,
  created_by_id: user.id,
  created_at: '2026-08-09T09:00:00Z',
  updated_at: '2026-08-09T09:00:00Z',
}

const testSuite: TestSuite = {
  id: '00000000-0000-4000-8000-000000000093',
  project_id: project.id,
  folder_id: null,
  name: '冒烟套件',
  description: '',
  tags: [],
  draft_definition: { items: [{ test_case_id: testCase.id, test_case_version: 2 }] },
  current_version: 1,
  created_by_id: user.id,
  created_at: '2026-08-09T09:00:00Z',
  updated_at: '2026-08-09T09:00:00Z',
}

describe('TestPlansPage', () => {
  it('allows viewers to inspect queues without querying owner credentials or writing assets', async () => {
    let forbiddenRequests = 0
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
      http.get(`/api/v1/projects/${project.id}/test-cases`, () =>
        HttpResponse.json({ items: [testCase], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/test-suites`, () =>
        HttpResponse.json({ items: [testSuite], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/test-plans`, () =>
        HttpResponse.json({ items: [plan], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/test-plan-runs`, () =>
        HttpResponse.json({ items: [queuedRun], total: 1, page: 1, page_size: 50 }),
      ),
      http.get(`/api/v1/projects/${project.id}/service-tokens`, () => {
        forbiddenRequests += 1
        return HttpResponse.json([])
      }),
      http.post('/api/v1/projects/:projectId/*', () => {
        forbiddenRequests += 1
        return HttpResponse.json({})
      }),
    )
    renderPage('viewer')
    expect(await screen.findByText('每日回归')).toBeVisible()
    for (const name of [/新建计划/, /生成 CI Token/, /运行/, /取消/]) {
      const button = screen.getByRole('button', { name })
      expect(button).toBeDisabled()
      await userEvent.click(button)
    }
    expect(screen.queryByText('CI 凭据')).not.toBeInTheDocument()
    expect(forbiddenRequests).toBe(0)
  })

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
      http.get(`/api/v1/projects/${project.id}/test-cases`, () =>
        HttpResponse.json({ items: [testCase], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/test-suites`, () =>
        HttpResponse.json({ items: [testSuite], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/test-plans`, () =>
        HttpResponse.json({
          items: [
            plan,
            {
              ...plan,
              id: `${plan.id}-cron`,
              name: 'Cron 回归',
              schedule_interval_seconds: null,
              schedule_cron: '0 9 * * 1-5',
            },
            {
              ...plan,
              id: `${plan.id}-manual`,
              name: '手动回归',
              schedule_interval_seconds: null,
            },
          ],
          total: 3,
          page: 1,
          page_size: 100,
        }),
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
        const body = (await request.json()) as {
          schedule_interval_seconds: number | null
          schedule_cron: string | null
          schedule_timezone: string
          queue_priority: number
          items: Array<{
            target_type: string
            target_id: string
            target_version: number
            environment_id: string | null
          }>
        }
        if (requests.created === 0) {
          expect(body.schedule_interval_seconds).toBe(1800)
        } else {
          expect(body).toMatchObject({
            schedule_interval_seconds: null,
            schedule_cron: '0 9 * * 1-5',
            schedule_timezone: 'Asia/Shanghai',
            queue_priority: 9,
          })
        }
        expect(body.items[0]).toMatchObject({
          target_type: 'suite',
          target_id: testSuite.id,
          target_version: 1,
          environment_id: null,
        })
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
    expect(screen.getByText('0 9 * * 1-5 · Asia/Shanghai')).toBeVisible()
    expect(screen.getByText('手动')).toBeVisible()
    expect(screen.getByText('尚未使用')).toBeVisible()

    await browser.click(screen.getByRole('button', { name: /生成 CI Token/ }))
    expect(await screen.findByText(serviceToken.token)).toBeInTheDocument()
    expect(requests.token).toBe(1)
    await browser.keyboard('{Escape}')

    await browser.click(screen.getByRole('button', { name: /新建计划/ }))
    await browser.type(screen.getByLabelText('计划名称'), '部署回归')
    await chooseSelect(browser, '执行目标', '测试套件')
    await chooseSelect(browser, '测试套件', `${testSuite.name} · v${testSuite.current_version}`)
    await chooseSelect(browser, '调度方式', '固定间隔')
    await browser.type(screen.getByLabelText('定时间隔（分钟）'), '30')
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    expect(await screen.findByText(plan.webhook_secret)).toBeInTheDocument()
    expect(requests.created).toBe(1)
    await browser.keyboard('{Escape}')

    await browser.click(screen.getByRole('button', { name: /新建计划/ }))
    await browser.type(screen.getByLabelText('计划名称'), 'Cron 部署回归')
    await chooseSelect(browser, '执行目标', '测试套件')
    await chooseSelect(browser, '测试套件', `${testSuite.name} · v${testSuite.current_version}`)
    await chooseSelect(browser, '调度方式', 'Cron')
    await browser.type(screen.getByLabelText('Cron 表达式'), '0 9 * * 1-5')
    await browser.clear(screen.getByLabelText('队列优先级（0 最低，9 最高）'))
    await browser.type(screen.getByLabelText('队列优先级（0 最低，9 最高）'), '9')
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    await waitFor(() => expect(requests.created).toBe(2))
    await browser.keyboard('{Escape}')

    await browser.click(screen.getAllByRole('button', { name: /运行/ })[0])
    await waitFor(() => expect(requests.run).toBe(1))
    await browser.click(screen.getByRole('button', { name: /取消/ }))
    await waitFor(() => expect(requests.cancelled).toBe(1))
  })
  it('edits scheduling without changing frozen targets, stops future scheduling, and revokes tokens', async () => {
    let current = { ...plan }
    let revoked = false
    const patches: unknown[] = []
    installMaintenanceHandlers(
      () => current,
      () => revoked,
    )
    server.use(
      http.patch(`/api/v1/projects/${project.id}/test-plans/${plan.id}`, async ({ request }) => {
        const payload = (await request.json()) as Record<string, unknown>
        expect(payload).not.toHaveProperty('items')
        patches.push(payload)
        current = { ...current, ...payload }
        return HttpResponse.json(current)
      }),
      http.delete(`/api/v1/projects/${project.id}/service-tokens/${serviceToken.id}`, () => {
        revoked = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    renderPage()
    const browser = userEvent.setup()
    await screen.findByText(plan.name)
    await waitFor(() => expect(screen.getByRole('button', { name: '编辑' })).toBeEnabled())
    await browser.click(screen.getByRole('button', { name: '编辑' }))
    const dialog = within(
      (await screen.findByText('编辑测试计划')).closest<HTMLElement>('.ant-modal')!,
    )
    await browser.clear(dialog.getByLabelText('计划名称'))
    await browser.type(dialog.getByLabelText('计划名称'), '工作日回归')
    await browser.click(dialog.getByLabelText('调度方式'))
    await browser.click(
      await screen.findByText('手动', { selector: '.ant-select-item-option-content' }),
    )
    await browser.click(dialog.getByRole('button', { name: /保\s*存/ }))
    await screen.findByText('工作日回归')
    expect(patches[0]).toMatchObject({ schedule_interval_seconds: null, schedule_cron: null })
    await browser.click(screen.getByRole('switch', { name: '启停计划 工作日回归' }))
    await waitFor(() => expect(patches.at(-1)).toEqual({ enabled: false }))
    await waitFor(() =>
      expect(screen.getByRole('switch', { name: '启停计划 工作日回归' })).not.toBeChecked(),
    )
    await browser.click(screen.getByRole('button', { name: /撤\s*销/ }))
    await browser.click(screen.getAllByRole('button', { name: /撤\s*销/ }).at(-1)!)
    await waitFor(() => expect(revoked).toBe(true))
    expect(await screen.findByText('已撤销')).toBeVisible()
  })

  it('links each run item to its actual execution and preserves missing reports', async () => {
    installMaintenanceHandlers(
      () => plan,
      () => false,
    )
    const executionId = 'actual-frozen-execution'
    const item = {
      id: 'run-item',
      target_type: 'workflow',
      target_id: workflow.id,
      target_version: 1,
      workflow_id: workflow.id,
      workflow_version: 1,
      environment_id: environment.id,
      status: 'failed',
      attempts: 2,
      max_retries: 1,
      workflow_execution_id: executionId,
      error_message: '断言未通过',
    }
    server.use(
      http.get(`/api/v1/projects/${project.id}/test-plan-runs/${queuedRun.id}`, () =>
        HttpResponse.json({
          run: { ...queuedRun, status: 'failed' },
          items: [item, { ...item, id: 'not-started', workflow_execution_id: null }],
        }),
      ),
    )
    renderPage()
    const browser = userEvent.setup()
    await browser.click(await screen.findByRole('button', { name: '详情' }))
    const dialog = within(
      (await screen.findByText('计划运行详情')).closest<HTMLElement>('.ant-modal')!,
    )
    expect(await dialog.findByRole('link', { name: '查看报告' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/reports?execution=${executionId}`,
    )
    expect(dialog.getByRole('link', { name: '定位编排' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/workflows?focus=${workflow.id}&execution=${executionId}`,
    )
    expect(dialog.getByText('尚无执行报告')).toBeInTheDocument()
    expect(dialog.getAllByText('2 次尝试 · 最多 1 次重试')).toHaveLength(2)
  })
})

function renderPage(role: 'owner' | 'viewer' = 'owner') {
  server.use(
    http.get(`/api/v1/projects/${project.id}/permissions`, () =>
      HttpResponse.json({
        effective_role: role,
        capabilities:
          role === 'owner'
            ? ['read', 'edit', 'execute', 'manage_members', 'manage_security']
            : ['read'],
        matrix: {},
      }),
    ),
  )
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
  await browser.click(screen.getByRole('combobox', { name: label }))
  await browser.click(
    await screen.findByText(option, { selector: '.ant-select-item-option-content' }),
  )
}

function withoutRawToken(created: CreatedServiceToken): ServiceToken {
  const { token, ...stored } = created
  void token
  return stored
}

function installMaintenanceHandlers(planValue: () => CreatedTestPlan, revoked: () => boolean) {
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 20 }),
    ),
    http.get(`/api/v1/projects/${project.id}/workflows`, () =>
      HttpResponse.json({ items: [workflow], total: 1, page: 1, page_size: 20 }),
    ),
    http.get(`/api/v1/projects/${project.id}/environments`, () => HttpResponse.json([environment])),
    http.get(`/api/v1/projects/${project.id}/test-cases`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
    ),
    http.get(`/api/v1/projects/${project.id}/test-suites`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
    ),
    http.get(`/api/v1/projects/${project.id}/test-plans`, () =>
      HttpResponse.json({ items: [planValue()], total: 1, page: 1, page_size: 20 }),
    ),
    http.get(`/api/v1/projects/${project.id}/test-plan-runs`, () =>
      HttpResponse.json({ items: [queuedRun], total: 1, page: 1, page_size: 20 }),
    ),
    http.get(`/api/v1/projects/${project.id}/service-tokens`, () =>
      HttpResponse.json([
        { ...withoutRawToken(serviceToken), revoked_at: revoked() ? '2026-10-11T00:00:00Z' : null },
      ]),
    ),
  )
}
