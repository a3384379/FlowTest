import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useLocation } from 'react-router-dom'

import type {
  FlakyRecord,
  QualityGate,
  ReleaseRiskDetail,
} from '../features/quality/quality-service'
import type { TestPlanRun } from '../lib/api'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { project, user, workflowVersion } from '../test/fixtures'
import { server } from '../test/server'
import QualityCenterPage from './QualityCenterPage'

const gate: QualityGate = {
  id: '00000000-0000-4000-8000-000000000101',
  project_id: project.id,
  name: '主分支门禁',
  enabled: true,
  min_pass_rate: 95,
  max_failed: 0,
  max_flaky: 0,
  max_duration_regression_percent: 20,
  require_no_breaking_changes: true,
  created_by_id: user.id,
  created_at: '2026-08-11T01:00:00Z',
  updated_at: '2026-08-11T01:00:00Z',
}

const flaky: FlakyRecord = {
  id: '00000000-0000-4000-8000-000000000102',
  project_id: project.id,
  target_type: 'workflow',
  target_id: '00000000-0000-4000-8000-000000000103',
  target_version: 2,
  total_runs: 8,
  passed_runs: 6,
  failed_runs: 2,
  transitions: 3,
  flaky_score: 42.5,
  quarantined: false,
  last_status: 'passed',
  last_run_id: '00000000-0000-4000-8000-000000000104',
  last_run_at: '2026-08-11T01:00:00Z',
  updated_at: '2026-08-11T01:00:00Z',
}

const run: TestPlanRun = {
  id: '00000000-0000-4000-8000-000000000104',
  project_id: project.id,
  test_plan_id: '00000000-0000-4000-8000-000000000105',
  requested_by_id: user.id,
  status: 'passed',
  trigger_type: 'ci',
  queue_priority: 8,
  queue_name: 'general',
  baseline_run_id: '00000000-0000-4000-8000-000000000106',
  quality_summary: { pass_rate: 96, failed: 1, flaky: 1 },
  cancel_requested_at: null,
  started_at: '2026-08-11T01:00:00Z',
  completed_at: '2026-08-11T01:01:00Z',
  error_message: null,
  created_at: '2026-08-11T01:00:00Z',
}

const risk: ReleaseRiskDetail = {
  id: '00000000-0000-4000-8000-000000000120',
  project_id: project.id,
  impact_run_id: '00000000-0000-4000-8000-000000000121',
  title: '候选版本风险',
  algorithm_version: 'release_risk_v1',
  window_days: 30,
  window_started_at: '2026-07-12T01:00:00Z',
  window_ended_at: '2026-08-11T01:00:00Z',
  baseline_started_at: '2026-06-12T01:00:00Z',
  baseline_ended_at: '2026-07-12T01:00:00Z',
  score: 42,
  quality_score: 58,
  risk_level: 'medium',
  factors: [{ code: 'coverage_gap', label: '覆盖缺口', score: 10, max_score: 25, value: 60 }],
  evidence_snapshot: { impact: { coverage_gap_count: 3 } },
  quality_trend: [],
  recommended_tests: [
    {
      target_type: 'workflow',
      target_id: '00000000-0000-4000-8000-000000000122',
      name: '支付流程',
      version: 2,
      priority: 'high',
      reasons: ['显式 Mapping'],
      change_keys: ['change-1'],
    },
  ],
  failure_clusters: [
    {
      id: '00000000-0000-4000-8000-000000000123',
      release_risk_id: '00000000-0000-4000-8000-000000000120',
      fingerprint: 'b'.repeat(64),
      title: 'HTTP_TIMEOUT · api',
      failure_category: 'timeout',
      error_code: 'HTTP_TIMEOUT',
      node_type: 'api',
      occurrence_count: 4,
      baseline_count: 1,
      affected_workflow_ids: ['00000000-0000-4000-8000-000000000122'],
      affected_workflow_names: ['支付流程'],
      sample_execution_ids: ['00000000-0000-4000-8000-000000000124'],
      confidence: 0.94,
      regression_percent: 300,
      recommendation: '检查目标服务延迟、性能基线与 Runner 网络区。',
      created_at: '2026-08-11T01:00:00Z',
    },
  ],
  fingerprint: 'a'.repeat(64),
  created_by_id: user.id,
  created_at: '2026-08-11T01:00:00Z',
}

describe('QualityCenterPage', () => {
  beforeEach(() => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/quality-gates`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${project.id}/flaky-tests`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/test-plan-runs`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/release-risks`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/impact/runs`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
    )
  })

  it.each([true, false])('counts enabled gates separately from all gates: %s', async (enabled) => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/quality-gates`, () =>
        HttpResponse.json([
          { ...gate, enabled },
          { ...gate, id: 'second-gate', name: 'Second gate', enabled },
          { ...gate, id: 'disabled-gate', name: 'Disabled gate', enabled: false },
        ]),
      ),
    )
    renderPage()
    await screen.findByText('Disabled gate')
    const metric = screen.getByText('启用门禁').closest('.ant-card')!
    expect(within(metric as HTMLElement).getByText(enabled ? '2' : '0')).toBeVisible()
    expect(within(metric as HTMLElement).getByText('共 3 项门禁')).toBeVisible()
  })

  it('keeps failed gate totals unknown instead of showing zero', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/quality-gates`, () =>
        HttpResponse.json(
          { error: { code: 'UNAVAILABLE', message: '门禁读取失败', trace_id: 'gate-read-trace' } },
          { status: 503 },
        ),
      ),
    )
    renderPage()
    await screen.findByText(/门禁读取失败/)
    const metric = screen.getByText('启用门禁').closest('.ant-card')!
    expect(within(metric as HTMLElement).getByText('未提供')).toBeVisible()
    expect(within(metric as HTMLElement).queryByText('0')).not.toBeInTheDocument()
  })

  it('shows quality evidence and creates gates and quarantines flaky assets', async () => {
    let created = 0
    let quarantined = false
    const createObjectUrl = vi.fn(() => 'blob:flowtest-junit')
    const revokeObjectUrl = vi.fn()
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectUrl })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectUrl })
    server.use(
      http.get(`/api/v1/projects/${project.id}/quality-gates`, () => HttpResponse.json([gate])),
      http.get(`/api/v1/projects/${project.id}/flaky-tests`, () =>
        HttpResponse.json({
          items: [{ ...flaky, quarantined }],
          total: 1,
          page: 1,
          page_size: 100,
        }),
      ),
      http.get(`/api/v1/projects/${project.id}/test-plan-runs`, () =>
        HttpResponse.json({ items: [run], total: 1, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/test-plan-runs/${run.id}/junit.xml`, () =>
        HttpResponse.text('<testsuite tests="1"/>'),
      ),
      http.post(`/api/v1/projects/${project.id}/quality-gates`, async ({ request }) => {
        const body = (await request.json()) as { name: string; min_pass_rate: number }
        expect(body).toMatchObject({ name: '发布门禁', min_pass_rate: 100 })
        created += 1
        return HttpResponse.json(
          { ...gate, id: `${gate.id}-new`, name: body.name },
          { status: 201 },
        )
      }),
      http.put(
        `/api/v1/projects/${project.id}/flaky-tests/${flaky.id}/quarantine`,
        async ({ request }) => {
          const body = (await request.json()) as { quarantined: boolean }
          quarantined = body.quarantined
          return HttpResponse.json({ ...flaky, quarantined })
        },
      ),
    )
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByRole('heading', { name: '质量中心' })).toBeVisible()
    expect(await screen.findByText('主分支门禁')).toBeVisible()
    expect(screen.getByText('通过率 96% · 失败 1 · Flaky 1')).toBeVisible()
    expect(screen.getByText('42.5')).toBeVisible()

    await browser.click(screen.getByRole('button', { name: /JUnit/ }))
    await waitFor(() => expect(createObjectUrl).toHaveBeenCalledOnce())
    expect(revokeObjectUrl).toHaveBeenCalledWith('blob:flowtest-junit')

    await browser.click(
      screen.getByRole('switch', { name: `隔离 ${flaky.target_id}@${flaky.target_version}` }),
    )
    await waitFor(() => expect(quarantined).toBe(true))

    await browser.click(screen.getByRole('button', { name: /新建门禁/ }))
    await browser.type(screen.getByLabelText('门禁名称'), '发布门禁')
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    await waitFor(() => expect(created).toBe(1))
  })

  it('renders safe empty states before quality evidence exists', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/quality-gates`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${project.id}/flaky-tests`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/test-plan-runs`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
      ),
    )
    renderPage()

    expect(await screen.findByText('暂无质量门禁')).toBeVisible()
    expect(screen.getByText('暂无 Flaky 记录')).toBeVisible()
    expect(screen.getByText('暂无运行数据')).toBeVisible()
    expect(screen.getByText('最近通过率')).toBeVisible()
  })

  it('keeps dialogs and records stable when quality mutations fail', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/quality-gates`, () => HttpResponse.json([gate])),
      http.get(`/api/v1/projects/${project.id}/flaky-tests`, () =>
        HttpResponse.json({ items: [flaky], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/test-plan-runs`, () =>
        HttpResponse.json({ items: [run], total: 1, page: 1, page_size: 20 }),
      ),
      http.post(`/api/v1/projects/${project.id}/quality-gates`, () =>
        HttpResponse.json(
          { error: { code: 'QUALITY_GATE_REJECTED', message: '门禁配置被拒绝' } },
          { status: 422 },
        ),
      ),
      http.put(`/api/v1/projects/${project.id}/flaky-tests/${flaky.id}/quarantine`, () =>
        HttpResponse.json(
          { error: { code: 'QUARANTINE_REJECTED', message: '隔离被拒绝' } },
          { status: 409 },
        ),
      ),
      http.get(`/api/v1/projects/${project.id}/test-plan-runs/${run.id}/junit.xml`, () =>
        HttpResponse.json(
          { error: { code: 'JUNIT_UNAVAILABLE', message: 'JUnit 不可用' } },
          { status: 409 },
        ),
      ),
    )
    renderPage()
    const browser = userEvent.setup()
    await screen.findByText('主分支门禁')

    await browser.click(
      screen.getByRole('switch', { name: `隔离 ${flaky.target_id}@${flaky.target_version}` }),
    )
    expect(await screen.findByText('隔离被拒绝')).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: /JUnit/ }))
    expect(await screen.findByText(/status code 409/)).toBeInTheDocument()

    await browser.click(screen.getByRole('button', { name: /新建门禁/ }))
    await browser.type(screen.getByLabelText('门禁名称'), '被拒绝门禁')
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    expect(await screen.findByText('门禁配置被拒绝')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('shows explainable risk evidence and creates a persisted risk snapshot', async () => {
    let created = 0
    server.use(
      http.get(`/api/v1/projects/${project.id}/quality-gates`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${project.id}/flaky-tests`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/test-plan-runs`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/impact/runs`, () =>
        HttpResponse.json({
          items: [
            {
              id: risk.impact_run_id,
              project_id: project.id,
              title: '开票影响',
              source_ref: 'feature/invoice',
              status: 'completed',
              source_fingerprint: 'f'.repeat(64),
              source_summary: {},
              change_count: 2,
              summary: { coverage_percent: 75 },
              created_by_id: user.id,
              created_at: '2026-08-11T01:00:00Z',
            },
          ],
          total: 1,
          page: 1,
          page_size: 20,
        }),
      ),
      http.get(`/api/v1/projects/${project.id}/release-risks`, () =>
        HttpResponse.json({ items: [risk], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/release-risks/${risk.id}`, () =>
        HttpResponse.json(risk),
      ),
      http.post(`/api/v1/projects/${project.id}/release-risks`, async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>
        expect(body).toEqual({
          impact_run_id: risk.impact_run_id,
          title: 'RC 风险',
          window_days: 30,
        })
        created += 1
        return HttpResponse.json(risk, { status: 201 })
      }),
    )
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByText('风险因子（总分等于发布风险）')).toBeVisible()
    expect(screen.getAllByText('支付流程').length).toBeGreaterThan(0)
    expect(screen.getByText('HTTP_TIMEOUT · api')).toBeVisible()
    expect(screen.getByText('94%')).toBeVisible()

    await browser.click(screen.getByRole('button', { name: '分析发布风险' }))
    await browser.type(screen.getByLabelText('候选版本'), 'RC 风险')
    await browser.click(screen.getByLabelText('影响分析'))
    await browser.click(await screen.findByText('开票影响 · 2 项变更'))
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    await waitFor(() => expect(created).toBe(1))
  })
  it('opens a frozen risk outside the list and preserves its evidence window', async () => {
    const old = { ...risk, id: 'old-risk', score: 91, algorithm_version: 'frozen-algorithm-v1' }
    server.use(
      http.get(`/api/v1/projects/${project.id}/quality-gates`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${project.id}/flaky-tests`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
      http.get(`/api/v1/projects/${project.id}/test-plan-runs`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
      http.get(`/api/v1/projects/${project.id}/impact/runs`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
      http.get(`/api/v1/projects/${project.id}/release-risks`, () =>
        HttpResponse.json({ items: [risk], total: 1 }),
      ),
      http.get(`/api/v1/projects/${project.id}/release-risks/old-risk`, () =>
        HttpResponse.json(old),
      ),
    )
    renderPage(`/projects/${project.id}/quality?risk=old-risk`)
    expect(await screen.findByText(old.algorithm_version)).toBeVisible()
    expect(screen.getByText(`${risk.window_started_at} 至 ${risk.window_ended_at}`)).toBeVisible()
  })

  it('does not read unopened risk or impact features for a linked snapshot', async () => {
    let reads = 0
    server.use(
      http.get(`/api/v1/projects/${project.id}/quality-gates`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${project.id}/flaky-tests`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
      http.get(`/api/v1/projects/${project.id}/test-plan-runs`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
      http.get(`/api/v1/projects/${project.id}/release-risks*`, () => {
        reads += 1
        return HttpResponse.json(risk)
      }),
      http.get(`/api/v1/projects/${project.id}/impact/runs`, () => {
        reads += 1
        return HttpResponse.json({ items: [], total: 0 })
      }),
    )
    renderPage(`/projects/${project.id}/quality?risk=old-risk`, false)
    expect(await screen.findByText('发布风险分析尚未开放')).toBeVisible()
    expect(screen.getByRole('button', { name: '分析发布风险' })).toBeDisabled()
    expect(reads).toBe(0)
  })

  it('selects another risk and keeps its URL while paging, refreshing and following reports', async () => {
    const second = {
      ...risk,
      id: 'second-risk',
      title: 'Second frozen candidate',
      algorithm_version: 'selected-algorithm',
    }
    const third = { ...risk, id: 'third-risk', title: 'Third page candidate' }
    server.use(
      http.get(`/api/v1/projects/${project.id}/release-risks`, ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get('page'))
        return HttpResponse.json({
          items: page === 2 ? [third] : [risk, second],
          total: 21,
          page,
          page_size: 20,
        })
      }),
      http.get(`/api/v1/projects/${project.id}/release-risks/:id`, ({ params }) =>
        HttpResponse.json(params.id === second.id ? second : params.id === third.id ? third : risk),
      ),
    )
    const view = renderPage()
    const browser = userEvent.setup()
    await browser.click(await screen.findByRole('button', { name: `打开风险 ${second.id}` }))
    await screen.findByText(second.algorithm_version)
    const history = screen.getByText('风险快照历史').closest('.ant-card')! as HTMLElement
    await browser.click(within(history).getByTitle('2'))
    await screen.findByRole('button', { name: `打开风险 ${third.id}` })
    expect(screen.getByText(second.algorithm_version)).toBeVisible()
    expect(screen.getByRole('link', { name: '查看样本 1' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/reports?execution=${risk.failure_clusters[0].sample_execution_ids[0]}`,
    )
    const destination = screen.getByTestId('quality-location').textContent!
    expect(new URL(destination, 'http://test').searchParams.get('risk')).toBe(second.id)
    expect(new URL(destination, 'http://test').searchParams.get('risk_page')).toBe('2')
    view.unmount()
    renderPage(destination)
    expect(await screen.findByText(second.algorithm_version)).toBeVisible()
    expect(await screen.findByRole('button', { name: `打开风险 ${third.id}` })).toBeVisible()
  })

  it('opens an off-page Flaky record with its original target version and exact run links', async () => {
    let writes = 0
    let isolated = false
    server.use(
      http.get(`/api/v1/projects/${project.id}/flaky-tests`, () =>
        HttpResponse.json({
          items: [{ ...flaky, id: 'newer-record', target_version: 3 }],
          total: 101,
          page: 1,
          page_size: 20,
        }),
      ),
      http.get(`/api/v1/projects/${project.id}/flaky-tests/${flaky.id}`, () =>
        HttpResponse.json({ ...flaky, quarantined: isolated }),
      ),
      http.get(`/api/v1/projects/${project.id}/workflows/${flaky.target_id}/versions`, () =>
        HttpResponse.json([
          {
            ...workflowVersion,
            workflow_id: flaky.target_id,
            version: 2,
            fingerprint: 'original-v2',
          },
          { ...workflowVersion, workflow_id: flaky.target_id, version: 3, fingerprint: 'newer-v3' },
        ]),
      ),
      http.get(`/api/v1/projects/${project.id}/test-plan-runs`, () =>
        HttpResponse.json({ items: [run], total: 1, page: 1, page_size: 20 }),
      ),
      http.put(
        `/api/v1/projects/${project.id}/flaky-tests/:id/quarantine`,
        async ({ params, request }) => {
          expect(params.id).toBe(flaky.id)
          expect(await request.json()).toEqual({ quarantined: true })
          writes++
          isolated = true
          return HttpResponse.json({ ...flaky, quarantined: isolated })
        },
      ),
    )
    renderPage(`/projects/${project.id}/quality?record=${flaky.id}`)
    const title = await screen.findByText('Flaky 固定版本证据')
    const evidence = within(title.closest('.ant-card')! as HTMLElement)
    expect(await evidence.findByText(`${flaky.target_type}:${flaky.target_id}@2`)).toBeVisible()
    expect(await evidence.findByText('版本指纹：original-v2')).toBeVisible()
    expect(evidence.queryByText(/newer-v3/)).not.toBeInTheDocument()
    expect(evidence.getByRole('link', { name: '打开最后一次计划运行' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/tasks?run=${flaky.last_run_id}`,
    )
    expect(screen.getByRole('link', { name: run.id })).toHaveAttribute(
      'href',
      `/projects/${project.id}/tasks?run=${run.id}&focus=${run.test_plan_id}`,
    )
    expect(screen.getByRole('link', { name: '查看基线运行' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/tasks?run=${run.baseline_run_id}`,
    )
    expect(writes).toBe(0)
    await userEvent
      .setup()
      .click(evidence.getByRole('switch', { name: `隔离选中记录 ${flaky.id}` }))
    await waitFor(() =>
      expect(evidence.getByRole('switch', { name: `隔离选中记录 ${flaky.id}` })).toBeChecked(),
    )
    expect(writes).toBe(1)
    expect(evidence.getByText('版本指纹：original-v2')).toBeVisible()
  })

  it.each(['missing', 'foreign'] as const)(
    'does not replace a %s record with the first catalog item',
    async (mode) => {
      server.use(
        http.get(`/api/v1/projects/${project.id}/flaky-tests`, () =>
          HttpResponse.json({ items: [flaky], total: 1, page: 1, page_size: 20 }),
        ),
        http.get(`/api/v1/projects/${project.id}/flaky-tests/linked-record`, () =>
          mode === 'foreign'
            ? HttpResponse.json({ ...flaky, id: 'linked-record', project_id: 'foreign-project' })
            : HttpResponse.json(
                {
                  error: {
                    code: 'FLAKY_RECORD_NOT_FOUND',
                    message: '指定记录已失效',
                    trace_id: 'record-read-trace',
                  },
                },
                { status: 404 },
              ),
        ),
      )
      renderPage(`/projects/${project.id}/quality?record=linked-record`)
      const evidence = within(
        screen.getByText('Flaky 固定版本证据').closest('.ant-card')! as HTMLElement,
      )
      expect(
        await evidence.findByText(
          mode === 'foreign' ? 'Flaky 记录不属于当前项目或记录' : '指定记录已失效',
        ),
      ).toBeVisible()
      expect(evidence.queryByText('固定资产版本 v2')).not.toBeInTheDocument()
      expect(
        new URL(
          screen.getByTestId('quality-location').textContent!,
          'http://test',
        ).searchParams.get('record'),
      ).toBe('linked-record')
      if (mode === 'missing')
        expect(evidence.getByText('Trace ID: record-read-trace')).toBeVisible()
    },
  )

  it('keeps a wrong-project risk unavailable and never falls back to the first snapshot', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/release-risks`, () =>
        HttpResponse.json({ items: [risk], total: 1, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/release-risks/foreign-risk`, () =>
        HttpResponse.json({ ...risk, id: 'foreign-risk', project_id: 'foreign-project' }),
      ),
    )
    renderPage(`/projects/${project.id}/quality?risk=foreign-risk`)
    expect(await screen.findByText('风险快照不属于当前项目或记录')).toBeVisible()
    expect(screen.queryByText('风险因子（总分等于发布风险）')).not.toBeInTheDocument()
    expect(
      new URL(screen.getByTestId('quality-location').textContent!, 'http://test').searchParams.get(
        'risk',
      ),
    ).toBe('foreign-risk')
  })

  it('keeps an unavailable original asset version distinct from its newer version', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/flaky-tests/${flaky.id}`, () =>
        HttpResponse.json(flaky),
      ),
      http.get(`/api/v1/projects/${project.id}/workflows/${flaky.target_id}/versions`, () =>
        HttpResponse.json([
          { ...workflowVersion, workflow_id: flaky.target_id, version: 3, fingerprint: 'newer-v3' },
        ]),
      ),
    )
    renderPage(`/projects/${project.id}/quality?record=${flaky.id}`)
    expect(
      await screen.findByText('指定资产版本不存在或已不可访问，请核对原始记录；未替换为最新版本'),
    ).toBeVisible()
    expect(screen.queryByText('版本指纹：newer-v3')).not.toBeInTheDocument()
  })

  it.each(['openapi_contract', 'pact_contract', 'performance', 'test_case'] as const)(
    'opens the known recommended %s target using its exact reference',
    async (type) => {
      let reads = 0
      const assetId = '00000000-0000-4000-8000-000000000155'
      const selected = {
        ...risk,
        recommended_tests: [
          {
            ...risk.recommended_tests[0],
            target_type: type,
            target_id: assetId,
            version: type === 'pact_contract' ? 'consumer-v1' : 2,
          },
        ],
      }
      const path =
        type === 'openapi_contract'
          ? `contract-runs/${assetId}`
          : type === 'pact_contract'
            ? `contract-hub/pacts/${assetId}`
            : `test-cases/${assetId}/versions`
      server.use(
        http.get(`/api/v1/projects/${project.id}/release-risks`, () =>
          HttpResponse.json({ items: [selected], total: 1, page: 1, page_size: 20 }),
        ),
        http.get(`/api/v1/projects/${project.id}/release-risks/${risk.id}`, () =>
          HttpResponse.json(selected),
        ),
        http.get(`/api/v1/projects/${project.id}/${path}`, () => {
          reads++
          return HttpResponse.json(
            {
              error: {
                code: 'NOT_FOUND',
                message: '指定推荐资产不可访问',
                trace_id: 'recommended-reference-trace',
              },
            },
            { status: 404 },
          )
        }),
      )
      renderPage()
      await screen.findByText('风险因子（总分等于发布风险）')
      if (type === 'performance') {
        expect(screen.getByRole('link', { name: '查看固定性能场景' })).toHaveAttribute(
          'href',
          `/projects/${project.id}/performance?scenario=${assetId}`,
        )
        expect(reads).toBe(0)
      } else {
        expect(reads).toBe(0)
        await userEvent.setup().click(
          screen.getByRole('button', {
            name: type === 'test_case' ? '查看固定版本' : '查看固定契约',
          }),
        )
        await waitFor(() => expect(screen.getByText('指定推荐资产不可访问')).toBeVisible())
        expect(screen.getByText('Trace ID: recommended-reference-trace')).toBeVisible()
        expect(reads).toBe(1)
      }
    },
  )
})

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="quality-location">{location.pathname + location.search}</output>
}

function renderPage(initialEntry?: string, riskEnabled = true) {
  server.use(
    http.get('/api/v1/v3/features', () =>
      HttpResponse.json({ quality_intelligence: riskEnabled, impact_engine: riskEnabled }),
    ),
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
    ),
  )
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <ProjectTestProvider section="quality" initialEntry={initialEntry}>
            <LocationProbe />
            <QualityCenterPage />
          </ProjectTestProvider>
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
}
