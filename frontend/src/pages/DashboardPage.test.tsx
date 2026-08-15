import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DashboardPage from './DashboardPage'
import { project } from '../test/fixtures'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { server } from '../test/server'

describe('DashboardPage', () => {
  beforeEach(() => {
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get('/api/v1/dashboard/summary', () =>
        HttpResponse.json({
          project_count: 1,
          api_count: 3,
          workflow_count: 2,
          today_total: 2,
          today_passed: 1,
          today_failed: 1,
          pass_rate: 50,
          trend: [],
        }),
      ),
      http.get('/api/v1/dashboard/recent-executions', () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 10 }),
      ),
      ...insightHandlers(),
    )
  })

  it('renders API and workflow activity with known and fallback statuses', async () => {
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get('/api/v1/dashboard/summary', () =>
        HttpResponse.json({
          project_count: 1,
          api_count: 3,
          workflow_count: 2,
          today_total: 2,
          today_passed: 1,
          today_failed: 1,
          pass_rate: 50,
          trend: [],
        }),
      ),
      http.get('/api/v1/dashboard/recent-executions', () =>
        HttpResponse.json({
          items: [
            recentExecution('api-run', 'api', 'passed', '查询用户'),
            recentExecution('workflow-run', 'workflow', 'waiting', '订单流程'),
          ],
          total: 2,
          page: 1,
          page_size: 10,
        }),
      ),
    )
    renderDashboard()

    expect(await screen.findByRole('heading', { name: '质量指挥中心' })).toBeVisible()
    expect(await screen.findByText('查询用户')).toBeVisible()
    expect(screen.getByText('接口')).toBeVisible()
    expect(screen.getAllByText('工作流').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('通过')).toBeVisible()
    expect(screen.getByText('waiting')).toBeVisible()
    expect(screen.getByText(`当前查看：${project.name}`)).toBeVisible()
  })

  it('summarizes real project quality, impact, flaky, and immutable release evidence', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/release-risks`, () =>
        HttpResponse.json({
          items: [
            {
              id: 'risk-1',
              project_id: project.id,
              impact_run_id: 'impact-1',
              title: '订单候选风险',
              algorithm_version: 'release_risk_v1',
              window_days: 7,
              score: 64,
              quality_score: 72,
              risk_level: 'high',
              fingerprint: 'a'.repeat(64),
              created_by_id: 'user-1',
              created_at: '2026-08-15T08:00:00Z',
            },
          ],
          total: 1,
          page: 1,
          page_size: 100,
        }),
      ),
      http.get(`/api/v1/projects/${project.id}/release-risks/risk-1`, () =>
        HttpResponse.json({
          id: 'risk-1',
          project_id: project.id,
          impact_run_id: 'impact-1',
          title: '订单候选风险',
          algorithm_version: 'release_risk_v1',
          window_days: 7,
          score: 64,
          quality_score: 72,
          risk_level: 'high',
          fingerprint: 'a'.repeat(64),
          created_by_id: 'user-1',
          created_at: '2026-08-15T08:00:00Z',
          window_started_at: '2026-08-08T00:00:00Z',
          window_ended_at: '2026-08-15T00:00:00Z',
          baseline_started_at: '2026-08-01T00:00:00Z',
          baseline_ended_at: '2026-08-08T00:00:00Z',
          factors: [],
          evidence_snapshot: {},
          quality_trend: [],
          recommended_tests: [
            {
              target_type: 'workflow',
              target_id: 'workflow-1',
              name: '订单回归流程',
              version: 3,
              priority: 'high',
              reasons: ['覆盖 breaking change'],
              change_keys: ['git:orders'],
            },
          ],
          failure_clusters: [
            {
              id: 'cluster-1',
              release_risk_id: 'risk-1',
              fingerprint: 'cluster-fingerprint',
              title: 'Token 获取失败',
              failure_category: 'authentication',
              error_code: 'AUTH_FAILED',
              node_type: 'api',
              occurrence_count: 7,
              baseline_count: 1,
              affected_workflow_ids: ['workflow-1'],
              affected_workflow_names: ['订单回归流程'],
              sample_execution_ids: ['execution-1'],
              confidence: 0.96,
              regression_percent: 600,
              recommendation: '检查测试环境 Token Provider',
              created_at: '2026-08-15T08:00:00Z',
            },
          ],
        }),
      ),
      http.get(`/api/v1/projects/${project.id}/impact/runs`, () =>
        HttpResponse.json({
          items: [
            {
              id: 'impact-1',
              project_id: project.id,
              title: '订单 API 变更',
              source_ref: 'feature/orders',
              status: 'completed',
              source_fingerprint: 'b'.repeat(64),
              source_summary: {},
              change_count: 4,
              summary: {
                change_count: 4,
                breaking_change_count: 1,
                selected_asset_count: 3,
                covered_change_count: 3,
                gap_count: 1,
                coverage_percent: 75,
              },
              created_by_id: 'user-1',
              created_at: '2026-08-15T07:00:00Z',
            },
          ],
          total: 1,
          page: 1,
          page_size: 100,
        }),
      ),
      http.get(`/api/v1/projects/${project.id}/flaky-tests`, () =>
        HttpResponse.json({
          items: [flakyRecord('flaky-1', false), flakyRecord('flaky-2', true)],
          total: 2,
          page: 1,
          page_size: 100,
        }),
      ),
      http.get(`/api/v1/projects/${project.id}/release-decisions`, () =>
        HttpResponse.json({
          items: [releaseDecision()],
          total: 1,
          page: 1,
          page_size: 100,
        }),
      ),
    )

    renderDashboard()

    expect(await screen.findByText('64 / 100')).toBeVisible()
    expect(screen.getByText('高风险')).toBeVisible()
    expect(screen.getByText('4 项')).toBeVisible()
    expect(screen.getByText('覆盖 75% · 缺口 1')).toBeVisible()
    expect(screen.getByText('2 项')).toBeVisible()
    expect(screen.getByText('其中隔离 1 项')).toBeVisible()
    expect(screen.getAllByText('BLOCK').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('v3.0.0-rc.dashboard').length).toBeGreaterThanOrEqual(1)
    expect(await screen.findByText('Token 获取失败')).toBeVisible()
    expect(screen.getByText('订单回归流程')).toBeVisible()
    expect(screen.getByRole('link', { name: '查看影响分析' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/impact`,
    )
    expect(screen.getAllByRole('link', { name: '发布门禁' }).at(-1)).toHaveAttribute(
      'href',
      `/projects/${project.id}/release`,
    )
  })

  it('keeps project quality evidence disabled without calling gated APIs', async () => {
    const riskRequest = vi.fn()
    const impactRequest = vi.fn()
    server.use(
      http.get('/api/v1/v3/features', () =>
        HttpResponse.json({
          capability_sdk: true,
          plugin_registry: true,
          runner_fabric: true,
          multi_protocol: true,
          event_protocols: true,
          performance_lab: true,
          environment_lab: true,
          contract_hub: true,
          impact_engine: false,
          quality_intelligence: false,
          pact_broker: false,
        }),
      ),
      http.get(`/api/v1/projects/${project.id}/release-risks`, () => {
        riskRequest()
        return HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 })
      }),
      http.get(`/api/v1/projects/${project.id}/impact/runs`, () => {
        impactRequest()
        return HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 })
      }),
    )

    renderDashboard()

    expect(await screen.findByText('质量智能能力未启用')).toBeVisible()
    expect(screen.getByText('影响分析能力未启用')).toBeVisible()
    expect(riskRequest).not.toHaveBeenCalled()
    expect(impactRequest).not.toHaveBeenCalled()
  })

  it('renders the global quality overview without project evidence requests', async () => {
    renderDashboard('/dashboard')

    expect(await screen.findByRole('heading', { name: '质量指挥中心' })).toBeVisible()
    expect(screen.getByText('汇总所有可访问项目的接口资产与执行质量。')).toBeVisible()
    expect(await screen.findByText('可访问项目')).toBeVisible()
    expect(screen.queryByText('发布风险')).not.toBeInTheDocument()
  })

  it('reports a recent-execution loading failure without hiding the empty state', async () => {
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get('/api/v1/dashboard/summary', () =>
        HttpResponse.json({
          project_count: 1,
          api_count: 0,
          workflow_count: 0,
          today_total: 0,
          today_passed: 0,
          today_failed: 0,
          pass_rate: 0,
          trend: [],
        }),
      ),
      http.get('/api/v1/dashboard/recent-executions', () =>
        HttpResponse.json({ error: { message: '最近执行暂不可用' } }, { status: 503 }),
      ),
    )
    renderDashboard()

    expect(await screen.findByText('质量总览加载失败')).toBeVisible()
    expect(screen.getByText('最近执行暂不可用')).toBeVisible()
    expect(screen.getByText('暂无执行记录')).toBeVisible()
  })

  it('reports a summary loading failure while recent executions stay available', async () => {
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get('/api/v1/dashboard/summary', () =>
        HttpResponse.json({ error: { message: '统计暂不可用' } }, { status: 503 }),
      ),
      http.get('/api/v1/dashboard/recent-executions', () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 10 }),
      ),
    )
    renderDashboard()

    expect(await screen.findByText('统计暂不可用')).toBeVisible()
    expect(screen.getByText('暂无执行记录')).toBeVisible()
  })
})

function recentExecution(id: string, kind: 'api' | 'workflow', status: string, name: string) {
  return {
    id,
    project_id: project.id,
    project_name: project.name,
    kind,
    target_id: `${id}-target`,
    target_name: name,
    status,
    started_at: '2026-08-09T08:00:00Z',
    completed_at: null,
    duration_ms: null,
  }
}

function renderDashboard(initialEntry?: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <ProjectTestProvider section="dashboard" initialEntry={initialEntry}>
          <DashboardPage />
        </ProjectTestProvider>
      </QueryClientProvider>
    </AntdApp>,
  )
}

function insightHandlers() {
  return [
    http.get('/api/v1/v3/features', () =>
      HttpResponse.json({
        capability_sdk: true,
        plugin_registry: true,
        runner_fabric: true,
        multi_protocol: true,
        event_protocols: true,
        performance_lab: true,
        environment_lab: true,
        contract_hub: true,
        impact_engine: true,
        quality_intelligence: true,
        pact_broker: false,
      }),
    ),
    http.get(`/api/v1/projects/${project.id}/release-risks`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
    ),
    http.get(`/api/v1/projects/${project.id}/impact/runs`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
    ),
    http.get(`/api/v1/projects/${project.id}/flaky-tests`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
    ),
    http.get(`/api/v1/projects/${project.id}/release-decisions`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
    ),
  ]
}

function flakyRecord(id: string, quarantined: boolean) {
  return {
    id,
    project_id: project.id,
    target_type: 'workflow',
    target_id: `${id}-target`,
    target_version: 1,
    total_runs: 10,
    passed_runs: 5,
    failed_runs: 5,
    transitions: 4,
    flaky_score: 0.4,
    quarantined,
    last_status: 'failed',
    last_run_id: `${id}-run`,
    last_run_at: '2026-08-15T08:00:00Z',
    updated_at: '2026-08-15T08:00:00Z',
  }
}

function releaseDecision() {
  return {
    id: 'decision-1',
    project_id: project.id,
    release_policy_id: 'policy-1',
    candidate_ref: 'v3.0.0-rc.dashboard',
    status: 'block',
    policy_snapshot: {
      snapshot_version: '1',
      policy_id: 'policy-1',
      name: '严格策略',
      quality_gate_id: null,
      require_quality_gate: true,
      require_contract_compatibility: true,
      require_impact_evidence: true,
      min_impact_coverage_percent: 90,
      require_release_risk: true,
      max_release_risk_score: 50,
      require_performance_evidence: true,
      require_runner_evidence: true,
      policy_updated_at: '2026-08-15T08:00:00Z',
    },
    evidence_snapshot: {
      snapshot_version: '1',
      quality_gate: null,
      contract_compatibility: null,
      impact: null,
      release_risk: null,
      performance: null,
      runner: null,
    },
    reasons: [
      {
        code: 'RELEASE_RISK_THRESHOLD_EXCEEDED',
        evidence_type: 'release_risk',
        status: 'blocked',
        message: '发布风险超过策略阈值',
        actual: 64,
        expected: 50,
      },
    ],
    fingerprint: 'c'.repeat(64),
    test_plan_run_id: null,
    deployment_check_id: null,
    impact_run_id: 'impact-1',
    release_risk_id: 'risk-1',
    performance_run_id: null,
    runner_task_id: null,
    created_by_id: 'user-1',
    created_at: '2026-08-15T08:00:00Z',
  }
}
