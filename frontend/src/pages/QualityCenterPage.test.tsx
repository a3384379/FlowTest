import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import type { FlakyRecord, QualityGate } from '../features/quality/quality-service'
import type { TestPlanRun } from '../lib/api'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { project, user } from '../test/fixtures'
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

describe('QualityCenterPage', () => {
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

    await browser.click(screen.getByRole('switch', { name: `隔离 ${flaky.target_id}` }))
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

    await browser.click(screen.getByRole('switch', { name: `隔离 ${flaky.target_id}` }))
    expect(await screen.findByText('隔离被拒绝')).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: /JUnit/ }))
    expect(await screen.findByText(/status code 409/)).toBeInTheDocument()

    await browser.click(screen.getByRole('button', { name: /新建门禁/ }))
    await browser.type(screen.getByLabelText('门禁名称'), '被拒绝门禁')
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    expect(await screen.findByText('门禁配置被拒绝')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})

function renderPage() {
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
    ),
  )
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <ProjectTestProvider section="quality">
          <QualityCenterPage />
        </ProjectTestProvider>
      </QueryClientProvider>
    </AntdApp>,
  )
}
