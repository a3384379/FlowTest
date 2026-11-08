// Regression cases converted from the audit reproductions.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import ProjectTestProvider from '../../test/ProjectTestProvider'
import { authenticateTestUser } from '../../test/auth'
import { project, user } from '../../test/fixtures'
import { server } from '../../test/server'
import QualityCenterPage from '../../pages/QualityCenterPage'
import MCPMaterializedResult from '../mcp/MCPMaterializedResult'
import SelfTestReportPanels from './SelfTestReportPanels'
import SelfTestGenerationProgress from './SelfTestGenerationProgress'
import SelfTestProposalBacklink from './SelfTestProposalBacklink'
import SelfTestInsights from './SelfTestInsights'
import SelfTestAssistedEditor from './SelfTestAssistedEditor'
import SelfTestFixedWorkflow from './SelfTestFixedWorkflow'
import { parseBatch, parseGeneration } from './self-test-contract'
import {
  selfTestBatch,
  selfTestBinding,
  selfTestIds as ids,
  selfTestInstallation,
  selfTestPage,
  selfTestPreview,
  selfTestScenario,
  selfTestTemplate,
} from './self-test-test-fixtures'

const base = `/api/v1/projects/${project.id}/self-tests`
const entry = `/projects/${project.id}/quality?tab=selftest&mode=mcp_generation&binding=${ids.binding}&installation=${ids.installation}&batch=${ids.batch}`
const reportEntry = `/projects/${project.id}/reports?execution=${ids.execution}&selfTestBatch=${ids.batch}&selfTestScenario=ST-MCP-023`
const generation = parseGeneration({
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
})

function mount(content: React.ReactNode, initialEntry = entry) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  })
  const result = render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App>
        <QueryClientProvider client={client}>
          <ProjectTestProvider section="quality" initialEntry={initialEntry}>
            {content}
          </ProjectTestProvider>
        </QueryClientProvider>
      </App>
    </ConfigProvider>,
  )
  return { ...result, client }
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
    http.get(`${base}/runs/${ids.batch}/scenarios/ST-MCP-023/executions/${ids.execution}`, () =>
      HttpResponse.json({
        batch: selfTestBatch,
        scenario: selfTestScenario,
        execution_id: ids.execution,
      }),
    ),
  )
})

describe('self-test audit repairs', () => {
  it('rejects statistics whose scope disagrees with the frozen batch', async () => {
    mount(
      <SelfTestInsights
        projectId={project.id}
        batch={{ ...selfTestBatch, verification_scope: 'diagnostic_subset' }}
      />,
    )
    expect(await screen.findByText('统计来源或范围与冻结清单不符，请刷新批次。')).toBeVisible()
    expect(screen.queryByText(/0 \/ 0 · 未评估/)).not.toBeInTheDocument()
  })
  it('opens the requested frozen workflow and offers an authorized return inside its detail drawer', async () => {
    const workflow = { id: ids.task, version: 3, fingerprint: 'a'.repeat(64) }
    const origin = `tab=selftest&mode=mcp_generation&binding=${ids.binding}&installation=${ids.installation}&batch=${ids.batch}&category=mcp&page=2`
    server.use(
      http.get(`/api/v1/projects/${project.id}/workflows/${ids.task}/versions`, () =>
        HttpResponse.json([
          { ...workflow, workflow_id: ids.task, definition: { name: '冻结的第三版' } },
          {
            ...workflow,
            version: 9,
            workflow_id: ids.task,
            definition: { name: '不能冒用的新版本' },
          },
        ]),
      ),
      http.get(`${base}/runs/${ids.batch}`, () =>
        HttpResponse.json({
          ...selfTestBatch,
          resource_snapshot: {
            suite: { id: ids.installation, version: 1, fingerprint: 'a'.repeat(64) },
            plan_id: ids.task,
            cases: [
              {
                scenario_id: 'ST-MCP-023',
                variant_key: 'default',
                workflow,
                case: { id: ids.scenario, version: 2, fingerprint: 'a'.repeat(64) },
                environment_id: ids.binding,
                target_snapshot_digest: 'a'.repeat(64),
              },
            ],
          },
        }),
      ),
    )
    mount(
      <SelfTestFixedWorkflow projectId={project.id} />,
      `/projects/${project.id}/workflows?focus=${ids.task}&version=3&selfTestBatch=${ids.batch}&selfTestReturn=${encodeURIComponent(origin)}`,
    )
    const drawer = within(screen.getByRole('dialog'))
    expect(await drawer.findByText(/冻结的第三版/)).toBeVisible()
    expect(drawer.queryByText(/不能冒用的新版本/)).not.toBeInTheDocument()
    const link = await drawer.findByRole('link', { name: '返回已核验的自测范围' })
    expect(link).toHaveAttribute('href', expect.stringContaining('category=mcp&page=2'))
  })
  it('shows scoped denominators, unevaluated metrics, compiler inputs and observer field evidence', async () => {
    server.use(
      http.get(`${base}/runs/${ids.batch}/insights`, () =>
        HttpResponse.json({
          batch_id: ids.batch,
          manifest_digest: selfTestBatch.manifest_digest,
          task_set_digest: 'b'.repeat(64),
          template_version: '2.0.0',
          scope: 'diagnostic_subset',
          assisted_before_batch_id: null,
          metrics: [
            {
              key: 'api',
              label: 'API 执行符合率',
              numerator: 2,
              denominator: 3,
              basis: '冻结的三个场景',
              exclusions: [],
            },
            {
              key: 'protocol',
              label: '协议可用率',
              numerator: 0,
              denominator: 0,
              basis: '无协议回执',
              exclusions: ['SELFTEST_NO_EVALUABLE_DENOMINATOR'],
            },
          ],
          diagnostics: [
            {
              code: 'MISSING_REQUIRED_INPUT',
              severity: 'input',
              scenario_id: 'ST-MCP-023',
              oracle_id: 'required-oracle',
              field_path: '$.input',
              repair_hint: '补充订单编号',
            },
          ],
          case_slots: [
            {
              scenario_id: 'ST-MCP-023',
              variant_key: 'default',
              workflow_slot: 'scenario:ST-MCP-023',
              case_id: ids.scenario,
              case_version: 4,
              environment_id: ids.task,
            },
          ],
          comparisons: [
            {
              scenario_id: 'ST-MCP-023',
              variant_key: 'default',
              execution_id: ids.execution,
              items: [
                {
                  field: '请求次数',
                  expected: '2',
                  observed: '1',
                  difference: 'different',
                  verification_status: 'mismatched',
                  reason_codes: ['REQUEST_COUNT_MISMATCH'],
                },
              ],
            },
          ],
          reason_codes: [],
        }),
      ),
    )
    server.use(
      http.get(`${base}/runs/${ids.batch}/scenarios/ST-MCP-023/executions/${ids.execution}`, () =>
        HttpResponse.json({
          batch: { ...selfTestBatch, verification_scope: 'diagnostic_subset' },
          scenario: selfTestScenario,
          execution_id: ids.execution,
        }),
      ),
    )
    mount(
      <>
        <SelfTestInsights
          projectId={project.id}
          batch={{ ...selfTestBatch, verification_scope: 'diagnostic_subset' }}
        />
        <SelfTestReportPanels projectId={project.id} executionId={ids.execution} />
      </>,
      reportEntry,
    )
    expect(await screen.findByText('2 / 3 · 66.7%')).toBeVisible()
    expect(screen.getByText('0 / 0 · 未评估')).toBeVisible()
    expect(screen.getByText(/模板 v2.0.0/)).toHaveTextContent('diagnostic_subset')
    await userEvent.click(screen.getByText('编译诊断与待补输入（1）'))
    expect(await screen.findByText('补充订单编号')).toBeVisible()
    expect(screen.getByText('required-oracle', { exact: false })).toBeVisible()
    expect(await screen.findByText('请求次数')).toBeVisible()
    expect(screen.getByText(/场景回执：mismatched/)).toBeVisible()
    expect(screen.queryByText('当前摘要未提供，详见执行与核验证据')).not.toBeInTheDocument()
  })
  it('requires an explicit human revision confirmation and links the created proposal to existing review', async () => {
    let writes = 0
    server.use(
      http.post(`${base}/runs/${ids.batch}/assisted-case-proposals`, async ({ request }) => {
        const body = (await request.json()) as {
          dry_run: boolean
          idempotency_key: string
          test_cases: Array<{ description: string }>
        }
        expect(body.dry_run).toBe(false)
        expect(body.idempotency_key).toBeTruthy()
        expect(body.test_cases[0].description).toContain('修订原因：修正变量映射')
        writes += 1
        return HttpResponse.json({ data: { id: ids.task, project_id: project.id } })
      }),
    )
    mount(
      <SelfTestAssistedEditor
        projectId={project.id}
        batchId={ids.batch}
        beforeBatchId={ids.scenario}
        allowed
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: '提交人工 Case 修订提案' }))
    const drawer = within(screen.getByRole('dialog'))
    expect(drawer.getByRole('button', { name: '创建人工提案' })).toBeDisabled()
    await userEvent.type(drawer.getByRole('textbox', { name: '修订原因' }), '修正变量映射')
    await userEvent.click(drawer.getByRole('textbox', { name: '修订文档' }))
    await userEvent.paste(
      JSON.stringify({
        design: { schema_version: '1.0' },
        test_cases: [
          {
            name: '人工修订',
            description: '原描述',
            tags: [],
            definition: { workflow_id: ids.task, workflow_version: 4 },
          },
        ],
      }),
    )
    expect(writes).toBe(0)
    await userEvent.click(drawer.getByRole('checkbox'))
    await userEvent.click(drawer.getByRole('button', { name: '创建人工提案' }))
    const link = await drawer.findByRole('link', { name: '进入人工审核与发布' })
    expect(link).toHaveAttribute('href', expect.stringContaining(`/mcp-changes?focus=${ids.task}`))
    expect(link).toHaveAttribute('href', expect.stringContaining(`selfTestBatch=${ids.batch}`))
    expect(writes).toBe(1)
  })
  it('shows the blocked initialization, reason and recovery without starting a run', async () => {
    const template = {
      ...selfTestTemplate,
      id: 'core-v1',
      title: '原生固定包',
      batch_kind: 'fixed_baseline',
      supported_modes: [],
    }
    let blockedReads = 0
    let runs = 0
    server.use(
      http.get(`${base}/templates`, () => HttpResponse.json(selfTestPage([template]))),
      http.post(`${base}/installations/preview`, () =>
        HttpResponse.json({ ...selfTestPreview, template }),
      ),
      http.post(`${base}/installations`, () =>
        HttpResponse.json({
          ...selfTestInstallation,
          template_id: 'core-v1',
          status: 'needs_input',
        }),
      ),
      http.get(`${base}/installations/${ids.installation}`, () => {
        blockedReads += 1
        return HttpResponse.json({
          ...selfTestInstallation,
          template_id: 'core-v1',
          status: 'blocked',
          reason_codes: ['SELFTEST_INSTALLATION_FAILED'],
          actions: { ...selfTestInstallation.actions, can_execute: false },
        })
      }),
      http.post(`${base}/installations/${ids.installation}/runs`, () => {
        runs += 1
        return HttpResponse.json(selfTestBatch)
      }),
    )
    mount(
      <QualityCenterPage />,
      `/projects/${project.id}/quality?tab=selftest&mode=native&binding=${ids.binding}`,
    )
    await waitFor(() => expect(screen.getByRole('button', { name: '初始化自测' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: '初始化自测' }))
    const drawer = within(screen.getByRole('dialog'))
    await userEvent.click(drawer.getByRole('combobox', { name: '固定自测包' }))
    await userEvent.click(await screen.findByText('原生固定包 · 1.0.0'))
    await userEvent.click(drawer.getByRole('button', { name: '运行安全预检' }))
    await drawer.findByText('实例与环境一致')
    const checks = drawer.getAllByRole('checkbox')
    await userEvent.click(checks[0])
    await userEvent.click(checks[1])
    await userEvent.click(drawer.getByRole('button', { name: '初始化并运行' }))
    await waitFor(() => expect(blockedReads).toBeGreaterThan(0))
    expect(await drawer.findByText('初始化状态：已阻断')).toBeVisible()
    expect(drawer.getByText(/SELFTEST_INSTALLATION_FAILED/)).toBeVisible()
    expect(drawer.getByRole('button', { name: '继续初始化' })).toBeEnabled()
    expect(runs).toBe(0)
  })

  it('shows the standard source error, trace and retry', async () => {
    server.use(
      http.get(`${base}/runs/${ids.batch}/generation`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'UNAVAILABLE',
              message: '生成来源暂不可读',
              trace_id: 'audit-source-trace',
            },
          },
          { status: 503 },
        ),
      ),
    )
    mount(
      <SelfTestProposalBacklink
        projectId={project.id}
        proposalId={ids.task}
        route="controlled_write"
      />,
      `/projects/${project.id}/mcp-changes?focus=${ids.task}&selfTestBatch=${ids.batch}`,
    )
    expect(await screen.findByText('生成来源暂不可读')).toBeVisible()
    expect(screen.getByText(/audit-source-trace/)).toBeVisible()
    expect(screen.getByRole('button', { name: '重试' })).toBeEnabled()
  })

  it('opens installation mappings with exact published asset versions', async () => {
    server.use(
      http.get(`${base}/installations/${ids.installation}`, () =>
        HttpResponse.json({
          ...selfTestInstallation,
          mapping: {
            environment_id: ids.task,
            target_environment_id: ids.scenario,
            fixture_service_id: ids.task,
            target_service_id: ids.scenario,
            target_project_id: ids.task,
            target_organization_id: ids.task,
            target_user_id: ids.task,
            target_instance_id: 'target-B',
            target_build_digest: 'target-build',
            assets: [
              {
                scenario_id: 'ST-MCP-023',
                variant_key: 'default',
                workflow: { id: ids.task, version: 3, fingerprint: 'a'.repeat(64) },
                case: { id: ids.scenario, version: 2, fingerprint: 'a'.repeat(64) },
              },
            ],
          },
        }),
      ),
    )
    mount(
      <QualityCenterPage />,
      `/projects/${project.id}/quality?tab=selftest&mode=mcp_generation&binding=${ids.binding}&installation=${ids.installation}`,
    )
    await screen.findByText('安装状态：已就绪')
    const workspace = within(screen.getByRole('region', { name: '系统自测工作台' }))
    await userEvent.click(workspace.getByRole('button', { name: '查看安装' }))
    const detail = within(screen.getByRole('dialog'))
    expect(detail.getByRole('link', { name: `${ids.task}@3` })).toHaveAttribute(
      'href',
      expect.stringContaining('version=3'),
    )
    expect(detail.getByRole('link', { name: `${ids.scenario}@2` })).toHaveAttribute(
      'href',
      expect.stringContaining('version=2'),
    )
  })

  it('keeps unperformed formal execution unfinished on a sealed blocked generation', () => {
    const batch = parseBatch({
      ...selfTestBatch,
      phase: 'completed',
      generation_stage: 'blocked',
      readiness: 'blocked',
      verdict: 'blocked',
      sealed_verdict: 'blocked',
      plan_run_ids: [],
    })
    mount(
      <SelfTestGenerationProgress
        projectId={project.id}
        batch={batch}
        generation={{ ...generation, stage: 'blocked', readiness: 'blocked' }}
      />,
    )
    expect(screen.getByText('正式执行').closest('.ant-steps-item')).not.toHaveClass(
      'ant-steps-item-finish',
    )
    expect(screen.getByText('尚无正式执行，需明确确认')).toBeVisible()
  })

  it('polls active verification and stops after Observer seal', async () => {
    let sealed = false
    let reads = 0
    server.use(
      http.get(`${base}/runs/${ids.batch}/scenarios/ST-MCP-023/executions/${ids.execution}`, () => {
        reads += 1
        return HttpResponse.json({
          batch: sealed
            ? selfTestBatch
            : {
                ...selfTestBatch,
                phase: 'collecting',
                sealed_at: null,
                verdict: 'pending',
                evidence_integrity: 'missing',
              },
          scenario: sealed
            ? selfTestScenario
            : { ...selfTestScenario, verification_status: 'pending', attempts_complete: false },
          execution_id: ids.execution,
        })
      }),
    )
    mount(<SelfTestReportPanels projectId={project.id} executionId={ids.execution} />, reportEntry)
    await screen.findByText(/服务端场景回执：pending/)
    sealed = true
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 2300))
    })
    expect(await screen.findByText('独立核验：符合预期')).toBeVisible()
    expect(reads).toBe(2)
  })

  it('refreshes generation, batch and historical catalog together', async () => {
    let generationReads = 0
    let historyReads = 0
    let batchReads = 0
    let updated = false
    server.use(
      http.get(`${base}/runs/${ids.batch}`, () => {
        batchReads += 1
        return HttpResponse.json(selfTestBatch)
      }),
      http.get(`${base}/runs/${ids.batch}/generation`, () => {
        generationReads += 1
        return HttpResponse.json({ ...generation, tool_call_count: updated ? 2 : 1 })
      }),
      http.get(`${base}/installations/${ids.installation}/runs`, () => {
        historyReads += 1
        return HttpResponse.json(
          selfTestPage([
            { ...selfTestBatch, batch_key: updated ? '更新后的历史批次' : '旧历史批次' },
          ]),
        )
      }),
    )
    mount(<QualityCenterPage />)
    await screen.findByText('实际工具调用')
    await screen.findByText('旧历史批次')
    updated = true
    await userEvent.click(screen.getByRole('button', { name: '刷新状态' }))
    await waitFor(() => expect(batchReads).toBeGreaterThan(1))
    await waitFor(() => expect(generationReads).toBeGreaterThan(1))
    await waitFor(() => expect(historyReads).toBeGreaterThan(1))
    expect(await screen.findByText('更新后的历史批次')).toBeVisible()
  })

  it('carries verified self-test context into the materialized Case editor', () => {
    mount(
      <MCPMaterializedResult
        projectId={project.id}
        changeSetId={ids.task}
        item={{
          id: ids.scenario,
          position: 0,
          item_type: 'test_case',
          action: 'create',
          title: '本次生成用例',
          proposed_content: {},
          review_status: 'accepted',
          review_note: '',
          reviewed_by_id: user.id,
          reviewed_at: selfTestBatch.created_at,
          materialized_resource_type: 'test_case',
          materialized_resource_id: ids.installation,
        }}
      />,
      `/projects/${project.id}/mcp-changes?focus=${ids.task}&selfTestBatch=${ids.batch}`,
    )
    const link = screen.getByRole('link', { name: '查看物化测试用例' })
    expect(link).toHaveAttribute('href', expect.stringContaining('version=draft'))
    expect(link.getAttribute('href')).toContain(`selfTestBatch=${ids.batch}`)
  })

  it('restores the originating filters, page and cursor from validated return context', async () => {
    mount(
      <SelfTestReportPanels projectId={project.id} executionId={ids.execution} />,
      `${reportEntry}&selfTestReturn=${encodeURIComponent(`tab=selftest&mode=mcp_generation&category=mcp&verification=matched&page=2&cursor=${ids.task}`)}`,
    )
    const link = await screen.findByRole('link', { name: '返回已核验自测批次' })
    const params = new URL(link.getAttribute('href')!, 'http://localhost').searchParams
    expect(params.get('batch')).toBe(ids.batch)
    for (const name of ['category', 'verification', 'page', 'cursor'])
      expect(params.has(name)).toBe(true)
  })

  it('links source chain assets to their fixed versions', async () => {
    server.use(
      http.get(`${base}/runs/${ids.batch}/scenarios/ST-MCP-023/executions/${ids.execution}`, () =>
        HttpResponse.json({
          batch: selfTestBatch,
          scenario: {
            ...selfTestScenario,
            published_assets: {
              scenario_id: 'ST-MCP-023',
              variant_key: 'default',
              case: { id: ids.installation, version: 2, fingerprint: 'a'.repeat(64) },
              workflow: { id: ids.task, version: 3, fingerprint: 'a'.repeat(64) },
            },
          },
          execution_id: ids.execution,
        }),
      ),
    )
    mount(<SelfTestReportPanels projectId={project.id} executionId={ids.execution} />, reportEntry)
    const title = await screen.findByText('MCP 来源链')
    const chain = within(title.closest('.ant-card') as HTMLElement)
    expect(chain.getByText('Workflow v3')).toBeVisible()
    expect(chain.getByText('原生 Case v2')).toBeVisible()
    expect(chain.getByRole('link', { name: `${ids.task}@3` })).toHaveAttribute(
      'href',
      expect.stringContaining('version=3'),
    )
    expect(chain.getByRole('link', { name: `${ids.installation}@2` })).toHaveAttribute(
      'href',
      expect.stringContaining('version=2'),
    )
  })
})
