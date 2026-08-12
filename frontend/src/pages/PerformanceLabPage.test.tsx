import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import type {
  PerformanceRun,
  PerformanceScenario,
} from '../features/performance/performance-service'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { project, user } from '../test/fixtures'
import { server } from '../test/server'
import PerformanceLabPage from './PerformanceLabPage'

const scenario: PerformanceScenario = {
  id: '00000000-0000-4000-8000-000000000901',
  project_id: project.id,
  name: '订单查询性能',
  description: 'S25',
  version: 1,
  status: 'published',
  target_type: 'rest',
  definition: {
    executor: 'constant_vus',
    steps: [
      {
        name: '查询订单',
        method: 'GET',
        url: 'https://api.example.com/orders/1',
        headers: {},
        body: null,
        expected_statuses: [200],
        pause_seconds: 0,
      },
    ],
    thresholds: [
      {
        metric: 'http_req_duration',
        aggregation: 'p(95)',
        operator: '<',
        value: 500,
        abort_on_fail: false,
        delay_abort_seconds: 0,
      },
    ],
    vus: 5,
    duration_seconds: 30,
    start_vus: null,
    stages: [],
    graceful_stop_seconds: 30,
  },
  compiled_sha256: 'a'.repeat(64),
  published_at: '2026-08-12T05:00:00Z',
  created_by_id: user.id,
  created_at: '2026-08-12T05:00:00Z',
  updated_at: '2026-08-12T05:00:00Z',
}

const run: PerformanceRun = {
  id: '00000000-0000-4000-8000-000000000902',
  project_id: project.id,
  scenario_id: scenario.id,
  scenario_version: 1,
  status: 'passed',
  definition_snapshot: scenario.definition,
  compiled_sha256: scenario.compiled_sha256,
  summary: {
    http_req_duration_p95_ms: 128.25,
    http_reqs_rate: 42.5,
    http_reqs_count: 1275,
    http_req_failed_rate: 0,
    baseline_p95_ms: 120,
    p95_regression_percent: 6.88,
  },
  threshold_results: [{ metric: 'http_req_duration', expression: 'p(95)<500', passed: true }],
  baseline_run_id: '00000000-0000-4000-8000-000000000903',
  raw_metrics_artifact_id: '00000000-0000-4000-8000-000000000904',
  error_code: null,
  error_message: null,
  started_at: '2026-08-12T05:01:00Z',
  completed_at: '2026-08-12T05:01:30Z',
  created_by_id: user.id,
  created_at: '2026-08-12T05:01:00Z',
  updated_at: '2026-08-12T05:01:30Z',
  gate_evaluations: [
    {
      id: '00000000-0000-4000-8000-000000000905',
      quality_gate_id: '00000000-0000-4000-8000-000000000906',
      performance_run_id: '00000000-0000-4000-8000-000000000902',
      status: 'passed',
      metrics: { http_req_duration_p95_ms: 128.25 },
      violations: [],
      evaluated_at: '2026-08-12T05:01:30Z',
    },
  ],
}

describe('PerformanceLabPage', () => {
  it('renders baseline, thresholds, artifacts and starts an isolated run', async () => {
    let started = 0
    installHandlers()
    server.use(
      http.post(`/api/v1/projects/${project.id}/performance-scenarios/${scenario.id}/runs`, () => {
        started += 1
        return HttpResponse.json({ ...run, status: 'queued' }, { status: 202 })
      }),
    )
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByRole('heading', { name: '性能实验室' })).toBeVisible()
    expect(await screen.findByText('订单查询性能')).toBeVisible()
    expect(screen.getByText('5 VU / 30s')).toBeVisible()
    expect(screen.getByText('128.25 ms')).toBeVisible()
    expect(screen.getByText('+6.88%')).toBeVisible()
    expect(screen.getAllByText('通过', { selector: '.ant-tag' })).toHaveLength(2)

    await browser.click(screen.getByRole('button', { name: /运行/ }))
    await waitFor(() => expect(started).toBe(1))
    await browser.click(screen.getByRole('button', { name: 'Expand row' }))
    expect(await screen.findByText('http_req_duration p(95)<500')).toBeVisible()
    expect(screen.getByText('原始指标已保存至 MinIO')).toBeVisible()
  })

  it('creates a ramping scenario from structured fields without source code', async () => {
    let submitted: Record<string, unknown> | null = null
    installHandlers({ scenarios: [] })
    server.use(
      http.post(`/api/v1/projects/${project.id}/performance-scenarios`, async ({ request }) => {
        submitted = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...scenario, status: 'draft' }, { status: 201 })
      }),
    )
    renderPage()
    const browser = userEvent.setup()

    await screen.findByText('暂无性能场景')
    await browser.click(screen.getByRole('button', { name: /新建性能场景/ }))
    await browser.type(screen.getByLabelText('场景名称'), '阶梯压力')
    await browser.type(screen.getByLabelText('目标 URL'), 'http://mock-target:8080/orders')
    await browser.click(screen.getByText('阶梯升压'))
    await browser.clear(screen.getByLabelText('目标 VU'))
    await browser.type(screen.getByLabelText('目标 VU'), '30')
    await browser.click(screen.getByRole('button', { name: 'OK' }))

    await waitFor(() => expect(submitted).not.toBeNull())
    expect(submitted).not.toHaveProperty('script')
    const definition = (submitted as unknown as { definition: Record<string, unknown> }).definition
    expect(definition).toMatchObject({
      executor: 'ramping_vus',
      vus: null,
      start_vus: 0,
      stages: [{ duration_seconds: 60, target_vus: 30 }],
    })
    expect(definition.thresholds).toHaveLength(2)
  })

  it('publishes drafts and keeps actions stable when the backend rejects a run', async () => {
    let published = 0
    installHandlers({ scenarios: [{ ...scenario, status: 'draft' }] })
    server.use(
      http.post(
        `/api/v1/projects/${project.id}/performance-scenarios/${scenario.id}/publish`,
        () => {
          published += 1
          return HttpResponse.json(scenario)
        },
      ),
      http.post(`/api/v1/projects/${project.id}/performance-scenarios/${scenario.id}/runs`, () =>
        HttpResponse.json(
          { error: { code: 'PERFORMANCE_QUEUE_UNAVAILABLE', message: '性能队列不可用' } },
          { status: 503 },
        ),
      ),
    )
    renderPage()
    const browser = userEvent.setup()
    await screen.findByText('订单查询性能')
    await browser.click(screen.getByRole('button', { name: '发布' }))
    await waitFor(() => expect(published).toBe(1))
  })

  it('explains an unsuccessful run without baseline, gate, metrics, or artifact', async () => {
    const ramping = {
      ...scenario,
      definition: {
        ...scenario.definition,
        executor: 'ramping_vus' as const,
        vus: null,
        duration_seconds: null,
        start_vus: 0,
        stages: [{ duration_seconds: 60, target_vus: 20 }],
      },
    }
    const failed: PerformanceRun = {
      ...run,
      status: 'failed',
      definition_snapshot: ramping.definition,
      summary: {},
      threshold_results: [],
      baseline_run_id: null,
      raw_metrics_artifact_id: null,
      gate_evaluations: [],
      error_code: 'K6_EXECUTION_FAILED',
      error_message: '性能 Runner 执行失败',
    }
    installHandlers({ scenarios: [ramping], runs: [failed] })
    renderPage()

    expect(await screen.findByText('0 → 20 VU / 60s')).toBeVisible()
    expect(screen.getAllByText('—')).toHaveLength(2)
    expect(screen.getByText('无基线')).toBeVisible()
    expect(screen.getByText('未配置')).toBeVisible()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Expand row' }))
    expect(await screen.findByText('性能 Runner 执行失败')).toBeVisible()
    expect(screen.queryByText('原始指标已保存至 MinIO')).not.toBeInTheDocument()
  })

  it('rejects non-HTTP targets before creating a scenario', async () => {
    let submitted = false
    installHandlers({ scenarios: [], runs: [] })
    server.use(
      http.post(`/api/v1/projects/${project.id}/performance-scenarios`, () => {
        submitted = true
        return HttpResponse.json(scenario, { status: 201 })
      }),
    )
    renderPage()
    const browser = userEvent.setup()

    await browser.click(await screen.findByRole('button', { name: /新建性能场景/ }))
    await browser.type(screen.getByLabelText('场景名称'), '非法协议')
    await browser.type(screen.getByLabelText('目标 URL'), 'file:///etc/passwd')
    await browser.click(screen.getByRole('button', { name: 'OK' }))

    expect(await screen.findByText('请输入有效的 HTTP 或 HTTPS URL')).toBeInTheDocument()
    expect(submitted).toBe(false)
  })
})

function installHandlers({
  scenarios = [scenario],
  runs = [run],
}: { scenarios?: PerformanceScenario[]; runs?: PerformanceRun[] } = {}) {
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
    ),
    http.get(`/api/v1/projects/${project.id}/performance-scenarios`, () =>
      HttpResponse.json({ items: scenarios, total: scenarios.length, page: 1, page_size: 100 }),
    ),
    http.get(`/api/v1/projects/${project.id}/performance-runs`, () =>
      HttpResponse.json({ items: runs, total: runs.length, page: 1, page_size: 50 }),
    ),
  )
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <ProjectTestProvider section="performance">
          <PerformanceLabPage />
        </ProjectTestProvider>
      </QueryClientProvider>
    </AntdApp>,
  )
}
