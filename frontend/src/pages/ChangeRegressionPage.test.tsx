import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { ReactNode } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import type { TestPlan } from '../lib/api'
import type {
  ChangeRegressionRun,
  ChangeRegressionInput,
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
  it('requires opening the proposed content before accepting a missing test', async () => {
    let current: ChangeRegressionRun = {
      ...structuredClone(baseRun),
      missing_tests: [
        {
          ...pendingItem,
          proposed_content: {
            target_type: 'api',
            target_id: 'orders-api',
            target_version: 2,
            assertions: [{ kind: 'status_code', expected: 201 }],
            evidence_refs: ['openapi://orders/create'],
          },
        },
      ],
    }
    installHandlers(
      () => current,
      (next) => {
        current = next as typeof current
      },
    )
    const reviewedPayloads: unknown[] = []
    const expectedContent = structuredClone(current.missing_tests[0].proposed_content)
    server.use(
      http.post(
        `/api/v1/projects/${project.id}/change-regressions/${runId}/change-set-items/${itemId}/accept`,
        async ({ request }) => {
          reviewedPayloads.push(await request.json())
          current = {
            ...current,
            missing_tests: current.missing_tests.map((item) => ({
              ...item,
              review_status: 'accepted',
            })),
          }
          return HttpResponse.json(current)
        },
      ),
    )
    renderPage()
    await screen.findByText('订单变更回归')
    const missing = within(screen.getByLabelText('缺失测试草案'))
    expect(missing.queryByText('接受', { exact: true })).not.toBeInTheDocument()
    // Check the semantic button and its visibility once instead of repeating ancestor-style queries.
    const openReview = missing.getByText('查看并审核').closest('button')
    expect(openReview).toHaveRole('button')
    expect(openReview).toBeVisible()
    fireEvent.click(openReview!)
    const review = screen.getByText('缺失测试草案审核').closest('[role=dialog]')!
    expect(review).toHaveRole('dialog')
    const content = within(review as HTMLElement).getByLabelText('缺失测试草案内容')
    expect(content).toHaveTextContent('openapi://orders/create')
    expect(content).toHaveTextContent('"expected": 201')
    expect(content).toBeVisible()
    const accept = within(review as HTMLElement)
      .getByText('接受草案')
      .closest('button')!
    expect(accept).toHaveRole('button')
    expect(accept).toBeEnabled()
    await userEvent.click(accept)
    await waitFor(() => expect(current.missing_tests[0].review_status).toBe('accepted'))
    expect(reviewedPayloads).toEqual([{ note: '前端人工审核', expected_content: expectedContent }])
  })
  it('preserves regression evidence while disabling viewer approval and creation', async () => {
    let current = structuredClone(baseRun)
    installHandlers(
      () => current,
      (next) => {
        current = next
      },
    )
    server.use(
      http.get(`/api/v1/projects/${project.id}/permissions`, () =>
        HttpResponse.json({
          effective_role: 'viewer',
          capabilities: ['read'],
          matrix: {},
        }),
      ),
    )
    renderPage()
    expect(await screen.findByText('订单变更回归')).toBeInTheDocument()
    const approve = buttonByText('人工批准')!
    expect(approve).toHaveRole('button')
    expect(approve).toBeDisabled()
    fireEvent.click(approve)
    expect(current.status).toBe('review_required')
    const create = buttonByText('新建回归链路')!
    expect(create).toHaveRole('button')
    expect(create).toBeDisabled()
    fireEvent.click(create)
    expect(screen.queryByLabelText('链路名称')).not.toBeInTheDocument()
  })

  it('keeps the viewed snapshot through background refresh and replaces it only on explicit refresh', async () => {
    let current: ChangeRegressionRun = {
      ...structuredClone(baseRun),
      missing_tests: [{ ...pendingItem, proposed_content: { expected: 201 } }],
    }
    installHandlers(
      () => current,
      (next) => {
        current = next
      },
    )
    const payloads: unknown[] = []
    server.use(
      http.post(
        `/api/v1/projects/${project.id}/change-regressions/${runId}/change-set-items/${itemId}/accept`,
        async ({ request }) => {
          payloads.push(await request.json())
          return HttpResponse.json(
            {
              error: {
                code: 'STALE_REVIEW',
                message: '草案已变化，请重新审核',
                trace_id: 'stale-draft',
              },
            },
            { status: 409 },
          )
        },
      ),
    )
    const { queryClient } = renderPage()
    await screen.findByText(pendingItem.title)
    const region = within(screen.getByRole('region', { name: '缺失测试草案' }))
    fireEvent.click(region.getByText('查看并审核').closest('button')!)
    const review = within(screen.getByRole('dialog', { name: '缺失测试草案审核' }))
    expect(review.getByLabelText('缺失测试草案内容')).toHaveTextContent('"expected": 201')

    current = {
      ...current,
      source_fingerprint: 'b'.repeat(64),
      missing_tests: [
        { ...pendingItem, title: '服务器更新的草案', proposed_content: { expected: 500 } },
      ],
    }
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ['change-regression', project.id, runId] })
    })
    await screen.findByText('服务器更新的草案')
    expect(review.getByText(baseRun.source_fingerprint)).toBeInTheDocument()
    expect(review.getByLabelText('缺失测试草案内容')).toHaveTextContent('"expected": 201')
    await userEvent.click(review.getByRole('button', { name: '接受草案' }))
    await screen.findByText(/stale-draft/)
    expect(payloads).toEqual([{ note: '前端人工审核', expected_content: { expected: 201 } }])
    expect(review.getByLabelText('缺失测试草案内容')).toHaveTextContent('"expected": 201')

    await userEvent.click(review.getByRole('button', { name: '刷新草案' }))
    await waitFor(() =>
      expect(review.getByLabelText('缺失测试草案内容')).toHaveTextContent('"expected": 500'),
    )
    expect(review.getByText('b'.repeat(64))).toBeInTheDocument()
    expect(payloads).toHaveLength(1)

    server.use(
      http.get(`/api/v1/projects/${project.id}/change-regressions/${runId}`, () =>
        HttpResponse.json(
          { error: { code: 'UNAVAILABLE', message: '刷新失败', trace_id: 'refresh-draft' } },
          { status: 503 },
        ),
      ),
    )
    await userEvent.click(review.getByRole('button', { name: '刷新草案' }))
    await waitFor(() => expect(review.getByText(/refresh-draft/)).toBeInTheDocument())
    expect(review.getByLabelText('缺失测试草案内容')).toHaveTextContent('"expected": 500')
    server.use(
      http.get(`/api/v1/projects/${project.id}/change-regressions/${runId}`, () =>
        HttpResponse.json(current),
      ),
    )
    await userEvent.click(review.getByRole('button', { name: '刷新草案' }))
    await waitFor(() => expect(review.queryByText(/refresh-draft/)).not.toBeInTheDocument())
    expect(review.getByLabelText('缺失测试草案内容')).toHaveTextContent('"expected": 500')
  })

  it('does not replace a newly opened review when the previous refresh completes late', async () => {
    const otherItem = {
      ...pendingItem,
      item_id: 'other-item',
      title: '草案 B',
      proposed_content: { marker: 'B' },
    }
    let current: ChangeRegressionRun = {
      ...structuredClone(baseRun),
      missing_tests: [
        { ...pendingItem, title: '草案 A', proposed_content: { marker: 'A' } },
        otherItem,
      ],
    }
    installHandlers(
      () => current,
      (next) => {
        current = next
      },
    )
    let delayed = false
    let release: (() => void) | undefined
    server.use(
      http.get(`/api/v1/projects/${project.id}/change-regressions/${runId}`, async () => {
        const response = structuredClone(current)
        if (delayed)
          await new Promise<void>((resolve) => {
            release = resolve
          })
        return HttpResponse.json(response)
      }),
    )
    renderPage()
    const row = (title: string) => within(screen.getByText(title).closest('tr')!)
    await screen.findByText('草案 A')
    fireEvent.click(row('草案 A').getByText('查看并审核').closest('button')!)
    let review = within(screen.getByRole('dialog', { name: '缺失测试草案审核' }))
    delayed = true
    current = {
      ...current,
      missing_tests: [
        { ...pendingItem, title: '草案 A 已更新', proposed_content: { marker: 'updated-A' } },
        otherItem,
      ],
    }
    await userEvent.click(review.getByRole('button', { name: '刷新草案' }))
    await waitFor(() => expect(release).toBeDefined())
    expect(review.getByRole('button', { name: '接受草案' })).toBeDisabled()
    fireEvent.click(review.getByRole('button', { name: /Close|关闭/ }))
    fireEvent.click(row('草案 B').getByText('查看并审核').closest('button')!)
    review = within(screen.getByRole('dialog', { name: '缺失测试草案审核' }))
    expect(review.getByLabelText('缺失测试草案内容')).toHaveTextContent('"marker": "B"')
    await act(async () => {
      release!()
    })
    await screen.findByText('草案 A 已更新')
    expect(review.getByLabelText('缺失测试草案内容')).toHaveTextContent('"marker": "B"')
    expect(review.getByRole('button', { name: '接受草案' })).toBeEnabled()
  })

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
    expect(screen.getByText('orders · GET /orders')).toBeVisible()
    expect(screen.getByText(/00000000-0000-4000-8000-000000003010 · v2/)).toBeVisible()
    expect(screen.getByText('100 → 999')).toBeVisible()
    expect(screen.getByText('contract:openapi://orders/GET')).toBeVisible()
    const actions = within(await screen.findByRole('group', { name: '变更回归动作' }))
    await waitFor(() => expect(actions.getByRole('button', { name: '人工批准' })).toBeVisible())

    await browser.click(actions.getByRole('button', { name: '人工批准' }))
    await waitFor(() => expect(actions.getByRole('button', { name: '执行回归' })).toBeVisible())

    await browser.click(actions.getByRole('button', { name: '执行回归' }))
    await waitFor(() =>
      expect(actions.getByRole('button', { name: '评估 Release Gate' })).toBeVisible(),
    )

    await browser.click(actions.getByRole('button', { name: '评估 Release Gate' }))
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
    await openRegressionForm(browser)
    await waitFor(() => expect(screen.getByLabelText('链路名称')).toBeEnabled())
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

  it('creates a chain from an OpenAPI pair without requiring Git and submits the exact references', async () => {
    let current: ChangeRegressionRun | null = null,
      payload: ChangeRegressionInput | null = null
    installHandlers(
      () => current,
      (next) => {
        current = next
      },
    )
    server.use(
      http.post(`/api/v1/projects/${project.id}/change-regressions`, async ({ request }) => {
        payload = (await request.json()) as ChangeRegressionInput
        current = { ...baseRun, title: payload.title, missing_tests: [] }
        return HttpResponse.json(current, { status: 201 })
      }),
    )
    renderPage()
    const browser = userEvent.setup()
    await fillRegressionForm(browser)
    await browser.click(screen.getByRole('button', { name: '添加 OpenAPI 对比' }))
    await selectSource(browser, 'OpenAPI 基线 1', '基线契约 · vbase.yaml')
    await selectSource(browser, 'OpenAPI 当前版本 1', '当前契约 · vcurrent.yaml')
    await browser.click(screen.getByRole('button', { name: '分析并创建链路' }))
    await waitFor(() => expect(payload).not.toBeNull())
    expect(payload).toMatchObject({
      openapi_diffs: [{ baseline_run_id: 'openapi-baseline', current_run_id: 'openapi-current' }],
      schema_diffs: [],
      test_plan_id: planId,
      release_policy_id: policyId,
    })
    expect(payload).not.toHaveProperty('git_diff')
  })

  it('preserves Git input and submits both GraphQL and Proto version pairs', async () => {
    let current: ChangeRegressionRun | null = null,
      payload: ChangeRegressionInput | null = null
    installHandlers(
      () => current,
      (next) => {
        current = next
      },
    )
    server.use(
      http.post(`/api/v1/projects/${project.id}/change-regressions`, async ({ request }) => {
        payload = (await request.json()) as ChangeRegressionInput
        current = { ...baseRun, missing_tests: [] }
        return HttpResponse.json(current, { status: 201 })
      }),
    )
    renderPage()
    const browser = userEvent.setup()
    await fillRegressionForm(browser)
    await browser.type(screen.getByLabelText('Git Diff'), 'diff --git a/orders.py b/orders.py')
    await browser.click(screen.getByRole('button', { name: '添加 GraphQL 对比' }))
    await selectSource(browser, 'GraphQL 基线 1', 'GraphQL 基线 · v1')
    await selectSource(browser, 'GraphQL 当前版本 1', 'GraphQL 当前 · v2')
    await browser.click(screen.getByRole('button', { name: '添加 Proto / gRPC 对比' }))
    await selectSource(browser, 'Proto / gRPC 基线 1', 'Proto 基线 · v1')
    await selectSource(browser, 'Proto / gRPC 当前版本 1', 'Proto 当前 · v2')
    expect(screen.getByLabelText('Git Diff')).toHaveValue('diff --git a/orders.py b/orders.py')
    await browser.click(screen.getByRole('button', { name: '分析并创建链路' }))
    await waitFor(() => expect(payload).not.toBeNull())
    expect(payload).toMatchObject({
      git_diff: 'diff --git a/orders.py b/orders.py',
      openapi_diffs: [],
      schema_diffs: [
        { baseline_artifact_id: 'graphql-baseline', current_artifact_id: 'graphql-current' },
        { baseline_artifact_id: 'grpc-baseline', current_artifact_id: 'grpc-current' },
      ],
    })
  })

  it.each(['none', 'partial', 'same'] as const)(
    'rejects an invalid source combination before creating a chain: %s',
    async (kind) => {
      installHandlers(
        () => null,
        () => undefined,
      )
      let creates = 0
      server.use(
        http.post(`/api/v1/projects/${project.id}/change-regressions`, () => {
          creates++
          return HttpResponse.json(baseRun, { status: 201 })
        }),
      )
      renderPage()
      const browser = userEvent.setup()
      await fillRegressionForm(browser)
      if (kind !== 'none') {
        await browser.click(screen.getByRole('button', { name: '添加 OpenAPI 对比' }))
        await selectSource(browser, 'OpenAPI 基线 1', '基线契约 · vbase.yaml')
        if (kind === 'same')
          await selectSource(browser, 'OpenAPI 当前版本 1', '基线契约 · vbase.yaml')
      }
      await browser.click(screen.getByRole('button', { name: '分析并创建链路' }))
      const message =
        kind === 'none'
          ? '至少提供一种 Git Diff 或契约版本对比'
          : kind === 'partial'
            ? '请完整选择 OpenAPI 基线和当前版本'
            : 'OpenAPI 基线和当前版本必须不同'
      expect((await screen.findAllByText(message))[0]).toBeVisible()
      expect(creates).toBe(0)
      expect(screen.getByLabelText('链路名称')).toHaveValue('契约差异链路')
    },
  )

  it('keeps source inputs while the creation form is collapsed and reopened', async () => {
    installHandlers(
      () => baseRun,
      () => undefined,
    )
    renderPage()
    const browser = userEvent.setup()
    await fillRegressionForm(browser)
    await browser.type(screen.getByLabelText('Git Diff'), 'diff --git a/retained.py b/retained.py')
    await browser.click(screen.getByRole('button', { name: '添加 OpenAPI 对比' }))
    await selectSource(browser, 'OpenAPI 基线 1', '基线契约 · vbase.yaml')
    await browser.click(screen.getByRole('button', { name: '收起创建表单（保留输入）' }))
    expect(screen.queryByLabelText('链路名称')).not.toBeInTheDocument()
    await openRegressionForm(browser)
    expect(screen.getByLabelText('链路名称')).toHaveValue('契约差异链路')
    expect(screen.getByLabelText('Git Diff')).toHaveValue('diff --git a/retained.py b/retained.py')
    expect(screen.getByText('基线契约 · vbase.yaml')).toBeVisible()
  })

  it('opens immutable source versions instead of the latest catalog values', async () => {
    installHandlers(
      () => baseRun,
      () => undefined,
    )
    const baseline = '00000000-0000-4000-8000-000000008001',
      current = '00000000-0000-4000-8000-000000008002',
      graphql = '00000000-0000-4000-8000-000000008003',
      newer = '00000000-0000-4000-8000-000000008004'
    const requested: string[] = []
    server.use(
      http.get(`/api/v1/projects/${project.id}/impact/runs/:id`, ({ params }) => {
        requested.push(String(params.id))
        return HttpResponse.json({
          id: baseRun.impact_run_id,
          project_id: project.id,
          source_fingerprint: 'original-impact-fingerprint',
          source_summary: {
            git: null,
            openapi: [
              { baseline_run_id: baseline, current_run_id: current, source_name: '冻结契约 v2' },
            ],
            schemas: [
              {
                protocol: 'graphql',
                baseline_artifact_id: graphql,
                current_artifact_id: newer,
                name: '冻结 GraphQL 对比',
              },
            ],
          },
        })
      }),
    )
    renderPage()
    const sourceAction = await screen.findByRole('button', { name: '查看冻结来源版本' })
    await waitFor(() => expect(sourceAction).toBeEnabled())
    await userEvent.setup().click(sourceAction)
    expect(await screen.findByText('original-impact-fingerprint')).toBeVisible()
    const card = within(screen.getByText('冻结来源版本').closest('.ant-card')! as HTMLElement)
    expect(card.getByText(baseline)).toBeVisible()
    expect(card.getByText(current)).toBeVisible()
    expect(card.getByRole('link', { name: `打开 GraphQL 基线 ${graphql}` })).toHaveAttribute(
      'href',
      `/projects/${project.id}/protocols?mode=graphql&graphqlSchema=${graphql}`,
    )
    expect(card.getByRole('link', { name: `打开 GraphQL 当前版本 ${newer}` })).toHaveAttribute(
      'href',
      `/projects/${project.id}/protocols?mode=graphql&graphqlSchema=${newer}`,
    )
    expect(requested).toEqual([baseRun.impact_run_id])
  })

  it('keeps historical source reads disabled when impact analysis is closed', async () => {
    installHandlers(
      () => baseRun,
      () => undefined,
    )
    let reads = 0
    server.use(
      http.get('/api/v1/v3/features', () => HttpResponse.json({ impact_engine: false })),
      http.get(`/api/v1/projects/${project.id}/impact/*`, () => {
        reads++
        return HttpResponse.json({})
      }),
    )
    renderPage()
    expect(await screen.findByText('影响分析尚未启用，现有回归链路可只读查看')).toBeVisible()
    const source = await screen.findByRole('button', { name: '查看冻结来源版本' })
    expect(source).toBeDisabled()
    await userEvent.setup().click(source)
    expect(reads).toBe(0)
  })

  it('links the frozen chain and supported evidence references while preserving unsupported history without writes', async () => {
    const executionId = '00000000-0000-4000-8000-000000007001',
      planRunId = '00000000-0000-4000-8000-000000007002',
      runItemId = '00000000-0000-4000-8000-000000007003'
    const traced: ChangeRegressionRun = {
      ...baseRun,
      test_plan_run_id: planRunId,
      release_decision_id: 'frozen-decision',
      failure_triage: {
        algorithm_version: 's47-failure-triage-v2',
        primary_classification: 'ASSERTION_FAILURE',
        secondary_candidates: [],
        confidence: 0.9,
        reason_codes: [],
        affected_service: 'orders',
        affected_operation: 'GET /orders',
        retry_signal: true,
        recommended_action: '核对冻结证据',
        recommended_regression: [],
        evidence_refs: [
          `flowtest://runs/${executionId}/nodes/health?attempt=2`,
          `flowtest://test-plan-runs/${planRunId}/items/${runItemId}`,
          'javascript:alert(1)',
          'execution://run/item/1',
        ],
      },
      missing_tests: [
        {
          ...pendingItem,
          review_status: 'accepted',
          materialized_resource_type: 'test_design_bundle',
          materialized_resource_id: 'original-design',
        },
      ],
      selection_summary: {
        ...baseRun.selection_summary,
        generated_assets: [
          {
            change_key: 'change-1',
            source_item_id: itemId,
            target_type: 'workflow',
            target_id: 'generated-workflow',
            status: 'draft',
          },
          {
            change_key: 'change-1',
            source_item_id: itemId,
            target_type: 'test_case',
            target_id: 'generated-case',
            status: 'draft',
          },
        ],
      },
    }
    installHandlers(
      () => traced,
      () => undefined,
    )
    server.use(
      http.get(`/api/v1/projects/${project.id}/test-plan-runs/${planRunId}`, () =>
        HttpResponse.json({
          run: { id: planRunId, project_id: project.id, test_plan_id: planId, status: 'failed' },
          items: [
            {
              id: runItemId,
              workflow_execution_id: executionId,
              attempts: 2,
              target_type: 'workflow',
              target_id: 'original-workflow',
              target_version: 1,
              workflow_id: 'original-workflow',
              workflow_version: 1,
            },
          ],
        }),
      ),
    )
    let writes = 0
    server.use(
      http.post(`/api/v1/projects/${project.id}/*`, () => {
        writes++
        return HttpResponse.json({})
      }),
    )
    renderPage()
    expect(await screen.findByRole('link', { name: '查看冻结影响分析' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/impact?run=${baseRun.impact_run_id}`,
    )
    expect(screen.getByRole('link', { name: '查看计划运行' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/tasks?run=${planRunId}&focus=${planId}`,
    )
    expect(screen.getByRole('link', { name: '查看发布判断' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/release?decision=frozen-decision`,
    )
    expect(await screen.findByRole('link', { name: '查看节点执行证据 1' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/reports?execution=${executionId}&node=health&attempt=2`,
    )
    expect(screen.getByRole('link', { name: '查看运行项证据 2' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/tasks?run=${planRunId}&item=${runItemId}`,
    )
    expect(screen.getByRole('link', { name: '打开生成工作流 generated-workflow' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/workflows?focus=generated-workflow`,
    )
    expect(screen.getByRole('link', { name: '打开生成用例 generated-case' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/assets?type=case&focus=generated-case&version=draft`,
    )
    expect(screen.getByText('javascript:alert(1)')).toBeVisible()
    expect(screen.queryByRole('link', { name: 'javascript:alert(1)' })).not.toBeInTheDocument()
    expect(screen.getByText('execution://run/item/1')).toBeVisible()
    expect(screen.getByText(baseRun.source_fingerprint)).toBeVisible()
    expect(writes).toBe(0)
  })

  it.each(['foreign', 'unavailable'] as const)(
    'does not link %s execution evidence to the current chain',
    async (kind) => {
      const executionId = '00000000-0000-4000-8000-000000007101'
      const parentId = '00000000-0000-4000-8000-000000007102'
      const run: ChangeRegressionRun = {
        ...baseRun,
        test_plan_run_id: parentId,
        failure_triage: {
          algorithm_version: 's47-failure-triage-v2',
          primary_classification: 'ASSERTION_FAILURE',
          confidence: 0.8,
          secondary_candidates: [],
          reason_codes: [],
          affected_service: null,
          affected_operation: null,
          evidence_refs: [`flowtest://runs/${executionId}/nodes/check?attempt=1`],
          retry_signal: false,
          recommended_action: 'Review evidence',
          recommended_regression: [],
        },
      }
      installHandlers(
        () => run,
        () => undefined,
      )
      server.use(
        http.get(`/api/v1/projects/${project.id}/test-plan-runs/${parentId}`, () =>
          kind === 'unavailable'
            ? HttpResponse.json(
                { error: { message: 'Evidence unavailable', trace_id: 'missing-parent' } },
                { status: 503 },
              )
            : HttpResponse.json({
                run: { id: parentId, project_id: project.id, test_plan_id: planId },
                items: [],
              }),
        ),
      )
      renderPage()
      const expected =
        kind === 'unavailable'
          ? '运行证据未提供，暂不能确认引用归属'
          : '原引用不属于本链路的计划运行，保留原文'
      expect(await screen.findByText(expected)).toBeVisible()
      expect(screen.queryByRole('link', { name: /查看节点执行证据/ })).not.toBeInTheDocument()
      expect(screen.getByText(`flowtest://runs/${executionId}/nodes/check?attempt=1`)).toBeVisible()
      if (kind === 'unavailable') expect(screen.getByText('Trace ID: missing-parent')).toBeVisible()
    },
  )

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
      oracle_reachability: ['conditional_assert' as const],
      recommended_existing_assets: asset
        ? [
            {
              target_type: 'workflow' as const,
              target_id: plan.items[0].target_id,
              target_version: plan.items[0].target_version,
              workflow_version: plan.items[0].workflow_version ?? plan.items[0].target_version,
            },
          ]
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
    expect(document.body.textContent).toContain('Conditional Assert')
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
            oracle_reachability: ['direct_oracle'],
            recommended_existing_assets: [],
            waiver: {
              id: '00000000-0000-4000-8000-000000003099',
              revision: 2,
              supersedes_waiver_id: '00000000-0000-4000-8000-000000003098',
              reason: '人工确认风险并安排补偿回归',
              approved_by: user.id,
              approved_at: '2026-08-23T01:30:00Z',
              expires_at: null,
            },
          },
        ],
      },
      semantic_gap_waivers: [
        {
          id: '00000000-0000-4000-8000-000000003099',
          gap_key: 'gap-waiver',
          revision: 2,
          supersedes_waiver_id: '00000000-0000-4000-8000-000000003098',
          reason: '人工确认风险并安排补偿回归',
          approved_by_id: user.id,
          approved_at: '2026-08-23T01:30:00Z',
          expires_at: null,
          operation_identity: {},
          semantic_requirement: {},
          requirement_fingerprint: 'd'.repeat(64),
          active: true,
        },
      ],
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
    expect(document.body.textContent).toContain('Revision 2')
    expect(document.body.textContent).toContain('Active')
    expect(buttonByText('人工批准')).toBeEnabled()
  })

  it('shows version mismatch, regeneration evidence and expired waiver renewal', async () => {
    const operation = baseRun.selection_summary.semantic_coverage_scopes?.[0]?.operation ?? null
    const target = baseRun.selection_summary.semantic_coverage_scopes?.[0]?.target ?? null
    const reviewRun: ChangeRegressionRun = {
      ...structuredClone(baseRun),
      selection_summary: {
        ...structuredClone(baseRun.selection_summary),
        semantic_coverage_basis: 'runtime_node_evidence',
        semantic_coverage_test_plan_run_id: '00000000-0000-4000-8000-000000003088',
        runtime_coverage: {
          evidence_chain:
            'test_plan_run_item>workflow_execution>workflow_node_execution>node_result_observation',
          passed_run_item_count: 1,
          selected_run_item_count: 1,
          workflow_execution_count: 1,
          passed_api_node_count: 1,
          matched_semantic_fact_count: 0,
        },
        unresolved_current_plan_gap_count: 1,
        operation_regenerations: [
          {
            change_key: 'openapi:orders:query.page.maximum',
            item_id: itemId,
            status: 'regenerated',
            old_design_fingerprint: '1'.repeat(64),
            design_fingerprint: '2'.repeat(64),
            contract_fingerprint: 'b'.repeat(64),
            scenario_count: 4,
            oracle_count: 2,
          },
        ],
        current_plan_gaps: [
          {
            change_key: 'openapi:orders:query.page.maximum',
            gap_key: 'gap-renew',
            operation,
            target,
            semantic_requirement: {
              semantic_value: '999',
              expected_category: 'success',
              oracle_set_fingerprint: 'c'.repeat(64),
            },
            requirement_fingerprint: 'd'.repeat(64),
            coverage_status: 'VERSION_MISMATCH',
            project_known_coverage: 'VERSION_MISMATCH',
            current_test_plan_coverage: 'VERSION_MISMATCH',
            oracle_reachability: ['unknown_graph'],
            recommended_existing_assets: [
              {
                target_type: 'workflow',
                target_id: plan.items[0].target_id,
                target_version: 2,
                workflow_version: 2,
              },
            ],
            waiver: null,
          },
        ],
      },
      semantic_gap_waivers: [
        {
          id: '00000000-0000-4000-8000-000000003098',
          gap_key: 'gap-renew',
          revision: 1,
          supersedes_waiver_id: null,
          reason: '历史人工豁免现已过期',
          approved_by_id: user.id,
          approved_at: '2026-08-22T01:30:00Z',
          expires_at: '2026-08-22T02:30:00Z',
          operation_identity: {},
          semantic_requirement: {},
          requirement_fingerprint: 'd'.repeat(64),
          active: false,
        },
      ],
    }
    installHandlers(
      () => reviewRun,
      () => undefined,
    )
    renderPage()

    expect(await screen.findByText('Proposal 已重新生成')).toBeVisible()
    expect(document.body.textContent).toContain('4 Scenario / 2 Oracle')
    expect(document.body.textContent).toContain('VERSION_MISMATCH')
    expect(document.body.textContent).toContain('Replace Plan Version · workflow v2')
    expect(document.body.textContent).toContain('Coverage Basis: 实际节点证据')
    expect(document.body.textContent).toContain('Runtime Match: 0 facts · 1 passed API nodes')
    expect(document.body.textContent).toContain('Unknown Graph')
    expect(buttonByText('Renew Waiver')).toBeDisabled()
    expect(document.body.textContent).toContain('Revision 1 已失效')
    expect(document.body.textContent).toContain('Expired')
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
    expect(screen.getAllByText('unresolved')).toHaveLength(6)
    expect(screen.getByText('-')).toBeVisible()
    expect(screen.getAllByText('无').length).toBeGreaterThanOrEqual(3)
    expect(screen.getByText('待审核')).toBeVisible()
    expect(screen.getByText('未填写')).toBeVisible()
    expect(screen.getByText('否')).toBeVisible()
    expect(screen.getAllByText('未定位')).toHaveLength(3)
    expect(screen.queryByText(/建议回归：/)).not.toBeInTheDocument()
  })

  it('persists selected regressions in the URL and rejects mismatched detail identities', async () => {
    installHandlers(
      () => baseRun,
      () => undefined,
    )
    const { result } = regressionHook()
    await waitFor(() => expect(result.current.regression.detail.data?.id).toBe(runId))
    const missingId = '00000000-0000-4000-8000-000000009999'
    server.use(
      http.get(`/api/v1/projects/${project.id}/change-regressions/${missingId}`, () =>
        HttpResponse.json(baseRun),
      ),
    )
    act(() => result.current.regression.setSelectedRunId(missingId))
    await waitFor(() => expect(result.current.location.search).toContain(`run=${missingId}`))
    await waitFor(() => expect(result.current.regression.detail.isError).toBe(true))
    expect(result.current.regression.detail.data).toBeUndefined()
    act(() => result.current.navigate(-1))
    await waitFor(() => expect(result.current.regression.detail.data?.id).toBe(runId))
  })

  it.each([
    ['create', 'success'],
    ['create', 'failure'],
    ['approve', 'success'],
    ['approve', 'failure'],
  ] as const)('ignores late %s %s feedback after navigation', async (action, outcome) => {
    installHandlers(
      () => baseRun,
      () => undefined,
    )
    let finish!: () => void
    let started!: () => void
    const pending = new Promise<void>((resolve) => {
      finish = resolve
    })
    const sent = new Promise<void>((resolve) => {
      started = resolve
    })
    server.use(
      http.post(
        `/api/v1/projects/${project.id}/change-regressions${action === 'approve' ? `/${runId}/approve` : ''}`,
        async () => {
          started()
          await pending
          return outcome === 'success'
            ? HttpResponse.json(baseRun)
            : HttpResponse.json(
                { error: { message: '旧链路操作失败', trace_id: 'stale-command' } },
                { status: 503 },
              )
        },
      ),
    )
    const { result } = regressionHook()
    await waitFor(() => expect(result.current.regression.canEdit).toBe(true))
    let command!: Promise<boolean>
    act(() => {
      command =
        action === 'approve'
          ? result.current.regression.approve(runId)
          : result.current.regression.createRun({
              title: '旧链路',
              source_ref: '',
              candidate_ref: 'old',
              git_diff: 'diff --git a/a b/a',
              openapi_diffs: [],
              schema_diffs: [],
              test_plan_id: planId,
              release_policy_id: policyId,
              generate_missing_tests: false,
            })
    })
    await sent
    act(() =>
      result.current.navigate(`/projects/${project.id}/change-regression?run=${runId}&sources=1`),
    )
    await waitFor(() => expect(result.current.location.search).toContain('sources=1'))
    await act(async () => {
      finish()
      await expect(command).resolves.toBe(false)
    })
    expect(result.current.location.search).toContain('sources=1')
    expect(document.querySelector('.ant-message-notice')).toBeNull()
  })

  it('renders incomplete historical triage as raw evidence without crashing or writing', async () => {
    installHandlers(
      () => ({
        ...baseRun,
        failure_triage: {
          algorithm_version: 's47-failure-triage-v2',
          primary_classification: 'LEGACY',
          evidence_refs: [],
        },
      }),
      () => undefined,
    )
    renderPage()
    expect(await screen.findByText('历史 Failure Triage 证据不含 S47 结构化分类')).toBeVisible()
    expect(screen.getByRole('region', { name: '历史失败分类原始证据' })).toBeVisible()
    expect(await screen.findByText('LEGACY', { exact: false })).toBeVisible()
  })

  it('distinguishes a blocked gate evaluation from a never-evaluated decision', async () => {
    installHandlers(
      () => ({
        ...baseRun,
        status: 'blocked',
        stages: [...baseRun.stages, stage('release_gate', 'blocked')],
      }),
      () => undefined,
    )
    renderPage()
    expect(await screen.findByText('评估已阻断，未生成独立发布判断')).toBeVisible()
    expect(screen.queryByRole('link', { name: '查看发布判断' })).not.toBeInTheDocument()
  })

  it('reports review decisions and action failures through the hook', async () => {
    let rejectCalls = 0
    const addPayloads: unknown[] = []
    const waiverPayloads: unknown[] = []
    const operationPayloads: unknown[] = []
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
        `/api/v1/projects/${project.id}/change-regressions/${runId}/operation-selection`,
        async ({ request }) => {
          operationPayloads.push(await request.json())
          return HttpResponse.json(baseRun)
        },
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
          targetVersion: plan.items[0].target_version,
          workflowVersion: plan.items[0].workflow_version ?? plan.items[0].target_version,
          environmentId: plan.items[0].environment_id ?? undefined,
        }),
      ).resolves.toBe(true)
      await expect(
        result.current.addToPlan({
          runId,
          gapKey: 'case-gap',
          targetType: 'test_case',
          targetId: itemId,
          targetVersion: 1,
          workflowVersion: 1,
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
        result.current.selectOperation({
          runId,
          changeKey: 'openapi:orders:query.page.maximum',
          apiDefinitionId: '00000000-0000-4000-8000-000000003010',
          apiVersion: 2,
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
          target_version: plan.items[0].target_version,
          workflow_version: plan.items[0].workflow_version,
          environment_id: plan.items[0].environment_id,
        },
      },
      {
        gap_key: 'case-gap',
        item: { target_type: 'case', target_id: itemId, target_version: 1 },
      },
    ])
    expect(waiverPayloads).toEqual([
      { gap_key: 'permanent-gap', reason: '人工确认风险并安排补偿回归' },
      {
        gap_key: 'expiring-gap',
        reason: '人工确认风险并安排补偿回归',
        expires_at: '2026-08-24T00:00:00Z',
      },
    ])
    expect(operationPayloads).toEqual([
      {
        change_key: 'openapi:orders:query.page.maximum',
        api_definition_id: '00000000-0000-4000-8000-000000003010',
        api_version: 2,
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
    http.get(`/api/v1/projects/${project.id}/impact/catalog`, () =>
      HttpResponse.json({
        targets: [
          {
            id: 'openapi-baseline',
            target_type: 'openapi_contract',
            name: '基线契约',
            version: 'base.yaml',
          },
          {
            id: 'openapi-current',
            target_type: 'openapi_contract',
            name: '当前契约',
            version: 'current.yaml',
          },
        ],
        schemas: [
          { id: 'graphql-baseline', protocol: 'graphql', name: 'GraphQL 基线', version: 1 },
          { id: 'graphql-current', protocol: 'graphql', name: 'GraphQL 当前', version: 2 },
          { id: 'grpc-baseline', protocol: 'grpc', name: 'Proto 基线', version: 1 },
          { id: 'grpc-current', protocol: 'grpc', name: 'Proto 当前', version: 2 },
        ],
      }),
    ),

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
  const rendered = render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <ProjectTestProvider section="change-regression">
            <ChangeRegressionPage />
          </ProjectTestProvider>
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
  return { ...rendered, queryClient }
}

async function fillRegressionForm(browser: ReturnType<typeof userEvent.setup>) {
  await openRegressionForm(browser)
  await waitFor(() => expect(screen.getByLabelText('链路名称')).toBeEnabled())
  await browser.type(screen.getByLabelText('链路名称'), '契约差异链路')
  await browser.type(screen.getByLabelText('候选版本'), 'contract:current')
  await selectSource(browser, '回归测试计划', 'S45 回归计划 · 1 项')
  await selectSource(browser, 'Release Policy', 'S45 Release Gate')
}

async function selectSource(
  browser: ReturnType<typeof userEvent.setup>,
  label: string,
  option: string,
) {
  await browser.click(screen.getByRole('combobox', { name: label }))
  const popup = document.querySelector<HTMLElement>(
    '.ant-select-dropdown:not(.ant-select-dropdown-hidden)',
  )!
  await browser.click(
    await within(popup).findByText(option, { selector: '.ant-select-item-option-content' }),
  )
}

async function openRegressionForm(browser: ReturnType<typeof userEvent.setup>) {
  const action = await screen.findByRole('button', { name: '新建回归链路' })
  await waitFor(() => expect(action).toBeEnabled())
  await browser.click(action)
}

function regressionHook() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <ProjectTestProvider section="change-regression">{children}</ProjectTestProvider>
        </QueryClientProvider>
      </AntdApp>
    )
  }
  return renderHook(
    () => {
      const [params] = useSearchParams()
      return {
        regression: useChangeRegression(params.get('run') ?? undefined),
        navigate: useNavigate(),
        location: useLocation(),
      }
    },
    { wrapper: Wrapper },
  )
}
