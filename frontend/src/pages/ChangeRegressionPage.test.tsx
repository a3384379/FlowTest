import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, renderHook, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { ReactNode } from 'react'

import type { TestPlan } from '../lib/api'
import type {
  ChangeRegressionRun,
  ChangeRegressionSummary,
} from '../features/change-regression/change-regression-service'
import { useChangeRegression } from '../features/change-regression/use-change-regression'
import type { ReleasePolicy } from '../features/release-gate/release-gate-service'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { project, user } from '../test/fixtures'
import { server } from '../test/server'
import ChangeRegressionPage from './ChangeRegressionPage'

const planId = '00000000-0000-4000-8000-000000003001'
const policyId = '00000000-0000-4000-8000-000000003002'
const runId = '00000000-0000-4000-8000-000000003003'
const itemId = '00000000-0000-4000-8000-000000003004'

const plan: TestPlan = {
  id: planId,
  project_id: project.id,
  name: 'S45 回归计划',
  description: '',
  enabled: true,
  schedule_interval_seconds: null,
  schedule_cron: null,
  schedule_timezone: 'Asia/Shanghai',
  queue_priority: 5,
  next_run_at: null,
  created_by_id: user.id,
  created_at: '2026-08-23T01:00:00Z',
  updated_at: '2026-08-23T01:00:00Z',
  items: [
    {
      id: '00000000-0000-4000-8000-000000003005',
      target_type: 'workflow',
      target_id: '00000000-0000-4000-8000-000000003006',
      target_version: 1,
      workflow_id: '00000000-0000-4000-8000-000000003006',
      environment_id: '00000000-0000-4000-8000-000000003007',
      workflow_version: 1,
      position: 1,
      max_retries: 0,
      runtime_variables: {},
      runtime_headers: {},
    },
  ],
}

const policy: ReleasePolicy = {
  id: policyId,
  project_id: project.id,
  name: 'S45 Release Gate',
  enabled: true,
  quality_gate_id: null,
  require_quality_gate: false,
  require_contract_compatibility: false,
  require_impact_evidence: true,
  min_impact_coverage_percent: 100,
  require_release_risk: false,
  max_release_risk_score: 100,
  require_performance_evidence: false,
  require_runner_evidence: false,
  created_by_id: user.id,
  created_at: '2026-08-23T01:00:00Z',
  updated_at: '2026-08-23T01:00:00Z',
}

const pendingItem = {
  item_id: itemId,
  title: '补齐覆盖：orders.py',
  proposed_content: {},
  review_status: 'pending' as const,
  review_note: '',
  materialized_resource_type: null,
  materialized_resource_id: null,
}

const baseRun: ChangeRegressionRun = {
  id: runId,
  project_id: project.id,
  title: '订单变更回归',
  source_ref: 'github://acme/flowtest/pull/42',
  source_fingerprint: 'a'.repeat(64),
  candidate_ref: 'commit:abc123',
  status: 'review_required',
  impact_run_id: '00000000-0000-4000-8000-000000003008',
  test_plan_id: planId,
  test_plan_run_id: null,
  release_policy_id: policyId,
  release_risk_id: null,
  deployment_check_id: null,
  change_set_id: '00000000-0000-4000-8000-000000003009',
  release_decision_id: null,
  selected_assets: [],
  selection_summary: {
    coverage_gap_count: 1,
    asset_coverage_gap_count: 0,
    semantic_coverage_scopes: [
      {
        change_key: 'openapi:orders:query.page.maximum',
        operation: {
          api_definition_id: '00000000-0000-4000-8000-000000003010',
          api_version: 2,
          portable_operation_ref: 'orders.list',
          service_key: 'orders',
          method: 'GET',
          normalized_path: '/orders',
          contract_fingerprint: 'b'.repeat(64),
        },
        target: {
          location: 'query',
          field_path: ['page'],
          constraint: 'maximum',
          before: 100,
          after: 999,
        },
        project_known_coverage: 'covered',
        current_test_plan_coverage: 'missing',
        project_known_values: ['999|success'],
        current_test_plan_values: [],
        project_missing_values: [],
        current_test_plan_missing_values: ['999|success', '1000|invalid_request'],
        oracle_sources: [{ source_type: 'contract', source_ref: 'openapi://orders/GET' }],
        requires_review: false,
      },
    ],
  },
  missing_tests: [{ ...pendingItem, review_status: 'accepted' as const }],
  evidence: {},
  failure_triage: {},
  semantic_gap_waivers: [],
  approved_by_id: null,
  approved_at: null,
  created_by_id: user.id,
  created_at: '2026-08-23T01:00:00Z',
  updated_at: '2026-08-23T01:00:00Z',
  stages: [
    stage('change', 'completed'),
    stage('impact', 'completed'),
    stage('regression_selection', 'completed'),
    stage('missing_test', 'completed'),
    stage('review', 'pending'),
    stage('custom_extension', 'completed'),
  ],
}

describe('ChangeRegressionPage', () => {
  it('runs the review, approval, execution and release-gate actions', async () => {
    let currentRun = structuredClone(baseRun)
    installHandlers(
      () => currentRun,
      (next) => (currentRun = next),
    )
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByRole('heading', { name: '变更驱动回归' })).toBeVisible()
    expect(await screen.findByText('订单变更回归')).toBeVisible()
    expect(screen.getByText('Asset Mapping Coverage')).toBeVisible()
    expect(screen.getByText('Project Known Semantic Coverage')).toBeVisible()
    expect(screen.getByText('Current Test Plan Semantic Coverage')).toBeVisible()
    expect(screen.getByText('orders · GET /orders · v2')).toBeVisible()
    expect(screen.getByText('100 → 999')).toBeVisible()
    expect(screen.getByText('contract:openapi://orders/GET')).toBeVisible()
    await waitFor(() => expect(screen.getByRole('button', { name: '人工批准' })).toBeVisible())

    await browser.click(screen.getByRole('button', { name: '人工批准' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '执行回归' })).toBeVisible())

    await browser.click(screen.getByRole('button', { name: '执行回归' }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '评估 Release Gate' })).toBeVisible(),
    )

    await browser.click(screen.getByRole('button', { name: '评估 Release Gate' }))
    await waitFor(() => expect(screen.getAllByText('passed').length).toBeGreaterThan(0))
    expect(currentRun.status).toBe('passed')
  })

  it('creates a trace from the form and renders failure triage evidence', async () => {
    let currentRun: ChangeRegressionRun | null = null
    let createPayload: Record<string, unknown> | null = null
    installHandlers(
      () => currentRun,
      (next) => (currentRun = next),
      {
        plans: [plan],
        policies: [policy],
      },
    )
    server.use(
      http.post(`/api/v1/projects/${project.id}/change-regressions`, async ({ request }) => {
        createPayload = (await request.json()) as Record<string, unknown>
        currentRun = {
          ...baseRun,
          title: String(createPayload.title),
          status: 'evidence_ready',
          missing_tests: [],
          failure_triage: {
            algorithm_version: 's47-failure-triage-v2',
            primary_classification: 'SERVICE_ENDPOINT_FAILURE',
            secondary_candidates: ['FLAKY'],
            confidence: 0.95,
            reason_codes: ['ENDPOINT_OR_SERVER_FAILURE'],
            affected_service: 'orders',
            affected_operation: 'POST /orders',
            evidence_refs: ['execution://run/item/1'],
            retry_signal: true,
            recommended_action: '检查 Service Endpoint 健康、变体与服务状态',
            recommended_regression: ['目标服务健康回归'],
          },
        }
        return HttpResponse.json(currentRun, { status: 201 })
      }),
    )
    renderPage()
    const browser = userEvent.setup()

    await screen.findByText('请选择或创建一条链路。')
    await browser.type(screen.getByLabelText('链路名称'), '新建订单链路')
    await browser.type(screen.getByLabelText('候选版本'), 'commit:new123')
    await browser.click(screen.getByLabelText('回归测试计划'))
    await browser.click(await screen.findByText('S45 回归计划 · 1 项'))
    await browser.click(screen.getByLabelText('Release Policy'))
    await browser.click(await screen.findByText('S45 Release Gate'))
    await browser.type(screen.getByLabelText('Git Diff'), 'diff --git a/orders.py b/orders.py')
    await browser.click(screen.getByRole('button', { name: '分析并创建链路' }))

    await waitFor(() => expect(createPayload).not.toBeNull())
    expect(createPayload).toMatchObject({
      title: '新建订单链路',
      candidate_ref: 'commit:new123',
      test_plan_id: planId,
      release_policy_id: policyId,
      generate_missing_tests: true,
    })
    expect(await screen.findByText('执行失败已生成 Failure Triage 证据')).toBeVisible()
    expect(screen.getByText('SERVICE_ENDPOINT_FAILURE')).toBeVisible()
    expect(screen.getByText('orders')).toBeVisible()
    expect(screen.getByText('建议回归：目标服务健康回归')).toBeVisible()
  })

  it('resolves current TestPlan gaps through an exact asset or a per-gap waiver', async () => {
    const operation = baseRun.selection_summary.semantic_coverage_scopes?.[0]?.operation ?? null
    const target = baseRun.selection_summary.semantic_coverage_scopes?.[0]?.target ?? null
    const gap = (gapKey: string, asset: boolean) => ({
      change_key: 'openapi:orders:query.page.maximum',
      gap_key: gapKey,
      operation,
      target,
      semantic_requirement: {
        semantic_value: gapKey === 'gap-asset' ? '999' : '1000',
        expected_category: gapKey === 'gap-asset' ? 'success' : 'invalid_request',
        oracle_set_fingerprint: 'c'.repeat(64),
      },
      requirement_fingerprint: 'd'.repeat(64),
      coverage_status: 'MISSING' as const,
      project_known_coverage: asset ? ('COVERED' as const) : ('MISSING' as const),
      current_test_plan_coverage: 'MISSING' as const,
      recommended_existing_assets: asset
        ? [{ target_type: 'workflow' as const, target_id: plan.items[0].target_id }]
        : [],
      waiver: null,
    })
    let currentRun: ChangeRegressionRun = {
      ...structuredClone(baseRun),
      selection_summary: {
        ...structuredClone(baseRun.selection_summary),
        asset_mapping_gap_count: 0,
        project_semantic_gap_count: 0,
        current_test_plan_semantic_gap_count: 1,
        waived_current_plan_gap_count: 0,
        unresolved_current_plan_gap_count: 1,
        current_plan_gaps: [gap('gap-asset', true)],
      },
    }
    installHandlers(
      () => currentRun,
      (next) => (currentRun = next),
    )
    renderPage()

    await waitFor(() => expect(document.body.textContent).toContain('1 个当前计划语义缺口尚未解决'))
    expect(document.body.textContent).toContain('Add to Plan · workflow')
    expect(buttonByText('人工批准')).toBeDisabled()
    expect(
      document.querySelector('input[placeholder="至少 10 字，说明发布风险与补偿措施"]'),
    ).toBeTruthy()
    expect(buttonByText('人工豁免')).toBeDisabled()
  })

  it('renders persisted WAIVED gaps without presenting them as covered', async () => {
    const operation = baseRun.selection_summary.semantic_coverage_scopes?.[0]?.operation ?? null
    const target = baseRun.selection_summary.semantic_coverage_scopes?.[0]?.target ?? null
    const waivedRun: ChangeRegressionRun = {
      ...structuredClone(baseRun),
      selection_summary: {
        ...structuredClone(baseRun.selection_summary),
        current_test_plan_semantic_gap_count: 1,
        waived_current_plan_gap_count: 1,
        unresolved_current_plan_gap_count: 0,
        current_plan_gaps: [
          {
            change_key: 'openapi:orders:query.page.maximum',
            gap_key: 'gap-waiver',
            operation,
            target,
            semantic_requirement: {
              semantic_value: '1000',
              expected_category: 'invalid_request',
              oracle_set_fingerprint: 'c'.repeat(64),
            },
            requirement_fingerprint: 'd'.repeat(64),
            coverage_status: 'WAIVED',
            project_known_coverage: 'MISSING',
            current_test_plan_coverage: 'WAIVED',
            recommended_existing_assets: [],
            waiver: {
              reason: '人工确认风险并安排补偿回归',
              approved_by: user.id,
              approved_at: '2026-08-23T01:30:00Z',
              expires_at: null,
            },
          },
        ],
      },
    }
    installHandlers(
      () => waivedRun,
      () => undefined,
    )
    renderPage()
    await waitFor(() => expect(document.body.textContent).toContain(`Approver: ${user.id}`))
    expect(document.body.textContent).toContain('不过期')
    expect(document.body.textContent).toContain('无精确匹配资产')
    expect(document.body.textContent).toContain('WAIVED')
    expect(buttonByText('人工批准')).toBeEnabled()
  })

  it('shows unresolved semantic targets and truthful empty triage fields', async () => {
    const unresolvedRun: ChangeRegressionRun = {
      ...baseRun,
      source_ref: '',
      selection_summary: {
        coverage_gap_count: 1,
        semantic_coverage_scopes: [
          {
            change_key: 'unresolved:legacy-change',
            operation: null,
            target: null,
            project_known_coverage: 'missing',
            current_test_plan_coverage: 'missing',
            project_known_values: [],
            current_test_plan_values: [],
            project_missing_values: [],
            current_test_plan_missing_values: [],
            oracle_sources: [],
            requires_review: true,
          },
        ],
      },
      missing_tests: [{ ...pendingItem, review_status: 'rejected' }],
      failure_triage: {
        algorithm_version: 's47-failure-triage-v2',
        primary_classification: 'NETWORK_FAILURE',
        secondary_candidates: [],
        confidence: 0.5,
        reason_codes: [],
        affected_service: null,
        endpoint_variant: null,
        affected_operation: null,
        evidence_refs: [],
        retry_signal: false,
        recommended_action: '检查网络路径',
        recommended_regression: [],
      },
    }
    installHandlers(
      () => unresolvedRun,
      () => undefined,
    )
    renderPage()

    expect(await screen.findByText('订单变更回归')).toBeVisible()
    expect(screen.getByText('unknown')).toBeVisible()
    expect(screen.getAllByText('unresolved')).toHaveLength(5)
    expect(screen.getByText('-')).toBeVisible()
    expect(screen.getAllByText('无').length).toBeGreaterThanOrEqual(3)
    expect(screen.getByText('待审核')).toBeVisible()
    expect(screen.getByText('未填写')).toBeVisible()
    expect(screen.getByText('否')).toBeVisible()
    expect(screen.getAllByText('未定位')).toHaveLength(3)
    expect(screen.queryByText(/建议回归：/)).not.toBeInTheDocument()
  })

  it('reports review decisions and action failures through the hook', async () => {
    let rejectCalls = 0
    const addPayloads: unknown[] = []
    const waiverPayloads: unknown[] = []
    const queuedRun = { ...baseRun, status: 'queued' as const }
    server.use(
      http.get('/api/v1/projects', () => HttpResponse.json(page([project]))),
      http.get(`/api/v1/projects/${project.id}/change-regressions`, () =>
        HttpResponse.json(page([summary(queuedRun)])),
      ),
      http.get(`/api/v1/projects/${project.id}/test-plans`, () => HttpResponse.json(page([plan]))),
      http.get(`/api/v1/projects/${project.id}/release-policies`, () =>
        HttpResponse.json([policy]),
      ),
      http.get(`/api/v1/projects/${project.id}/change-regressions/${runId}`, () =>
        HttpResponse.json(queuedRun),
      ),
      http.post(`/api/v1/projects/${project.id}/change-regressions`, () =>
        HttpResponse.json({ error: { message: '创建服务不可用' } }, { status: 503 }),
      ),
      http.post(
        `/api/v1/projects/${project.id}/change-regressions/${runId}/change-set-items/${itemId}/accept`,
        () => HttpResponse.json(baseRun),
      ),
      http.post(
        `/api/v1/projects/${project.id}/change-regressions/${runId}/change-set-items/${itemId}/reject`,
        () => {
          rejectCalls += 1
          return rejectCalls === 1
            ? HttpResponse.json(baseRun)
            : HttpResponse.json({ error: { message: '审核服务不可用' } }, { status: 503 })
        },
      ),
      http.post(`/api/v1/projects/${project.id}/change-regressions/${runId}/approve`, () =>
        HttpResponse.json({ error: { message: '批准服务不可用' } }, { status: 503 }),
      ),
      http.post(
        `/api/v1/projects/${project.id}/change-regressions/${runId}/add-project-known-test`,
        async ({ request }) => {
          addPayloads.push(await request.json())
          return HttpResponse.json(baseRun)
        },
      ),
      http.post(
        `/api/v1/projects/${project.id}/change-regressions/${runId}/semantic-gap-waivers`,
        async ({ request }) => {
          waiverPayloads.push(await request.json())
          return HttpResponse.json(baseRun)
        },
      ),
    )
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    const wrapper = ({ children }: { children: ReactNode }) => (
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <ProjectTestProvider section="change-regression">{children}</ProjectTestProvider>
        </QueryClientProvider>
      </AntdApp>
    )
    const { result } = renderHook(() => useChangeRegression(), { wrapper })
    await waitFor(() => expect(result.current.projectId).toBe(project.id))
    await waitFor(() => expect(result.current.detail.data?.status).toBe('queued'))

    await act(async () => {
      await expect(result.current.reviewItem({ runId, itemId, decision: 'accept' })).resolves.toBe(
        true,
      )
      await expect(result.current.reviewItem({ runId, itemId, decision: 'reject' })).resolves.toBe(
        true,
      )
      await expect(result.current.reviewItem({ runId, itemId, decision: 'reject' })).resolves.toBe(
        false,
      )
      await expect(result.current.approve(runId)).resolves.toBe(false)
      await expect(
        result.current.addToPlan({
          runId,
          gapKey: 'workflow-gap',
          targetType: 'workflow',
          targetId: plan.items[0].target_id,
          environmentId: plan.items[0].environment_id ?? undefined,
        }),
      ).resolves.toBe(true)
      await expect(
        result.current.addToPlan({
          runId,
          gapKey: 'case-gap',
          targetType: 'test_case',
          targetId: itemId,
        }),
      ).resolves.toBe(true)
      await expect(
        result.current.waiveGap({
          runId,
          gapKey: 'permanent-gap',
          reason: '人工确认风险并安排补偿回归',
        }),
      ).resolves.toBe(true)
      await expect(
        result.current.waiveGap({
          runId,
          gapKey: 'expiring-gap',
          reason: '人工确认风险并安排补偿回归',
          expiresAt: '2026-08-24T00:00:00Z',
        }),
      ).resolves.toBe(true)
      await expect(
        result.current.createRun({
          title: '创建失败链路',
          source_ref: 'test://change',
          candidate_ref: 'commit:failed',
          git_diff: 'diff --git a/a b/a',
          openapi_diffs: [],
          schema_diffs: [],
          test_plan_id: planId,
          release_policy_id: policyId,
          generate_missing_tests: true,
        }),
      ).resolves.toBe(false)
    })
    expect(rejectCalls).toBe(2)
    expect(addPayloads).toEqual([
      {
        gap_key: 'workflow-gap',
        item: {
          target_type: 'workflow',
          target_id: plan.items[0].target_id,
          environment_id: plan.items[0].environment_id,
        },
      },
      { gap_key: 'case-gap', item: { target_type: 'case', target_id: itemId } },
    ])
    expect(waiverPayloads).toEqual([
      { gap_key: 'permanent-gap', reason: '人工确认风险并安排补偿回归' },
      {
        gap_key: 'expiring-gap',
        reason: '人工确认风险并安排补偿回归',
        expires_at: '2026-08-24T00:00:00Z',
      },
    ])
  })
})

function stage(name: string, status: string) {
  return {
    id: `00000000-0000-4000-8000-${String(Math.random()).slice(2, 14).padEnd(12, '0')}`,
    sequence: 1,
    stage: name,
    status,
    details: {},
    actor_id: user.id,
    created_at: '2026-08-23T01:00:00Z',
  }
}

function buttonByText(label: string): HTMLButtonElement | undefined {
  return [...document.querySelectorAll('button')].find((button) => button.textContent === label)
}

function installHandlers(
  getRun: () => ChangeRegressionRun | null,
  setRun: (run: ChangeRegressionRun) => void,
  options: { plans?: TestPlan[]; policies?: ReleasePolicy[] } = {},
) {
  server.use(
    http.get('/api/v1/projects', () => HttpResponse.json(page([project]))),
    http.get(`/api/v1/projects/${project.id}/change-regressions`, () => {
      const run = getRun()
      return HttpResponse.json(page(run ? [summary(run)] : []))
    }),
    http.get(`/api/v1/projects/${project.id}/test-plans`, () =>
      HttpResponse.json(page(options.plans ?? [plan])),
    ),
    http.get(`/api/v1/projects/${project.id}/release-policies`, () =>
      HttpResponse.json(options.policies ?? [policy]),
    ),
    http.get(`/api/v1/projects/${project.id}/change-regressions/${runId}`, () => {
      const run = getRun()
      return run
        ? HttpResponse.json(run)
        : HttpResponse.json({ detail: 'not found' }, { status: 404 })
    }),
    http.post(
      `/api/v1/projects/${project.id}/change-regressions/${runId}/change-set-items/${itemId}/accept`,
      () => {
        const run = getRun()
        if (!run) return HttpResponse.json({ detail: 'not found' }, { status: 404 })
        const accepted = run.missing_tests.map((item) => ({
          ...item,
          review_status: 'accepted' as const,
          materialized_resource_type: 'test_design',
        }))
        const next = { ...run, missing_tests: accepted, status: 'review_required' as const }
        setRun(next)
        return HttpResponse.json(next)
      },
    ),
    http.post(`/api/v1/projects/${project.id}/change-regressions/${runId}/approve`, () => {
      const run = getRun()
      if (!run) return HttpResponse.json({ detail: 'not found' }, { status: 404 })
      const next = { ...run, status: 'approved' as const }
      setRun(next)
      return HttpResponse.json(next)
    }),
    http.post(`/api/v1/projects/${project.id}/change-regressions/${runId}/execute`, () => {
      const run = getRun()
      if (!run) return HttpResponse.json({ detail: 'not found' }, { status: 404 })
      const next = {
        ...run,
        status: 'evidence_ready' as const,
        test_plan_run_id: '00000000-0000-4000-8000-000000003010',
      }
      setRun(next)
      return HttpResponse.json(next)
    }),
    http.post(`/api/v1/projects/${project.id}/change-regressions/${runId}/release-gate`, () => {
      const run = getRun()
      if (!run) return HttpResponse.json({ detail: 'not found' }, { status: 404 })
      const next = {
        ...run,
        status: 'passed' as const,
        release_decision_id: '00000000-0000-4000-8000-000000003011',
      }
      setRun(next)
      return HttpResponse.json(next)
    }),
  )
}

function summary(run: ChangeRegressionRun): ChangeRegressionSummary {
  return {
    ...run,
    selected_asset_count: run.selected_assets.length,
    missing_test_count: run.missing_tests.length,
  }
}

function page<T>(items: T[]) {
  return { items, total: items.length, page: 1, page_size: 100 }
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <ProjectTestProvider section="change-regression">
          <ChangeRegressionPage />
        </ProjectTestProvider>
      </QueryClientProvider>
    </AntdApp>,
  )
}
