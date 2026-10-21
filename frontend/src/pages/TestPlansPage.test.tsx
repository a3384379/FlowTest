import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp, ConfigProvider } from 'antd'
import { useLocation, useNavigate } from 'react-router-dom'
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
    const view = renderPage('viewer')
    const workspace = within(view.container)
    const planName = await workspace.findByText('每日回归')
    expect(planName).toBeVisible()
    const heading = within(view.container.querySelector('.page-heading')! as HTMLElement)
    const planRow = within(planName.closest('tr')!)
    const queue = within(workspace.getByText('运行队列').closest('.ant-card')! as HTMLElement)
    const browser = userEvent.setup()
    const buttons = [
      heading.getByRole('button', { name: /新建计划/ }),
      heading.getByRole('button', { name: /生成 CI Token/ }),
      planRow.getByRole('button', { name: /运行/ }),
      await queue.findByRole('button', { name: /取消/ }),
    ]
    for (const button of buttons) {
      expect(button).toBeDisabled()
      await browser.click(button)
    }
    expect(screen.queryByText('CI 凭据')).not.toBeInTheDocument()
    expect(forbiddenRequests).toBe(0)
  })

  it('shows interval, cron and manual schedules and reveals a new CI credential once', async () => {
    installMaintenanceHandlers(
      () => plan,
      () => false,
    )
    let tokenRequests = 0
    server.use(
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
            { ...plan, id: `${plan.id}-manual`, name: '手动回归', schedule_interval_seconds: null },
          ],
          total: 3,
          page: 1,
          page_size: 100,
        }),
      ),
      http.post(`/api/v1/projects/${project.id}/service-tokens`, () => {
        tokenRequests++
        return HttpResponse.json(serviceToken, { status: 201 })
      }),
    )
    const view = renderPage()
    const workspace = within(view.container)
    expect(await workspace.findByRole('heading', { name: '任务执行' })).toBeVisible()
    expect(await workspace.findByText('每日回归')).toBeVisible()
    expect(workspace.getByText('每 60 分钟')).toBeVisible()
    expect(workspace.getByText('0 9 * * 1-5 · Asia/Shanghai')).toBeVisible()
    expect(workspace.getByText('手动')).toBeVisible()
    expect(workspace.getByText('尚未使用')).toBeVisible()
    expect(screen.queryByText(serviceToken.token)).not.toBeInTheDocument()
    const browser = userEvent.setup()
    const heading = within(view.container.querySelector('.page-heading')! as HTMLElement)
    await browser.click(heading.getByRole('button', { name: /生成 CI Token/ }))
    expect(await screen.findByText(serviceToken.token)).toBeInTheDocument()
    expect(tokenRequests).toBe(1)
    await closeRevealedSecret(browser, serviceToken.token)
  })

  it.each(['固定间隔', 'Cron'] as const)(
    'creates a version-pinned suite plan with %s scheduling',
    async (schedule) => {
      installMaintenanceHandlers(
        () => plan,
        () => false,
      )
      let created = 0
      server.use(
        http.get(`/api/v1/projects/${project.id}/test-cases`, () =>
          HttpResponse.json({ items: [testCase], total: 1, page: 1, page_size: 20 }),
        ),
        http.get(`/api/v1/projects/${project.id}/test-suites`, () =>
          HttpResponse.json({ items: [testSuite], total: 1, page: 1, page_size: 20 }),
        ),
        http.post(`/api/v1/projects/${project.id}/test-plans`, async ({ request }) => {
          const body: unknown = await request.json()
          expect(body).toMatchObject({
            schedule_interval_seconds: schedule === '固定间隔' ? 1800 : null,
            schedule_cron: schedule === 'Cron' ? '0 9 * * 1-5' : null,
            queue_priority: schedule === 'Cron' ? 9 : 5,
            items: [
              expect.objectContaining({
                target_type: 'suite',
                target_id: testSuite.id,
                target_version: 1,
                environment_id: null,
              }),
            ],
          })
          if (schedule === 'Cron')
            expect(body).toMatchObject({ schedule_timezone: 'Asia/Shanghai' })
          created++
          return HttpResponse.json(plan, { status: 201 })
        }),
      )
      const view = renderPage()
      const workspace = within(view.container)
      await workspace.findByText('每日回归')
      const browser = userEvent.setup()
      const heading = within(view.container.querySelector('.page-heading')! as HTMLElement)
      await waitFor(() => expect(heading.getByRole('button', { name: /新建计划/ })).toBeEnabled())
      await browser.click(heading.getByRole('button', { name: /新建计划/ }))
      const title = await screen.findByText('新建测试计划')
      await waitFor(() => expect(title).toBeVisible())
      const dialog = within(title.closest('.ant-modal')! as HTMLElement)
      await browser.type(
        dialog.getByLabelText('计划名称'),
        schedule === 'Cron' ? 'Cron 部署回归' : '部署回归',
      )
      await chooseScopedSelect(browser, dialog, '执行目标', '测试套件')
      await chooseScopedSelect(
        browser,
        dialog,
        '测试套件',
        `${testSuite.name} · v${testSuite.current_version}`,
      )
      await chooseScopedSelect(browser, dialog, '调度方式', schedule)
      if (schedule === '固定间隔')
        await browser.type(dialog.getByLabelText('定时间隔（分钟）'), '30')
      else {
        await browser.type(dialog.getByLabelText('Cron 表达式'), '0 9 * * 1-5')
        await browser.clear(dialog.getByLabelText('队列优先级（0 最低，9 最高）'))
        await browser.type(dialog.getByLabelText('队列优先级（0 最低，9 最高）'), '9')
      }
      await browser.click(dialog.getByRole('button', { name: '创建计划' }))
      expect(await screen.findByText(plan.webhook_secret)).toBeInTheDocument()
      expect(created).toBe(1)
      await closeRevealedSecret(browser, plan.webhook_secret)
    },
  )

  it('queues the selected plan, opens the exact run and submits cancellation', async () => {
    installMaintenanceHandlers(
      () => plan,
      () => false,
    )
    const requests = { run: 0, cancelled: 0 }
    server.use(
      http.get(`/api/v1/projects/${project.id}/test-plans/${plan.id}`, () =>
        HttpResponse.json(plan),
      ),
      http.get(`/api/v1/projects/${project.id}/test-plan-runs/${queuedRun.id}`, () =>
        HttpResponse.json({ run: queuedRun, items: [] }),
      ),
      http.post(`/api/v1/projects/${project.id}/test-plans/${plan.id}/runs`, () => {
        requests.run++
        return HttpResponse.json(queuedRun, { status: 202 })
      }),
      http.post(`/api/v1/projects/${project.id}/test-plan-runs/${queuedRun.id}/cancel`, () => {
        requests.cancelled++
        return HttpResponse.json({ ...queuedRun, status: 'cancelled' })
      }),
    )
    const view = renderPage()
    const workspace = within(view.container)
    const row = within((await workspace.findByText('每日回归')).closest('tr')!)
    const browser = userEvent.setup()
    await browser.click(row.getByRole('button', { name: /运行/ }))
    await waitFor(() => expect(requests.run).toBe(1))
    await screen.findByText('计划运行详情')
    await waitFor(() =>
      expect(screen.getByTestId('task-route')).toHaveTextContent(`run=${queuedRun.id}`),
    )
    const details = screen.getByText('计划运行详情').closest('.ant-modal')! as HTMLElement
    await waitFor(() => expect(details).toBeVisible())
    await browser.click(within(details).getByRole('button', { name: 'Close' }))
    await waitFor(() => expect(screen.getByTestId('task-route')).not.toHaveTextContent('run='))
    const queue = within(workspace.getByText('运行队列').closest('.ant-card')! as HTMLElement)
    await browser.click(queue.getByRole('button', { name: /取消/ }))
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

  it('keeps three ordered and version-pinned targets intact through a failed creation and retry', async () => {
    installMaintenanceHandlers(
      () => plan,
      () => false,
    )
    const payloads: Array<{ items: Array<Record<string, unknown>>; name: string }> = []
    server.use(
      http.get(`/api/v1/projects/${project.id}/test-cases`, () =>
        HttpResponse.json({ items: [testCase], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/test-suites`, () =>
        HttpResponse.json({ items: [testSuite], total: 1, page: 1, page_size: 100 }),
      ),
      http.post(`/api/v1/projects/${project.id}/test-plans`, async ({ request }) => {
        const payload = (await request.json()) as (typeof payloads)[number]
        payloads.push(payload)
        return payloads.length === 1
          ? HttpResponse.json(
              {
                error: {
                  code: 'UNAVAILABLE',
                  message: '合成创建暂不可用',
                  trace_id: 'task-create-failure',
                },
              },
              { status: 503 },
            )
          : HttpResponse.json(plan, { status: 201 })
      }),
    )
    renderPage()
    const browser = userEvent.setup()
    const create = await screen.findByRole('button', { name: /新建计划/ })
    await waitFor(() => expect(create).toBeEnabled())
    await browser.click(create)
    const dialog = within(
      (await screen.findByText('新建测试计划', { exact: true })).closest<HTMLElement>(
        '.ant-modal',
      )!,
    )
    await browser.type(dialog.getByLabelText('计划名称'), '三个固定执行目标')
    const first = within(screen.getByLabelText('执行项 1'))
    await chooseScopedSelect(
      browser,
      first,
      '工作流',
      `${workflow.name} · v${workflow.current_version}`,
    )
    await chooseScopedSelect(browser, first, '环境', environment.name)
    await browser.clear(first.getByLabelText('失败重试次数'))
    await browser.type(first.getByLabelText('失败重试次数'), '2')
    await browser.click(dialog.getByText('添加执行项', { exact: true }))
    const second = within(screen.getByLabelText('执行项 2'))
    await chooseScopedSelect(browser, second, '执行目标', '测试用例')
    await chooseScopedSelect(browser, second, '测试用例', `${testCase.name} · v2`)
    await browser.click(dialog.getByText('添加执行项', { exact: true }))
    const third = within(screen.getByLabelText('执行项 3'))
    await chooseScopedSelect(browser, third, '执行目标', '测试套件')
    await chooseScopedSelect(browser, third, '测试套件', `${testSuite.name} · v1`)
    await browser.click(dialog.getByLabelText('上移执行项 3'))
    expect(within(screen.getByLabelText('执行项 2')).getByLabelText('固定发布版本')).toHaveValue(
      '1',
    )
    expect(within(screen.getByLabelText('执行项 3')).getByLabelText('固定发布版本')).toHaveValue(
      '2',
    )
    await browser.click(dialog.getByText('创建计划', { exact: true }))
    expect(await dialog.findByText('task-create-failure')).toBeVisible()
    expect(dialog.getByLabelText('计划名称')).toHaveValue('三个固定执行目标')
    expect(dialog.getAllByText('流程版本及环境继承所选用例或套件的固定发布配置')).toHaveLength(2)
    expect(payloads[0].items).toEqual([
      {
        target_type: 'workflow',
        target_id: workflow.id,
        target_version: workflow.current_version,
        environment_id: environment.id,
        max_retries: 2,
      },
      {
        target_type: 'suite',
        target_id: testSuite.id,
        target_version: 1,
        environment_id: null,
        max_retries: 0,
      },
      {
        target_type: 'case',
        target_id: testCase.id,
        target_version: 2,
        environment_id: null,
        max_retries: 0,
      },
    ])
    await browser.click(dialog.getByText('创建计划', { exact: true }))
    await screen.findByText(plan.webhook_secret)
    expect(payloads).toHaveLength(2)
    expect(payloads[1]).toEqual(payloads[0])
  })

  it('restores an off-page plan and cancelled run from the URL and browser history with no writes', async () => {
    installMaintenanceHandlers(
      () => plan,
      () => false,
    )
    const offPageId = '00000000-0000-4000-8000-000000003121'
    const runId = '00000000-0000-4000-8000-000000003122'
    let writes = 0
    const requests: string[] = []
    server.use(
      http.get(`/api/v1/projects/${project.id}/test-plans/${offPageId}`, () => {
        requests.push(offPageId)
        return HttpResponse.json({ ...plan, id: offPageId, name: '第21个计划' })
      }),
      http.get(`/api/v1/projects/${project.id}/test-plan-runs/${runId}`, () => {
        requests.push(runId)
        return HttpResponse.json({
          run: { ...queuedRun, id: runId, test_plan_id: offPageId, status: 'cancelled' },
          items: [],
        })
      }),
      http.post(`/api/v1/projects/${project.id}/*`, () => {
        writes++
        return new HttpResponse(null, { status: 500 })
      }),
    )
    renderPage('viewer', `/projects/${project.id}/tasks?focus=${offPageId}&run=${runId}`)
    const modal = within(
      (await screen.findByText('计划运行详情')).closest<HTMLElement>('.ant-modal')!,
    )
    await waitFor(() => expect(modal.getByText('cancelled')).toBeVisible())
    expect(modal.getByText(runId)).toBeVisible()
    await userEvent.keyboard('{Escape}')
    expect(await screen.findByText('第21个计划')).toBeVisible()
    expect(screen.getByTestId('task-route')).toHaveTextContent(`focus=${offPageId}`)
    expect(screen.getByTestId('task-route')).not.toHaveTextContent('run=')
    await userEvent.click(screen.getByText('任务历史后退', { exact: true }))
    await screen.findByText('计划运行详情')
    expect(screen.getByTestId('task-route')).toHaveTextContent(`run=${runId}`)
    expect(requests).toContain(offPageId)
    expect(requests).toContain(runId)
    expect(writes).toBe(0)
  })

  it.each([404, 503])(
    'retains a failed focused plan identity after %s and retries that exact plan',
    async (status) => {
      installMaintenanceHandlers(
        () => plan,
        () => false,
      )
      const id = '00000000-0000-4000-8000-000000003123'
      let reads = 0,
        writes = 0
      server.use(
        http.get(`/api/v1/projects/${project.id}/test-plans/${id}`, () => {
          reads++
          return reads === 1
            ? HttpResponse.json(
                {
                  error: {
                    code: 'NOT_AVAILABLE',
                    message: '合成计划暂不可读',
                    trace_id: `plan-read-${status}`,
                  },
                },
                { status },
              )
            : HttpResponse.json({ ...plan, id, name: '精确重试计划' })
        }),
        http.post(`/api/v1/projects/${project.id}/*`, () => {
          writes++
          return new HttpResponse(null, { status: 500 })
        }),
      )
      renderPage('viewer', `/projects/${project.id}/tasks?focus=${id}`)
      const card = within(
        (await screen.findByText('选中计划详情', { exact: true })).closest<HTMLElement>(
          '.ant-card',
        )!,
      )
      await waitFor(() => expect(card.getByText(`Trace ID: plan-read-${status}`)).toBeVisible())
      expect(card.queryByText(plan.name, { exact: true })).not.toBeInTheDocument()
      expect(screen.getByTestId('task-route')).toHaveTextContent(`focus=${id}`)
      await userEvent.click(card.getByLabelText('重试'))
      await waitFor(() => expect(card.getByText('精确重试计划', { exact: true })).toBeVisible())
      expect(reads).toBe(2)
      expect(writes).toBe(0)
    },
  )
})

function renderPage(role: 'owner' | 'viewer' = 'owner', initialEntry?: string) {
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
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <ProjectTestProvider section="tasks" initialEntry={initialEntry}>
            <TestPlansPage />
            <TaskRouteProbe />
          </ProjectTestProvider>
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
}

function TaskRouteProbe() {
  const location = useLocation()
  const navigate = useNavigate()
  return (
    <>
      <span data-testid="task-route">
        {location.pathname}
        {location.search}
      </span>
      <button onClick={() => navigate(-1)}>任务历史后退</button>
    </>
  )
}

async function chooseScopedSelect(
  browser: ReturnType<typeof userEvent.setup>,
  scope: ReturnType<typeof within>,
  label: string,
  option: string,
) {
  await browser.click(scope.getByLabelText(label))
  const popup = document.querySelector<HTMLElement>(
    '.ant-select-dropdown:not(.ant-select-dropdown-hidden)',
  )!
  await browser.click(
    await within(popup).findByText(option, { selector: '.ant-select-item-option-content' }),
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

async function closeRevealedSecret(browser: ReturnType<typeof userEvent.setup>, value: string) {
  const content = await screen.findByText(value)
  await waitFor(() => expect(content).toBeVisible())
  const dialog = within(content.closest('.ant-modal')! as HTMLElement)
  await browser.click(dialog.getByRole('button', { name: 'Close' }))
  await waitFor(() => {
    const remaining = screen.queryByText(value)
    if (remaining) expect(remaining).not.toBeVisible()
    else expect(remaining).toBeNull()
  })
}
