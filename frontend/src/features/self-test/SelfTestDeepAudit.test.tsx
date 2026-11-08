import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App, ConfigProvider } from 'antd'
import { delay, http, HttpResponse } from 'msw'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { FlowSpecVisualProposal, TestCase, TestSuite } from '../../lib/api'
import QualityCenterPage from '../../pages/QualityCenterPage'
import ProjectTestProvider from '../../test/ProjectTestProvider'
import { authenticateTestUser } from '../../test/auth'
import {
  apiDefinition,
  environment,
  project,
  user,
  workflow,
  workflowDefinition,
} from '../../test/fixtures'
import { server } from '../../test/server'
import AssetDetailDrawer from '../test-assets/AssetDetailDrawer'
import FlowProposalReviewDialog from '../workflows/FlowProposalReviewDialog'
import SelfTestFixedWorkflow from './SelfTestFixedWorkflow'
import SelfTestInsights from './SelfTestInsights'
import SelfTestReportPanels from './SelfTestReportPanels'
import { selfTestKeys, selfTestScope, type SelfTestIdentity } from './self-test-query-keys'
import { useAuthStore } from '../auth/auth-store'
import {
  selfTestBatch,
  selfTestBinding,
  selfTestDigest,
  selfTestIds as ids,
  selfTestInstallation,
  selfTestPage,
  selfTestScenario,
  selfTestTemplate,
} from './self-test-test-fixtures'

const base = `/api/v1/projects/${project.id}/self-tests`
const entry = `/projects/${project.id}/quality?tab=selftest&mode=mcp_generation&binding=${ids.binding}&installation=${ids.installation}&batch=${ids.batch}`
const generation = {
  batch_id: ids.batch,
  generation_mode: 'deterministic_mcp',
  stage: 'ready',
  readiness: 'ready',
  reason_codes: [],
  host_status: 'available',
  tool_call_count: 1,
  proposals: [],
  sources: [],
  manifest: null,
  actions: selfTestBatch.actions,
}
const cancelled = {
  ...selfTestBatch,
  phase: 'cancelled' as const,
  generation_stage: 'cancelled' as const,
  verdict: 'blocked' as const,
  sealed_at: null,
  sealed_verdict: null,
  cleanup_status: 'pending' as const,
}
const runningScenario = {
  ...selfTestScenario,
  observed_status: 'running' as const,
  verification_status: 'pending' as const,
}

beforeEach(() => {
  authenticateTestUser(user)
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
    ),
    http.get(`${base}/templates`, () => HttpResponse.json(selfTestPage([selfTestTemplate]))),
    http.get(`${base}/bindings`, () => HttpResponse.json(selfTestPage([selfTestBinding]))),
    http.get(`${base}/installations/${ids.installation}`, () =>
      HttpResponse.json(selfTestInstallation),
    ),
    http.get(`${base}/installations/${ids.installation}/runs`, () =>
      HttpResponse.json(selfTestPage([selfTestBatch])),
    ),
    http.get(`${base}/runs/${ids.batch}`, () => HttpResponse.json(selfTestBatch)),
    http.get(`${base}/runs/${ids.batch}/generation`, () => HttpResponse.json(generation)),
    http.get(`${base}/runs/${ids.batch}/scenarios`, () =>
      HttpResponse.json(selfTestPage([selfTestScenario])),
    ),
  )
})

function identity(): SelfTestIdentity {
  const state = useAuthStore.getState()
  return {
    userId: state.user?.id ?? null,
    organizationId: state.organizationId,
    epoch: state.epoch,
    projectId: project.id,
  }
}
function Location() {
  const location = useLocation()
  return (
    <output aria-label="审计 URL">
      {location.pathname}
      {location.search}
    </output>
  )
}
function mount(
  content: React.ReactNode,
  initialEntry = entry,
  client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  }),
) {
  render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App>
        <QueryClientProvider client={client}>
          <ProjectTestProvider section="quality" initialEntry={initialEntry}>
            <Location />
            {content}
          </ProjectTestProvider>
        </QueryClientProvider>
      </App>
    </ConfigProvider>,
  )
  return client
}
function ReportJourney() {
  const location = useLocation()
  return location.pathname.endsWith('/reports') ? (
    <SelfTestReportPanels projectId={project.id} executionId={ids.execution} />
  ) : (
    <QualityCenterPage />
  )
}

describe('deep self-test frontend audit', () => {
  it('returns a page-two execution report to the original visible scenario page', async () => {
    const rows = Array.from({ length: 21 }, (_, index) => ({
      ...selfTestScenario,
      id: `00000000-0000-4000-8000-${String(300 + index).padStart(12, '0')}`,
      scenario_id: `ST-DEEP-${index + 1}`,
      title: `分页冻结场景 ${index + 1}`,
    }))
    const batch = {
      ...selfTestBatch,
      expected_count: rows.length,
      expected_scenario_set: rows.map(({ scenario_id, variant_key }) => ({
        scenario_id,
        variant_key,
      })),
      required_scenario_set: rows.map(({ scenario_id, variant_key }) => ({
        scenario_id,
        variant_key,
      })),
    }
    server.use(
      http.get(`${base}/runs/${ids.batch}`, () => HttpResponse.json(batch)),
      http.get(`${base}/runs/${ids.batch}/scenarios`, ({ request }) => {
        const params = new URL(request.url).searchParams
        const selected = rows.filter(
          (row) => !params.get('scenario_id') || params.get('scenario_id') === row.scenario_id,
        )
        const offset = (Number(params.get('page')) - 1) * 20
        return HttpResponse.json({
          ...selfTestPage(selected.slice(offset, offset + 20)),
          total: selected.length,
        })
      }),
      http.get(`${base}/runs/${ids.batch}/scenarios/ST-DEEP-21/executions/${ids.execution}`, () =>
        HttpResponse.json({ batch, scenario: rows[20], execution_id: ids.execution }),
      ),
    )
    mount(<ReportJourney />, `${entry}&page=2`)
    await screen.findByText('分页冻结场景 21')
    await userEvent.click(screen.getByRole('link', { name: /执行 1 ·/ }))
    await userEvent.click(await screen.findByRole('link', { name: '返回已核验自测批次' }))
    expect(await screen.findByText('分页冻结场景 21')).toBeVisible()
    expect(screen.getByLabelText('审计 URL')).toHaveTextContent('page=2')
    expect(screen.getByLabelText('审计 URL')).not.toHaveTextContent('scenario=')
  })

  it('closes initialization, recovery and green conclusions for mismatched selected scopes', async () => {
    const resume = vi.fn()
    server.use(
      http.get(`${base}/installations/${ids.installation}`, () =>
        HttpResponse.json({ ...selfTestInstallation, binding_id: ids.task, status: 'blocked' }),
      ),
      http.get(`${base}/runs/${ids.batch}`, () =>
        HttpResponse.json({ ...selfTestBatch, binding_id: ids.task }),
      ),
      http.post(`${base}/installations/${ids.installation}/resume`, () => {
        resume()
        return HttpResponse.json(selfTestInstallation)
      }),
    )
    mount(<QualityCenterPage />)
    await screen.findByText(/链接中的绑定、安装、批次或模式不一致/)
    expect.soft(screen.getByRole('button', { name: '初始化自测' })).toBeDisabled()
    expect.soft(screen.queryByText('当前冻结包核验已完成')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '查看安装' }))
    expect(screen.getByRole('button', { name: '继续初始化' })).toBeDisabled()
    expect(resume).not.toHaveBeenCalled()
  })

  it('keeps reading cancelled-batch native status until termination, then stops', async () => {
    let reads = 0
    server.use(
      http.get(`${base}/runs/${ids.batch}`, () => HttpResponse.json(cancelled)),
      http.get(`${base}/runs/${ids.batch}/scenarios`, () => {
        reads += 1
        return HttpResponse.json(
          selfTestPage([
            { ...runningScenario, observed_status: reads === 1 ? 'running' : 'cancelled' },
          ]),
        )
      }),
    )
    mount(<QualityCenterPage />)
    expect(await screen.findByText('原始执行：运行中')).toBeVisible()
    expect(await screen.findByText('原始执行：已取消', {}, { timeout: 6500 })).toBeVisible()
    const terminalReads = reads
    await act(async () => {
      await delay(2200)
    })
    expect(reads).toBe(terminalReads)
  })

  it('updates cancelled report relations from actual native status and stops at termination', async () => {
    let reads = 0
    server.use(
      http.get(`${base}/runs/${ids.batch}/scenarios/ST-MCP-023/executions/${ids.execution}`, () => {
        reads += 1
        return HttpResponse.json({
          batch: cancelled,
          scenario: { ...runningScenario, observed_status: reads === 1 ? 'running' : 'cancelled' },
          execution_id: ids.execution,
        })
      }),
    )
    mount(
      <SelfTestReportPanels projectId={project.id} executionId={ids.execution} />,
      `/projects/${project.id}/reports?execution=${ids.execution}&selfTestBatch=${ids.batch}&selfTestScenario=ST-MCP-023`,
    )
    expect(await screen.findByText('原始执行：运行中')).toBeVisible()
    expect(await screen.findByText('原始执行：已取消', {}, { timeout: 6500 })).toBeVisible()
    const terminalReads = reads
    await act(async () => {
      await delay(2200)
    })
    expect(reads).toBe(terminalReads)
  })

  it('stops bounded cancellation polling without inventing a native terminal state', async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    })
    const key = selfTestKeys.relation(identity(), ids.batch, 'ST-MCP-023', ids.execution)
    client.setQueryData(key, {
      batch: cancelled,
      scenario: runningScenario,
      execution_id: ids.execution,
    })
    client.getQueryCache().find({ queryKey: key, exact: true })!.setState({ dataUpdateCount: 299 })
    let reads = 0
    server.use(
      http.get(`${base}/runs/${ids.batch}/scenarios/ST-MCP-023/executions/${ids.execution}`, () => {
        reads += 1
        return HttpResponse.json({
          batch: cancelled,
          scenario: runningScenario,
          execution_id: ids.execution,
        })
      }),
    )
    mount(
      <SelfTestReportPanels projectId={project.id} executionId={ids.execution} />,
      `/projects/${project.id}/reports?execution=${ids.execution}&selfTestBatch=${ids.batch}&selfTestScenario=ST-MCP-023`,
      client,
    )
    await waitFor(() => expect(reads).toBe(1), { timeout: 6500 })
    await act(async () => {
      await delay(2200)
    })
    expect(reads).toBe(1)
    expect(screen.getByText('原始执行：运行中')).toBeVisible()
    expect(screen.queryByText('独立核验：符合预期')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '刷新独立核验' })).toBeEnabled()
  })

  it('does not carry a confirmed human revision document to another cached assisted batch', async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    })
    for (const id of [ids.batch, ids.task])
      client.setQueryData([...selfTestScope(identity()), 'insights', id, 1], {
        batch_id: id,
        manifest_digest: selfTestDigest,
        task_set_digest: selfTestDigest,
        template_version: '1.0.0',
        scope: 'full_pack',
        assisted_before_batch_id: ids.scenario,
        metrics: [],
        diagnostics: [],
        case_slots: [],
        comparisons: [],
        reason_codes: [],
      })
    mount(<AssistedJourney />, entry, client)
    await userEvent.click(await screen.findByRole('button', { name: '提交人工 Case 修订提案' }))
    const editor = within(screen.getByRole('dialog'))
    await userEvent.type(editor.getByRole('textbox', { name: '修订原因' }), '修正原批次变量')
    await userEvent.click(editor.getByRole('textbox', { name: '修订文档' }))
    await userEvent.paste('{"design":{},"test_cases":[{"name":"原批次","definition":{}}]}')
    await userEvent.click(editor.getByRole('checkbox'))
    expect(editor.getByRole('button', { name: '创建人工提案' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: '切换辅助批次' }))
    await waitFor(() =>
      expect(screen.getByLabelText('审计 URL')).toHaveTextContent(`batch=${ids.task}`),
    )
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '提交人工 Case 修订提案' }))
    const next = within(screen.getByRole('dialog'))
    expect(next.getByRole('textbox', { name: '修订原因' })).toHaveValue('')
    expect(next.getByRole('checkbox')).not.toBeChecked()
  })

  it('retains self-test context through Suite and Case and opens the pinned workflow definition', async () => {
    const item: TestCase = {
      id: ids.scenario,
      project_id: project.id,
      folder_id: null,
      name: '冻结 Case',
      description: '',
      tags: [],
      is_template: false,
      current_version: 2,
      created_by_id: user.id,
      created_at: workflow.created_at,
      updated_at: workflow.updated_at,
      draft_definition: {
        workflow_id: ids.task,
        workflow_version: 9,
        environment_id: environment.id,
        runtime_variables: {},
        runtime_headers: {},
      },
    }
    const suite: TestSuite = {
      id: ids.installation,
      project_id: project.id,
      folder_id: null,
      name: '冻结 Suite',
      description: '',
      tags: [],
      current_version: 1,
      created_by_id: user.id,
      created_at: workflow.created_at,
      updated_at: workflow.updated_at,
      draft_definition: { items: [] },
    }
    const snapshot = {
      suite: { id: suite.id, version: 1, fingerprint: selfTestDigest },
      plan_id: ids.task,
      cases: [
        {
          scenario_id: selfTestScenario.scenario_id,
          variant_key: 'default',
          case: { id: item.id, version: 2, fingerprint: selfTestDigest },
          workflow: { id: ids.task, version: 3, fingerprint: selfTestDigest },
          environment_id: environment.id,
          target_snapshot_digest: selfTestDigest,
        },
      ],
    }
    server.use(
      http.get(`${base}/runs/${ids.batch}`, () =>
        HttpResponse.json({ ...selfTestBatch, resource_snapshot: snapshot }),
      ),
      http.get(`/api/v1/projects/${project.id}/test-suites/${suite.id}`, () =>
        HttpResponse.json(suite),
      ),
      http.get(`/api/v1/projects/${project.id}/test-suites/${suite.id}/versions`, () =>
        HttpResponse.json([
          { version: 1, definition: { items: [{ test_case_id: item.id, test_case_version: 2 }] } },
        ]),
      ),
      http.get(`/api/v1/projects/${project.id}/test-cases/${item.id}`, () =>
        HttpResponse.json(item),
      ),
      http.get(`/api/v1/projects/${project.id}/test-cases/${item.id}/versions`, () =>
        HttpResponse.json([
          { version: 2, definition: { ...item.draft_definition, workflow_version: 3 } },
        ]),
      ),
      http.get(`/api/v1/projects/${project.id}/workflows/${ids.task}/versions`, () =>
        HttpResponse.json([
          {
            workflow_id: ids.task,
            version: 3,
            fingerprint: selfTestDigest,
            definition: { name: '原冻结流程第三版' },
          },
          {
            workflow_id: ids.task,
            version: 9,
            fingerprint: selfTestDigest,
            definition: { name: '不能替代的第九版' },
          },
        ]),
      ),
    )
    mount(
      <AssetJourney item={item} />,
      `/projects/${project.id}/assets?type=suite&focus=${suite.id}&version=1&selfTestBatch=${ids.batch}&selfTestReturn=${encodeURIComponent(entry.split('?')[1])}`,
    )
    await userEvent.click(await screen.findByRole('link', { name: item.name }))
    expect(screen.getByLabelText('审计 URL')).toHaveTextContent(`selfTestBatch=${ids.batch}`)
    const openWorkflow = await screen.findByRole('link', { name: '打开流程' })
    await userEvent.click(openWorkflow)
    expect(await screen.findByText(/原冻结流程第三版/)).toBeVisible()
    expect(screen.queryByText(/不能替代的第九版/)).not.toBeInTheDocument()
    expect(await screen.findByRole('link', { name: '返回已核验的自测范围' })).toBeVisible()
  })

  it('ignores late workflow Apply navigation after following the verified self-test backlink', async () => {
    let release!: () => void
    const pending = new Promise<void>((resolve) => {
      release = resolve
    })
    const visual = proposal()
    server.use(
      http.get(`/api/v1/projects/${project.id}/flow-specs/change-sets/proposals`, () =>
        HttpResponse.json({ items: [visual.proposal], next_cursor: null, page_size: 100 }),
      ),
      http.get(
        `/api/v1/projects/${project.id}/flow-specs/change-sets/${ids.execution}/visual-proposal`,
        () => HttpResponse.json(visual),
      ),
      http.post(
        `/api/v1/projects/${project.id}/flow-specs/change-sets/${ids.execution}/apply`,
        async () => {
          await pending
          return HttpResponse.json({
            change_set_id: ids.execution,
            workflow_id: workflow.id,
            draft_revision: 2,
            fingerprint: selfTestDigest,
            applied_at: workflow.updated_at,
          })
        },
      ),
      http.get(`${base}/runs/${ids.batch}/generation`, () =>
        HttpResponse.json({
          ...generation,
          proposals: [
            {
              change_set_id: ids.execution,
              item_id: null,
              route: 'flow_spec_visual',
              content_fingerprint: selfTestDigest,
              review_status: 'accepted',
              materialized_resource_id: workflow.id,
            },
          ],
        }),
      ),
    )
    const applied = vi.fn()
    const client = mount(
      <ApplyJourney onApplied={applied} />,
      `/projects/${project.id}/workflows?proposal=${ids.execution}&selfTestBatch=${ids.batch}`,
    )
    client.setQueryData(['workflows', project.id], { items: [workflow] })
    await userEvent.click(await screen.findByRole('button', { name: '应用到工作流草稿' }))
    await userEvent.click(
      await screen.findByRole('link', { name: '返回已核验的 MCP 自测生成批次' }),
    )
    await waitFor(() =>
      expect(screen.getByLabelText('审计 URL')).toHaveTextContent('/quality?tab=selftest'),
    )
    await act(async () => {
      release()
      await pending
    })
    await waitFor(() =>
      expect(client.getQueryState(['workflows', project.id])?.isInvalidated).toBe(true),
    )
    expect(applied).not.toHaveBeenCalled()
    expect(screen.queryByText('流程提案已应用到工作流草稿，可继续安全编辑')).not.toBeInTheDocument()
    expect(screen.getByLabelText('审计 URL')).toHaveTextContent('/quality?tab=selftest')
  })
})

function AssistedJourney() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  return (
    <>
      <button onClick={() => navigate(entry.replace(ids.batch, ids.task))}>切换辅助批次</button>
      <SelfTestInsights
        projectId={project.id}
        batch={{
          ...selfTestBatch,
          id: params.get('batch')!,
          phase: 'awaiting_review',
          generation_mode: 'host_llm_mcp',
          sealed_at: null,
        }}
      />
    </>
  )
}
function AssetJourney({ item }: { item: TestCase }) {
  const [params] = useSearchParams()
  const location = useLocation()
  if (location.pathname.endsWith('/workflows'))
    return <SelfTestFixedWorkflow projectId={project.id} />
  return (
    <AssetDetailDrawer
      projectId={project.id}
      kind={params.get('type') === 'suite' ? 'suite' : 'case'}
      id={params.get('focus')!}
      version={Number(params.get('version'))}
      workflows={[]}
      environments={[environment]}
      cases={[item]}
      history={{ loading: false, error: null, history: () => [], reload: vi.fn() }}
      canEdit={false}
      canExecute={false}
      onVersion={() => undefined}
      onClose={() => undefined}
      onEditCase={() => undefined}
      onEditSuite={() => undefined}
      onPlan={() => undefined}
    />
  )
}
function ApplyJourney({ onApplied }: { onApplied: () => void }) {
  const location = useLocation()
  if (!location.pathname.endsWith('/workflows')) return <p>已返回原自测范围</p>
  return (
    <FlowProposalReviewDialog
      open
      projectId={project.id}
      initialProposalId={ids.execution}
      resources={{
        environments: [environment],
        apis: [apiDefinition],
        workflows: [workflow],
        artifacts: [],
        credentials: [],
        graphqlSchemas: [],
        grpcDescriptors: [],
        eventSources: [],
      }}
      onClose={() => undefined}
      onApplied={onApplied}
      onOpenRawMapping={() => undefined}
    />
  )
}
function proposal(): FlowSpecVisualProposal {
  return {
    schema_version: 'flowtest-visual-flow-proposal-v1',
    existing_definition: workflowDefinition,
    proposed_definition: workflowDefinition,
    integration_plan: null,
    compilation: null,
    service_mappings: {},
    operation_mappings: {},
    operation_version_mappings: {},
    proposal: {
      id: ids.execution,
      project_id: project.id,
      title: '冻结审核流程',
      status: 'accepted',
      source_type: 'flow_spec',
      source_ref: 'mcp://selftest',
      source_fingerprint: selfTestDigest,
      target_workflow_id: workflow.id,
      target_revision: 1,
      target_snapshot_sha256: selfTestDigest,
      review_status: 'accepted',
      reviewed_by_id: user.id,
      reviewed_at: workflow.updated_at,
      applied_at: null,
      created_by_id: user.id,
      created_at: workflow.created_at,
      updated_at: workflow.updated_at,
      spec: {
        schema_version: 'flowtest-flow-spec-v1',
        fingerprint_version: 'flowtest-flow-spec-fingerprint-v3',
        project_id: project.id,
        name: '冻结审核流程',
        description: '',
        source_evidence: [],
        services: [],
        operations: [],
        nodes: [],
        edges: [],
        variables: {},
        settings: workflowDefinition.settings,
        bindings: [],
        parameters: [],
        assertions: [],
        cleanup: [],
        security_policy: { secret_refs_only: true, max_requests: 20, allow_private_network: false },
        confidence: { overall: 1, unresolved: [] },
      },
      validation: { valid: true, issues: [], warnings: [], requires_review: true },
      compatibility: {
        compatible: true,
        source_schema_version: 'flowtest-flow-spec-v1',
        target_schema_version: 'flowtest-flow-spec-v1',
        blockers: [],
        warnings: [],
        requires_review: true,
      },
      diff: [],
    },
  }
}
