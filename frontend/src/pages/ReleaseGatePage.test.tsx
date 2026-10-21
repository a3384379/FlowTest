import type { ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useReleaseGate } from '../features/release-gate/use-release-gate'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import type { V3FeatureFlags } from '../features/capabilities/capability-service'
import type { ReleaseDecision, ReleasePolicy } from '../features/release-gate/release-gate-service'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { project, user } from '../test/fixtures'
import { server } from '../test/server'
import ReleaseGatePage from './ReleaseGatePage'

const policyId = '00000000-0000-4000-8000-000000000301'
const qualityGateId = '00000000-0000-4000-8000-000000000302'
const qualityRunId = '00000000-0000-4000-8000-000000000303'
const deploymentCheckId = '00000000-0000-4000-8000-000000000304'
const impactRunId = '00000000-0000-4000-8000-000000000305'
const releaseRiskId = '00000000-0000-4000-8000-000000000306'
const performanceRunId = '00000000-0000-4000-8000-000000000307'
const runnerTaskId = '00000000-0000-4000-8000-000000000308'

const policy: ReleasePolicy = {
  id: policyId,
  project_id: project.id,
  name: 'V3 GA 门禁',
  enabled: true,
  quality_gate_id: qualityGateId,
  require_quality_gate: true,
  require_contract_compatibility: true,
  require_impact_evidence: true,
  min_impact_coverage_percent: 80,
  require_release_risk: true,
  max_release_risk_score: 50,
  require_performance_evidence: true,
  require_runner_evidence: true,
  created_by_id: user.id,
  created_at: '2026-08-13T01:00:00Z',
  updated_at: '2026-08-13T01:00:00Z',
}

const decision: ReleaseDecision = {
  id: '00000000-0000-4000-8000-000000000309',
  project_id: project.id,
  release_policy_id: policyId,
  candidate_ref: 'v3.0.0-rc.1',
  status: 'pass',
  policy_snapshot: {
    snapshot_version: 'release_decision_v1',
    policy_id: policyId,
    name: policy.name,
    quality_gate_id: qualityGateId,
    require_quality_gate: true,
    require_contract_compatibility: true,
    require_impact_evidence: true,
    min_impact_coverage_percent: 80,
    require_release_risk: true,
    max_release_risk_score: 50,
    require_performance_evidence: true,
    require_runner_evidence: true,
    policy_updated_at: '2026-08-13T01:00:00Z',
  },
  evidence_snapshot: {
    snapshot_version: 'release_decision_v1',
    quality_gate: null,
    contract_compatibility: null,
    impact: null,
    release_risk: null,
    performance: null,
    runner: null,
  },
  reasons: [
    {
      code: 'QUALITY_GATE_PASSED',
      evidence_type: 'quality_gate',
      status: 'passed',
      message: 'Quality Gate 已通过',
      actual: 'passed',
      expected: 'passed',
    },
  ],
  fingerprint: 'a'.repeat(64),
  test_plan_run_id: qualityRunId,
  deployment_check_id: deploymentCheckId,
  impact_run_id: impactRunId,
  release_risk_id: releaseRiskId,
  performance_run_id: performanceRunId,
  runner_task_id: runnerTaskId,
  created_by_id: user.id,
  created_at: '2026-08-13T01:00:00Z',
}

describe('ReleaseGatePage', () => {
  it.each(['性能运行', 'Runner 任务'])(
    'shows the retained %s search after closing and reopening the decision dialog',
    async (label) => {
      handlers()
      renderPage()
      const browser = userEvent.setup()
      await browser.click(await screen.findByRole('button', { name: '生成发布判断' }))
      let dialog = await screen.findByRole('dialog', { name: '生成发布判断' })
      const input = within(dialog).getByRole('searchbox', { name: `${label}跨页搜索` })
      await browser.type(input, 'cancelled{Enter}')
      await browser.click(within(dialog).getByRole('button', { name: 'Cancel' }))
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
      await browser.click(screen.getByRole('button', { name: '生成发布判断' }))
      dialog = await screen.findByRole('dialog', { name: '生成发布判断' })
      expect(within(dialog).getByRole('searchbox', { name: `${label}跨页搜索` })).toHaveValue(
        'cancelled',
      )
    },
  )
  it('renders an immutable historical decision and its explainable evidence', async () => {
    handlers()
    renderPage()

    expect(await screen.findByRole('heading', { name: '发布门禁' })).toBeVisible()
    expect(screen.getByText(/不可变快照/)).toBeVisible()
    expect(await screen.findByText('v3.0.0-rc.1')).toBeVisible()
    const latest = screen.getByRole('region', { name: '最新判断的冻结证据' })
    expect(within(latest).getByText('Quality Gate 已通过')).toBeVisible()
    expect(within(latest).getByText(/不会触发生产部署/)).toBeVisible()
    expect(within(latest).queryByRole('button', { name: /编辑|删除|部署/ })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '查看证据' }))

    const dialog = await screen.findByRole('dialog', { name: '发布判断证据' })
    await waitFor(() => expect(within(dialog).getByText('Quality Gate 已通过')).toBeVisible())
    expect(within(dialog).getByText('QUALITY_GATE_PASSED')).toBeVisible()
    expect(within(dialog).getByText(/历史判断只读/)).toBeVisible()
    expect(within(dialog).queryByRole('button', { name: /编辑|删除/ })).not.toBeInTheDocument()
  })

  it('shows blocking evidence before passing evidence in the frozen decision workspace', async () => {
    handlers()
    server.use(
      http.get(`/api/v1/projects/${project.id}/release-decisions`, () =>
        HttpResponse.json({
          items: [
            {
              ...decision,
              status: 'block',
              reasons: [
                ...decision.reasons,
                {
                  code: 'CONTRACT_EVIDENCE_MISSING',
                  evidence_type: 'contract_compatibility',
                  status: 'blocked',
                  message: '必需契约证据未提供',
                  expected: 'present',
                  actual: null,
                },
              ],
            },
          ],
          total: 1,
          page: 1,
          page_size: 100,
        }),
      ),
    )
    renderPage()
    await screen.findByText('必需契约证据未提供')
    const latest = screen.getByRole('region', { name: '最新判断的冻结证据' })
    const rows = within(latest).getAllByRole('row')
    expect(rows[1]).toHaveTextContent('必需契约证据未提供')
    expect(rows[1]).toHaveTextContent('阻断')
    expect(within(latest).getByText('BLOCK')).toBeVisible()
  })

  it('creates a typed release policy with the configured thresholds', async () => {
    let created: Record<string, unknown> | null = null
    handlers()
    server.use(
      http.post(`/api/v1/projects/${project.id}/release-policies`, async ({ request }) => {
        created = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...policy, ...created }, { status: 201 })
      }),
    )
    renderPage()
    const browser = userEvent.setup()
    await screen.findByText('V3 GA 门禁')

    await browser.click(screen.getByRole('button', { name: /新建策略/ }))
    const dialog = await screen.findByRole('dialog', { name: '新建发布策略' })
    await browser.type(within(dialog).getByLabelText('策略名称'), '生产发布策略')
    await browser.click(within(dialog).getByLabelText('Quality Gate'))
    await browser.click(await screen.findByText('主线质量门禁'))
    await browser.click(within(dialog).getByRole('button', { name: 'OK' }))

    await waitFor(() =>
      expect(created).toMatchObject({
        name: '生产发布策略',
        quality_gate_id: qualityGateId,
        min_impact_coverage_percent: 80,
        max_release_risk_score: 50,
        require_quality_gate: true,
        require_contract_compatibility: true,
        require_impact_evidence: true,
        require_release_risk: true,
      }),
    )
  })

  it('binds all selected evidence when creating a release decision', async () => {
    let created: Record<string, unknown> | null = null
    handlers()
    server.use(
      http.post(`/api/v1/projects/${project.id}/release-decisions`, async ({ request }) => {
        created = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(decision, { status: 201 })
      }),
    )
    renderPage()
    const browser = userEvent.setup()
    await screen.findByText('V3 GA 门禁')

    await browser.click(screen.getByRole('button', { name: '生成发布判断' }))
    const dialog = await screen.findByRole('dialog', { name: '生成发布判断' })
    await chooseOption(browser, dialog, '发布策略', 'V3 GA 门禁')
    await browser.type(within(dialog).getByLabelText('候选版本'), 'v3.0.0-rc.2')
    await chooseEvidence(browser, dialog, 'Quality Gate 运行', '00000000 · passed')
    await chooseEvidence(browser, dialog, '契约兼容判断', '3.0.0 · safe')
    await chooseEvidence(browser, dialog, 'Impact Run', '结算影响 · completed')
    await chooseEvidence(browser, dialog, 'Release Risk', '候选风险 · 25')
    await chooseEvidence(browser, dialog, '性能运行', 'v3 · passed')
    await chooseEvidence(browser, dialog, 'Runner 任务', '00000000 · succeeded · fence 7')
    await waitFor(() => expect(within(dialog).getByRole('button', { name: 'OK' })).toBeEnabled())
    await browser.click(within(dialog).getByRole('button', { name: 'OK' }))

    await waitFor(() =>
      expect(created).toEqual({
        release_policy_id: policyId,
        candidate_ref: 'v3.0.0-rc.2',
        test_plan_run_id: qualityRunId,
        deployment_check_id: deploymentCheckId,
        impact_run_id: impactRunId,
        release_risk_id: releaseRiskId,
        performance_run_id: performanceRunId,
        runner_task_id: runnerTaskId,
      }),
    )
  })

  it('allows an optional quality policy without selecting a Quality Gate', async () => {
    let created: Record<string, unknown> | null = null
    handlers()
    server.use(
      http.post(`/api/v1/projects/${project.id}/release-policies`, async ({ request }) => {
        created = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...policy, ...created }, { status: 201 })
      }),
    )
    renderPage()
    const browser = userEvent.setup()
    await screen.findByText('V3 GA 门禁')

    await browser.click(screen.getByRole('button', { name: /新建策略/ }))
    const dialog = await screen.findByRole('dialog', { name: '新建发布策略' })
    await browser.type(within(dialog).getByLabelText('策略名称'), '可选证据策略')
    await browser.click(within(dialog).getByLabelText('要求 Quality Gate'))
    await browser.click(within(dialog).getByRole('button', { name: 'OK' }))

    await waitFor(() =>
      expect(created).toMatchObject({
        name: '可选证据策略',
        quality_gate_id: null,
        require_quality_gate: false,
      }),
    )
  })

  it('does not request evidence APIs for disabled V3 capabilities', async () => {
    const disabledEvidenceRequest = vi.fn()
    handlers({
      runner_fabric: false,
      performance_lab: false,
      contract_hub: false,
      impact_engine: false,
      quality_intelligence: false,
    })
    server.use(
      http.get(`/api/v1/projects/${project.id}/contract-hub/deployment-checks`, () => {
        disabledEvidenceRequest()
        return HttpResponse.json(page([]))
      }),
      http.get(`/api/v1/projects/${project.id}/impact/runs`, () => {
        disabledEvidenceRequest()
        return HttpResponse.json(page([]))
      }),
      http.get(`/api/v1/projects/${project.id}/release-risks`, () => {
        disabledEvidenceRequest()
        return HttpResponse.json(page([]))
      }),
      http.get(`/api/v1/projects/${project.id}/performance-runs`, () => {
        disabledEvidenceRequest()
        return HttpResponse.json(page([]))
      }),
      http.get(`/api/v1/projects/${project.id}/release-runner-evidence`, () => {
        disabledEvidenceRequest()
        return HttpResponse.json(page([]))
      }),
    )

    renderPage()

    expect(await screen.findByRole('heading', { name: '发布门禁' })).toBeVisible()
    await waitFor(() => expect(screen.getByText('v3.0.0-rc.1')).toBeVisible())
    expect(disabledEvidenceRequest).not.toHaveBeenCalled()
  })
  it('opens a specific historical decision outside the loaded list without creating a decision', async () => {
    handlers()
    const old = {
      ...decision,
      id: 'old-decision',
      candidate_ref: '历史候选-旧版本',
      status: 'block' as const,
      fingerprint: 'b'.repeat(64),
    }
    let writes = 0
    server.use(
      http.get(`/api/v1/projects/${project.id}/release-decisions/old-decision`, () =>
        HttpResponse.json(old),
      ),
      http.post(`/api/v1/projects/${project.id}/release-decisions`, () => {
        writes += 1
        return HttpResponse.json(decision)
      }),
    )
    renderPage(`/projects/${project.id}/release?decision=old-decision`)
    const dialog = await screen.findByRole('dialog', { name: '发布判断证据' })
    await waitFor(() => expect(within(dialog).getByText('历史候选-旧版本')).toBeVisible())
    expect(within(dialog).getByText(old.fingerprint)).toBeVisible()
    expect(within(dialog).queryByText(decision.candidate_ref)).not.toBeInTheDocument()
    await userEvent.setup().click(within(dialog).getByRole('tab', { name: '冻结策略' }))
    expect(within(dialog).getByRole('region', { name: '此判断的策略快照' })).toHaveTextContent(
      'release_decision_v1',
    )
    expect(writes).toBe(0)
  })

  it('shows policy requirements and distinguishes unavailable evidence without selecting defaults', async () => {
    handlers({ impact_engine: false })
    server.use(
      http.get(`/api/v1/projects/${project.id}/release-policies`, () =>
        HttpResponse.json([
          {
            ...policy,
            require_contract_compatibility: false,
            require_release_risk: false,
            require_runner_evidence: false,
          },
        ]),
      ),
      http.get(`/api/v1/projects/${project.id}/performance-runs`, () =>
        HttpResponse.json(
          { error: { message: 'Performance catalog unavailable', trace_id: 'perf-unavailable' } },
          { status: 503 },
        ),
      ),
    )
    renderPage()
    const browser = userEvent.setup()
    await browser.click(await screen.findByRole('button', { name: '生成发布判断' }))
    const dialog = await screen.findByRole('dialog', { name: '生成发布判断' })
    await chooseOption(browser, dialog, '发布策略', policy.name)
    expect(await within(dialog).findByText('必需证据：3 类')).toBeVisible()
    expect(within(dialog).getByText('影响分析能力已关闭')).toBeVisible()
    expect(within(dialog).getByText(/Performance catalog unavailable/)).toBeVisible()
    expect(within(dialog).getByText('Trace ID: perf-unavailable')).toBeVisible()
    expect(
      within(dialog).getByText('缺失必需证据仍可评估，结果将由后端按冻结策略判断为 BLOCK'),
    ).toBeVisible()
    expect(within(dialog).getByRole('region', { name: '提交前冻结对象摘要' })).toHaveTextContent(
      '未提供',
    )
  })

  it('uses a verified exact evidence ID outside the catalog and reports invalid identities without writes', async () => {
    handlers()
    const exactId = '00000000-0000-4000-8000-000000000399'
    let detailReads = 0
    let writes = 0
    server.use(
      http.get(`/api/v1/projects/${project.id}/performance-runs/${exactId}`, () => {
        detailReads++
        return HttpResponse.json({
          id: exactId,
          project_id: project.id,
          status: 'passed',
          scenario_version: 42,
        })
      }),
      http.post(`/api/v1/projects/${project.id}/*`, () => {
        writes++
        return HttpResponse.json({})
      }),
    )
    renderPage()
    const browser = userEvent.setup()
    await browser.click(await screen.findByRole('button', { name: '生成发布判断' }))
    const dialog = await screen.findByRole('dialog', { name: '生成发布判断' })
    await chooseOption(browser, dialog, '发布策略', policy.name)
    await browser.type(within(dialog).getByLabelText('候选版本'), 'lookup-must-not-evaluate')
    const input = within(dialog).getByRole('searchbox', { name: '性能运行精确ID' })
    await browser.type(input, exactId)
    await browser.keyboard('{Enter}')
    const chosen = await within(dialog).findByRole('button', { name: '使用已核对证据' })
    await browser.click(chosen)
    expect(within(dialog).getByRole('region', { name: '提交前冻结对象摘要' })).toHaveTextContent(
      exactId,
    )
    expect(detailReads).toBe(1)
    await browser.clear(input)
    await browser.type(input, 'invalid-id')
    await browser.keyboard('{Enter}')
    expect(await within(dialog).findByText('请输入完整有效的证据 UUID')).toBeVisible()
    expect(detailReads).toBe(1)
    expect(writes).toBe(0)
  })

  it('rejects runner source identity mismatches while preserving frozen evidence', async () => {
    handlers()
    server.use(
      http.get(`/api/v1/projects/${project.id}/release-decisions/${decision.id}`, () =>
        HttpResponse.json({
          ...decision,
          evidence_snapshot: {
            ...decision.evidence_snapshot,
            runner: {
              task_id: runnerTaskId,
              execution_id: 'original-execution',
              status: 'completed',
              fencing_token: 7,
              attempts: 1,
              completed_lease_count: 1,
              leases: [],
              completed_at: decision.created_at,
            },
          },
        }),
      ),
      http.get(`/api/v1/projects/${project.id}/release-runner-evidence/${runnerTaskId}`, () =>
        HttpResponse.json({ id: 'another-task', status: 'completed' }),
      ),
    )
    renderPage(`/projects/${project.id}/release?decision=${decision.id}&source=runner`)
    await waitFor(() => expect(screen.getByText('Runner任务响应身份不一致')).toBeVisible())
    expect(
      screen.queryByRole('region', { name: '项目 Runner 任务原始摘要' }),
    ).not.toBeInTheDocument()
    expect(screen.getAllByText('隔离令牌编号').length).toBeGreaterThan(0)
  })

  it('waits for risk ownership and keeps it retryable after a read error', async () => {
    handlers()
    let finish!: () => void
    const pending = new Promise<void>((resolve) => {
      finish = resolve
    })
    let reads = 0
    server.use(
      http.get(`/api/v1/projects/${project.id}/release-risks/${releaseRiskId}`, async () => {
        reads++
        if (reads === 1) {
          await pending
          return HttpResponse.json(
            { error: { message: 'Risk ownership unavailable', trace_id: 'risk-ownership' } },
            { status: 503 },
          )
        }
        return HttpResponse.json({
          id: releaseRiskId,
          project_id: project.id,
          impact_run_id: impactRunId,
        })
      }),
    )
    renderPage()
    const browser = userEvent.setup()
    await browser.click(await screen.findByRole('button', { name: '生成发布判断' }))
    const dialog = await screen.findByRole('dialog', { name: '生成发布判断' })
    await chooseEvidence(browser, dialog, 'Impact Run', '结算影响 · completed')
    await chooseEvidence(browser, dialog, 'Release Risk', '候选风险 · 25')
    await waitFor(() => expect(reads).toBe(1))
    const submit = within(dialog).getByRole('button', { name: 'OK' })
    expect(submit).toBeDisabled()
    await act(async () => {
      finish()
    })
    expect(await within(dialog).findByText('Trace ID: risk-ownership')).toBeVisible()
    expect(submit).toBeDisabled()
    await browser.click(within(dialog).getByRole('button', { name: '重试' }))
    await waitFor(() => expect(submit).toBeEnabled())
  })

  it('blocks a known risk and impact mismatch before submission and keeps the selected input', async () => {
    handlers()
    server.use(
      http.get(`/api/v1/projects/${project.id}/release-risks/${releaseRiskId}`, () =>
        HttpResponse.json({
          id: releaseRiskId,
          project_id: project.id,
          impact_run_id: 'foreign-impact',
        }),
      ),
    )
    let writes = 0
    server.use(
      http.post(`/api/v1/projects/${project.id}/release-decisions`, () => {
        writes++
        return HttpResponse.json(decision, { status: 201 })
      }),
    )
    renderPage()
    const browser = userEvent.setup()
    await browser.click(await screen.findByRole('button', { name: '生成发布判断' }))
    const dialog = await screen.findByRole('dialog', { name: '生成发布判断' })
    await chooseOption(browser, dialog, '发布策略', policy.name)
    await browser.type(within(dialog).getByLabelText('候选版本'), 'mismatch-is-not-ready')
    await chooseEvidence(browser, dialog, 'Impact Run', '结算影响 · completed')
    await chooseEvidence(browser, dialog, 'Release Risk', '候选风险 · 25')
    expect(await within(dialog).findByText('所选发布风险与影响分析不匹配')).toBeVisible()
    const submit = within(dialog).getByRole('button', { name: 'OK' })
    expect(submit).toBeDisabled()
    await browser.click(submit)
    expect(within(dialog).getByLabelText('候选版本')).toHaveValue('mismatch-is-not-ready')
    expect(writes).toBe(0)
  })

  it('selects performance evidence after the first page and preserves that exact ID when paging back', async () => {
    handlers()
    const laterId = '00000000-0000-4000-8000-000000000321'
    let created: Record<string, unknown> | null = null
    server.use(
      http.get(`/api/v1/projects/${project.id}/performance-runs`, ({ request }) => {
        const pageNumber = Number(new URL(request.url).searchParams.get('page') ?? 1)
        return HttpResponse.json({
          items: [
            {
              id: pageNumber === 2 ? laterId : performanceRunId,
              status: 'passed',
              scenario_version: pageNumber === 2 ? 21 : 3,
            },
          ],
          total: 21,
          page: pageNumber,
          page_size: 20,
        })
      }),
      http.post(`/api/v1/projects/${project.id}/release-decisions`, async ({ request }) => {
        created = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(decision, { status: 201 })
      }),
    )
    renderPage()
    const browser = userEvent.setup()
    await browser.click(await screen.findByRole('button', { name: '生成发布判断' }))
    const dialog = await screen.findByRole('dialog', { name: '生成发布判断' })
    const pagination = within(
      (await within(dialog).findByText('性能运行证据共 21 项')).closest(
        '.ant-pagination',
      )! as HTMLElement,
    )
    await browser.click(pagination.getByTitle('2'))
    await chooseEvidence(browser, dialog, '性能运行', 'v21 · passed')
    await browser.click(pagination.getByTitle('1'))
    expect(within(dialog).getByRole('region', { name: '提交前冻结对象摘要' })).toHaveTextContent(
      laterId,
    )
    await chooseOption(browser, dialog, '发布策略', policy.name)
    await browser.type(within(dialog).getByLabelText('候选版本'), 'page-two-evidence')
    await browser.click(within(dialog).getByRole('button', { name: 'OK' }))
    await waitFor(() =>
      expect(created).toMatchObject({
        performance_run_id: laterId,
        candidate_ref: 'page-two-evidence',
      }),
    )
  })

  it('opens six source identities from immutable decision evidence without new decisions', async () => {
    handlers()
    const snapshot = {
      ...decision,
      evidence_snapshot: {
        ...decision.evidence_snapshot,
        quality_gate: {
          test_plan_run_id: qualityRunId,
          quality_gate_id: qualityGateId,
          run_status: 'passed',
          status: 'passed',
          quality_summary: {},
          metrics: {},
          violations: [],
          evaluated_at: decision.created_at,
        },
        contract_compatibility: {
          check_id: deploymentCheckId,
          provider_service_id: 'provider',
          provider_version: 'old-v1',
          decision: 'safe',
          evidence: {},
          checked_at: decision.created_at,
        },
        impact: {
          run_id: impactRunId,
          status: 'completed',
          source_ref: 'old-source',
          source_fingerprint: 'old-impact',
          change_count: 1,
          summary: {},
          coverage_percent: 100,
          total_changes: 1,
          covered_changes: 1,
          gaps: [],
          created_at: decision.created_at,
        },
        release_risk: {
          risk_id: releaseRiskId,
          impact_run_id: impactRunId,
          algorithm_version: 'old-risk',
          score: 10,
          quality_score: 90,
          risk_level: 'low',
          factors: [],
          evidence: {},
          fingerprint: 'old-risk-fingerprint',
          created_at: decision.created_at,
        },
        performance: {
          run_id: performanceRunId,
          scenario_id: 'scenario',
          scenario_version: 3,
          status: 'passed',
          summary: {},
          threshold_results: [],
          gate_statuses: [],
          gate_evaluations: [],
          completed_at: decision.created_at,
        },
        runner: {
          task_id: runnerTaskId,
          execution_id: 'execution',
          status: 'completed',
          attempts: 1,
          fencing_token: 7,
          completed_lease_count: 1,
          leases: [],
          completed_at: decision.created_at,
        },
      },
    }
    server.use(
      http.get(`/api/v1/projects/${project.id}/release-decisions/${decision.id}`, () =>
        HttpResponse.json(snapshot),
      ),
    )
    let writes = 0
    server.use(
      http.post(`/api/v1/projects/${project.id}/*`, () => {
        writes++
        return HttpResponse.json({})
      }),
    )
    renderPage(`/projects/${project.id}/release?decision=${decision.id}`)
    const dialog = await screen.findByRole('dialog', { name: '发布判断证据' })
    expect(await within(dialog).findByRole('link', { name: '查看质量运行来源' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/tasks?run=${qualityRunId}`,
    )
    expect(within(dialog).getByRole('link', { name: '查看影响分析来源' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/impact?run=${impactRunId}`,
    )
    expect(within(dialog).getByRole('link', { name: '查看发布风险来源' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/quality?risk=${releaseRiskId}`,
    )
    expect(within(dialog).getByRole('link', { name: '查看性能运行来源' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/performance?run=${performanceRunId}`,
    )
    expect(within(dialog).getByRole('link', { name: '查看契约判断来源' })).toHaveAttribute(
      'href',
      expect.stringContaining('source=contract_compatibility'),
    )
    expect(within(dialog).getByRole('link', { name: '查看Runner任务来源' })).toHaveAttribute(
      'href',
      expect.stringContaining('source=runner'),
    )
    await waitFor(() => expect(within(dialog).getByText('old-v1')).toBeVisible())
    expect(writes).toBe(0)
  })

  it.each([
    ['policy', 'success'],
    ['policy', 'failure'],
    ['decision', 'success'],
    ['decision', 'failure'],
  ] as const)('ignores late %s %s after leaving the initiating route', async (action, outcome) => {
    handlers()
    let finish!: () => void
    let started!: () => void
    const pending = new Promise<void>((resolve) => {
      finish = resolve
    })
    const sent = new Promise<void>((resolve) => {
      started = resolve
    })
    const path = action === 'policy' ? 'release-policies' : 'release-decisions'
    server.use(
      http.post(`/api/v1/projects/${project.id}/${path}`, async () => {
        started()
        await pending
        return outcome === 'success'
          ? HttpResponse.json(action === 'policy' ? policy : decision, { status: 201 })
          : HttpResponse.json(
              { error: { message: 'Old release command failed', trace_id: 'old-release-command' } },
              { status: 503 },
            )
      }),
    )
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    function Wrapper({ children }: { children: ReactNode }) {
      return (
        <AntdApp>
          <QueryClientProvider client={client}>
            <ProjectTestProvider section="release">{children}</ProjectTestProvider>
          </QueryClientProvider>
        </AntdApp>
      )
    }
    const { result } = renderHook(
      () => ({ release: useReleaseGate(), navigate: useNavigate(), location: useLocation() }),
      { wrapper: Wrapper },
    )
    await waitFor(() => expect(result.current.release.canEdit).toBe(true))
    let operation!: Promise<boolean>
    act(() => {
      operation =
        action === 'policy'
          ? result.current.release.addPolicy(policy)
          : result.current.release.evaluate({
              release_policy_id: policyId,
              candidate_ref: 'old-candidate',
            })
    })
    await sent
    act(() => result.current.navigate(`/projects/${project.id}/release?tab=policies`))
    await waitFor(() => expect(result.current.location.search).toBe('?tab=policies'))
    await act(async () => {
      finish()
      await expect(operation).resolves.toBe(false)
    })
    expect(result.current.location.search).toBe('?tab=policies')
    expect(document.querySelector('.ant-message-notice')).toBeNull()
  })

  it('keeps missing linked evidence retryable and hides mutation access from viewers', async () => {
    handlers()
    let reads = 0
    server.use(
      http.get(`/api/v1/projects/${project.id}/permissions`, () =>
        HttpResponse.json({ effective_role: 'viewer', capabilities: ['read'] }),
      ),
      http.get(`/api/v1/projects/${project.id}/release-decisions/missing`, () => {
        reads += 1
        return HttpResponse.json(
          { error: { code: 'NOT_FOUND', message: '判断不存在', trace_id: 'test' } },
          { status: 404 },
        )
      }),
    )
    renderPage(`/projects/${project.id}/release?decision=missing`)
    await waitFor(() => expect(screen.getByText('发布判断读取失败')).toBeVisible())
    expect(screen.getByRole('button', { name: /新建策略/ })).toBeDisabled()
    await userEvent.setup().click(screen.getByRole('button', { name: /重\s*试/ }))
    await waitFor(() => expect(reads).toBe(2))
  })
})

async function chooseEvidence(
  browser: ReturnType<typeof userEvent.setup>,
  dialog: HTMLElement,
  label: string,
  option: string,
) {
  await chooseOption(browser, dialog, label, option)
}

async function chooseOption(
  browser: ReturnType<typeof userEvent.setup>,
  dialog: HTMLElement,
  label: string,
  option: string,
) {
  await browser.click(within(dialog).getByLabelText(label))
  const dropdown = await waitFor(() => {
    const element = document.querySelector<HTMLElement>(
      '.ant-select-dropdown:not(.ant-select-dropdown-hidden)',
    )
    expect(element).not.toBeNull()
    return element as HTMLElement
  })
  await browser.click(within(dropdown).getByText(option))
}

function handlers(overrides: Partial<V3FeatureFlags> = {}) {
  const featureFlags: V3FeatureFlags = {
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
    integration_flow: false,
    pact_broker: false,
    ...overrides,
  }
  server.use(
    http.get(`/api/v1/projects/${project.id}/release-decisions/${decision.id}`, () =>
      HttpResponse.json(decision),
    ),
    http.get('/api/v1/v3/features', () => HttpResponse.json(featureFlags)),
    http.get('/api/v1/projects', () => HttpResponse.json(page([project]))),
    http.get(`/api/v1/projects/${project.id}/release-policies`, () => HttpResponse.json([policy])),
    http.get(`/api/v1/projects/${project.id}/release-decisions`, () =>
      HttpResponse.json(page([decision])),
    ),
    http.get(`/api/v1/projects/${project.id}/quality-gates`, () =>
      HttpResponse.json([{ id: qualityGateId, name: '主线质量门禁' }]),
    ),
    http.get(`/api/v1/projects/${project.id}/test-plan-runs`, () =>
      HttpResponse.json(page([{ id: qualityRunId, status: 'passed' }])),
    ),
    http.get(`/api/v1/projects/${project.id}/contract-hub/deployment-checks`, () =>
      HttpResponse.json(
        page([{ id: deploymentCheckId, provider_version: '3.0.0', decision: 'safe' }]),
      ),
    ),
    http.get(`/api/v1/projects/${project.id}/impact/runs`, () =>
      HttpResponse.json(page([{ id: impactRunId, title: '结算影响', status: 'completed' }])),
    ),
    http.get(`/api/v1/projects/${project.id}/release-risks/${releaseRiskId}`, () =>
      HttpResponse.json({
        id: releaseRiskId,
        project_id: project.id,
        impact_run_id: impactRunId,
      }),
    ),
    http.get(`/api/v1/projects/${project.id}/release-risks`, () =>
      HttpResponse.json(page([{ id: releaseRiskId, title: '候选风险', score: 25 }])),
    ),
    http.get(`/api/v1/projects/${project.id}/performance-runs`, () =>
      HttpResponse.json(page([{ id: performanceRunId, status: 'passed', scenario_version: 3 }])),
    ),
    http.get(`/api/v1/projects/${project.id}/release-runner-evidence`, () =>
      HttpResponse.json(
        page([
          {
            id: runnerTaskId,
            project_id: project.id,
            status: 'succeeded',
            fencing_token: 7,
          },
        ]),
      ),
    ),
  )
}

function page<T>(items: T[]) {
  return { items, total: items.length, page: 1, page_size: 100 }
}

function renderPage(initialEntry?: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <ProjectTestProvider section="release" initialEntry={initialEntry}>
            <ReleaseGatePage />
          </ProjectTestProvider>
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
}
