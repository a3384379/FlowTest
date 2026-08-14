import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
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
  it('renders an immutable historical decision and its explainable evidence', async () => {
    handlers()
    renderPage()

    expect(await screen.findByRole('heading', { name: '发布门禁' })).toBeVisible()
    expect(screen.getByText(/不可变快照/)).toBeVisible()
    expect(await screen.findByText('v3.0.0-rc.1')).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: '查看证据' }))

    const dialog = await screen.findByRole('dialog', { name: '发布判断证据' })
    await waitFor(() => expect(within(dialog).getByText('Quality Gate 已通过')).toBeVisible())
    expect(within(dialog).getByText('QUALITY_GATE_PASSED')).toBeVisible()
    expect(within(dialog).getByText(/历史判断只读/)).toBeVisible()
    expect(within(dialog).queryByRole('button', { name: /编辑|删除/ })).not.toBeInTheDocument()
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
      http.get('/api/v1/execution-fabric/tasks', () => {
        disabledEvidenceRequest()
        return HttpResponse.json(page([]))
      }),
    )

    renderPage()

    expect(await screen.findByRole('heading', { name: '发布门禁' })).toBeVisible()
    await waitFor(() => expect(screen.getByText('v3.0.0-rc.1')).toBeVisible())
    expect(disabledEvidenceRequest).not.toHaveBeenCalled()
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
    pact_broker: false,
    ...overrides,
  }
  server.use(
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
    http.get(`/api/v1/projects/${project.id}/release-risks`, () =>
      HttpResponse.json(page([{ id: releaseRiskId, title: '候选风险', score: 25 }])),
    ),
    http.get(`/api/v1/projects/${project.id}/performance-runs`, () =>
      HttpResponse.json(page([{ id: performanceRunId, status: 'passed', scenario_version: 3 }])),
    ),
    http.get('/api/v1/execution-fabric/tasks', () =>
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

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <ProjectTestProvider section="release">
            <ReleaseGatePage />
          </ProjectTestProvider>
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
}
