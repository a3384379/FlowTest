import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App, ConfigProvider } from 'antd'
import { delay, http, HttpResponse } from 'msw'
import { useLocation, useNavigate } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import QualityCenterPage from '../../pages/QualityCenterPage'
import ProjectTestProvider from '../../test/ProjectTestProvider'
import { authenticateTestUser } from '../../test/auth'
import { project, user } from '../../test/fixtures'
import { server } from '../../test/server'
import type { ReportExecutionDetail } from '../../lib/api'
import { useAuthStore } from '../auth/auth-store'
import { SelfTestArtifacts } from './SelfTestEvidence'
import SelfTestReportPanels from './SelfTestReportPanels'
import SelfTestProposalBacklink from './SelfTestProposalBacklink'
import {
  selfTestBatch,
  selfTestAssistedLineage,
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
const generation = {
  batch_id: ids.batch,
  generation_mode: 'deterministic_mcp',
  stage: 'ready',
  readiness: 'ready',
  reason_codes: [],
  host_status: 'available',
  tool_call_count: 4,
  proposals: [],
  sources: [],
  manifest: null,
  actions: selfTestBatch.actions,
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
    http.post(`${base}/installations/preview`, () => HttpResponse.json(selfTestPreview)),
  )
})
function Probe() {
  const location = useLocation()
  const navigate = useNavigate()
  return (
    <>
      <output aria-label="URL">{location.search}</output>
      <button onClick={() => navigate(-1)}>浏览器返回</button>
      <button
        onClick={() =>
          navigate(`/projects/${project.id}/quality?tab=selftest&binding=${ids.binding}`)
        }
      >
        切换范围
      </button>
    </>
  )
}
function mount(content = <QualityCenterPage />, initialEntry = entry) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const result = render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App>
        <QueryClientProvider client={client}>
          <ProjectTestProvider section="quality" initialEntry={initialEntry}>
            <Probe />
            {content}
          </ProjectTestProvider>
        </QueryClientProvider>
      </App>
    </ConfigProvider>,
  )
  return { ...result, client }
}
describe('real self-test workspace', () => {
  it('keeps registered sidebar identities compact while copying the complete frozen digest', async () => {
    const browser = userEvent.setup()
    const copied = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
    const digest = `sha256:${'0123456789abcdef'.repeat(4)}`
    server.use(
      http.get(`${base}/bindings`, () =>
        HttpResponse.json(
          selfTestPage([
            { ...selfTestBinding, builds: { ...selfTestBinding.builds, runner: digest } },
          ]),
        ),
      ),
    )
    mount()
    const title = await screen.findByText('已登记运行身份')
    const card = title.closest('.ant-card')!
    const identity = within(card as HTMLElement)
    expect(identity.getByTitle(digest)).toHaveTextContent('sha256:01234…456789abcdef')
    expect(identity.queryByText(digest)).not.toBeVisible()
    const rows = card.querySelectorAll('.ant-descriptions-row')
    expect(rows.length).toBeGreaterThan(0)
    expect(Array.from(rows).every((row) => row.children.length === 1)).toBe(true)
    await browser.click(identity.getByRole('button', { name: '复制完整Runner 构建' }))
    expect(copied).toHaveBeenCalledWith(digest)
    await browser.click(identity.getAllByText('显示完整值')[0])
    expect(identity.getByText(digest)).toBeVisible()
  })
  it('keeps failed raw execution red alongside matched verification and verified report IDs', async () => {
    mount()
    expect(await screen.findByText('原始执行：失败')).toHaveClass('ant-tag-error')
    expect(await screen.findByText('真实宿主模型链路：未执行（NOT_RUN）')).toBeVisible()
    expect(await screen.findByText('独立核验：符合预期')).toHaveClass('ant-tag-success')
    expect(screen.getByText('当前范围验收通过')).toBeVisible()
    expect(screen.getByText('本地未受信来源')).toBeVisible()
    expect(screen.getByRole('link', { name: /执行 1/ })).toHaveAttribute(
      'href',
      expect.stringContaining(
        `execution=${ids.execution}&selfTestBatch=${ids.batch}&selfTestScenario=ST-MCP-023&panel=verification`,
      ),
    )
    expect(screen.getByText(/尚无已发布且核验完成/)).toBeVisible()
  })
  it('reads the final scenario receipt after the batch seals ahead of an older scenario response', async () => {
    let batchReads = 0
    let sealed = false
    server.use(
      http.get(`${base}/runs/${ids.batch}`, async () => {
        batchReads += 1
        if (batchReads === 1)
          return HttpResponse.json({
            ...selfTestBatch,
            phase: 'running',
            verdict: 'pending',
            sealed_at: null,
            sealed_verdict: null,
            evidence_integrity: 'missing',
            cleanup_status: 'pending',
          })
        await delay(20)
        sealed = true
        return HttpResponse.json({ ...selfTestBatch, revision: 2 })
      }),
      http.get(`${base}/runs/${ids.batch}/scenarios`, async () => {
        const observedSeal = sealed
        await delay(40)
        return HttpResponse.json(
          selfTestPage([
            { ...selfTestScenario, verification_status: observedSeal ? 'matched' : 'pending' },
          ]),
        )
      }),
    )
    mount()
    await screen.findByText('独立核验：未独立核验')
    await userEvent.click(screen.getByRole('button', { name: '刷新状态' }))
    expect(await screen.findByText('当前范围验收通过')).toBeVisible()
    expect(await screen.findByText('独立核验：符合预期')).toBeVisible()
  })
  it('preserves the sealed historical verdict while current Observer is unavailable', async () => {
    server.use(
      http.get(`${base}/bindings`, () =>
        HttpResponse.json(
          selfTestPage([{ ...selfTestBinding, observer_status: 'not_configured' }]),
        ),
      ),
    )
    mount()
    await screen.findByText('封存验收结论（历史）')
    expect(screen.getByText('封存验收结论（历史）').closest('tr')).toHaveTextContent('通过')
    expect(screen.queryByText('当前范围验收通过')).not.toBeInTheDocument()
    expect(screen.getByText('Observer 未核验')).toBeVisible()
  })
  it('separates an expired current verdict from the explicit sealed original verdict', async () => {
    server.use(
      http.get(`${base}/runs/${ids.batch}`, () =>
        HttpResponse.json({
          ...selfTestBatch,
          verdict: 'blocked',
          sealed_verdict: 'passed',
          evidence_integrity: 'expired',
        }),
      ),
    )
    mount()
    await screen.findByText('封存验收结论（历史）')
    expect(screen.getByText('封存验收结论（历史）').closest('tr')).toHaveTextContent('通过')
    expect(screen.queryByText('当前范围验收通过')).not.toBeInTheDocument()
  })
  it('does not infer a historical verdict from an older server projection', async () => {
    server.use(
      http.get(`${base}/runs/${ids.batch}`, () =>
        HttpResponse.json({
          ...selfTestBatch,
          verdict: 'blocked',
          sealed_verdict: undefined,
          evidence_integrity: 'expired',
        }),
      ),
    )
    mount()
    await screen.findByText('原始执行：失败')
    expect(screen.queryByText('封存验收结论（历史）')).not.toBeInTheDocument()
    expect(screen.queryByText('当前范围验收通过')).not.toBeInTheDocument()
  })
  it('never greens missing Observer or missing/nonterminal evidence', async () => {
    server.use(
      http.get(`${base}/bindings`, () =>
        HttpResponse.json(
          selfTestPage([
            {
              ...selfTestBinding,
              observer_status: 'not_configured',
              host_status: 'not_registered',
            },
          ]),
        ),
      ),
      http.get(`${base}/runs/${ids.batch}`, () =>
        HttpResponse.json({
          ...selfTestBatch,
          phase: 'collecting',
          evidence_integrity: 'missing',
          sealed_at: null,
        }),
      ),
    )
    mount()
    expect(await screen.findByText('Observer 未核验')).toBeVisible()
    expect(await screen.findByText('独立核验：证据不完整')).toBeVisible()
    expect(screen.queryByText('当前范围验收通过')).not.toBeInTheDocument()
    expect(screen.queryByText('独立核验：符合预期')).not.toBeInTheDocument()
  })
  it('rejects a zero-required set and mismatched project instead of filling an empty green view', async () => {
    server.use(
      http.get(`${base}/runs/${ids.batch}`, () =>
        HttpResponse.json({ ...selfTestBatch, required_scenario_set: [] }),
      ),
    )
    mount()
    expect((await screen.findAllByText(/自测响应格式或范围无效/)).length).toBeGreaterThan(0)
    expect(screen.queryByText('当前范围验收通过')).not.toBeInTheDocument()
  })
  it('requires independent generation confirmation and does not execute after generating', async () => {
    const generated = vi.fn()
    const executed = vi.fn()
    server.use(
      http.post(
        `${base}/installations/${ids.installation}/generation-batches`,
        async ({ request }) => {
          generated(await request.json(), request.headers.get('Idempotency-Key'))
          return HttpResponse.json({
            ...selfTestBatch,
            phase: 'generating',
            verdict: 'pending',
            sealed_at: null,
          })
        },
      ),
      http.post(`${base}/runs/${ids.batch}/execute-materialized`, () => {
        executed()
        return HttpResponse.json(selfTestBatch)
      }),
    )
    mount()
    await screen.findByText('原始执行：失败')
    await userEvent.click(screen.getByRole('button', { name: '创建 MCP 生成任务' }))
    const drawer = within(screen.getByRole('dialog'))
    expect(drawer.getByRole('button', { name: '创建 MCP 生成任务' })).toBeDisabled()
    await userEvent.click(drawer.getByRole('checkbox'))
    await userEvent.click(drawer.getByRole('button', { name: '创建 MCP 生成任务' }))
    await waitFor(() => expect(generated).toHaveBeenCalledTimes(1))
    expect(generated.mock.calls[0][0]).toMatchObject({
      generation_mode: 'deterministic_mcp',
      host_id: null,
      verification_scope: 'full_pack',
      budget: { timeout_seconds: 600, max_requests: 500, max_tool_calls: 100 },
    })
    expect(generated.mock.calls[0][1]).toMatch(/^[0-9a-f-]{36}$/)
    expect(executed).not.toHaveBeenCalled()
  })
  it('closes writes immediately on permission invalidation, before a delayed permission refresh', async () => {
    const { client } = mount()
    const button = await screen.findByRole('button', { name: '创建 MCP 生成任务' })
    await waitFor(() => expect(button).toBeEnabled())
    server.use(
      http.get(`/api/v1/projects/${project.id}/permissions`, async () => {
        await delay(1000)
        return HttpResponse.json({ effective_role: 'viewer', capabilities: ['read'], matrix: {} })
      }),
    )
    act(() => {
      void client.invalidateQueries({ queryKey: ['project-permissions', project.id, user.id] })
    })
    expect(button).toBeDisabled()
  })
  it('blocks conflicting previews and clears confirmation when choosing another pack', async () => {
    server.use(
      http.post(`${base}/installations/preview`, () =>
        HttpResponse.json({
          ...selfTestPreview,
          can_apply: false,
          conflicts: ['RESOURCE_CONFLICT'],
        }),
      ),
    )
    mount()
    await screen.findByText('原始执行：失败')
    await userEvent.click(screen.getByRole('button', { name: '初始化自测' }))
    const drawer = within(screen.getByRole('dialog'))
    await userEvent.click(drawer.getByRole('combobox', { name: '固定自测包' }))
    await userEvent.click(await screen.findByText('真实 MCP 自测包 · 1.0.0'))
    await userEvent.click(drawer.getByRole('button', { name: '运行安全预检' }))
    await drawer.findByText('原因：RESOURCE_CONFLICT')
    expect(drawer.getByRole('button', { name: '仅初始化' })).toBeDisabled()
    expect(drawer.getByRole('checkbox')).toBeDisabled()
  })
  it('stores filters in URL and browser history without changing batch identity', async () => {
    const seen = vi.fn()
    server.use(
      http.get(`${base}/runs/${ids.batch}/scenarios`, ({ request }) => {
        seen(new URL(request.url).searchParams.get('verification'))
        return HttpResponse.json(selfTestPage([selfTestScenario]))
      }),
    )
    mount()
    await screen.findByText('原始执行：失败')
    await userEvent.click(screen.getByRole('combobox', { name: '核验结果筛选' }))
    await userEvent.click(screen.getByText('不符合预期'))
    await waitFor(() => expect(seen).toHaveBeenCalledWith('mismatched'))
    expect(screen.getByLabelText('URL')).toHaveTextContent(`batch=${ids.batch}`)
    await userEvent.click(screen.getByRole('button', { name: '浏览器返回' }))
    await waitFor(() => expect(screen.getByLabelText('URL')).not.toHaveTextContent('verification='))
  })
  it('ignores a late generation receipt after the organization epoch changes', async () => {
    let resolve: (() => void) | undefined
    server.use(
      http.post(`${base}/installations/${ids.installation}/generation-batches`, async () => {
        await new Promise<void>((done) => {
          resolve = done
        })
        return HttpResponse.json({ ...selfTestBatch, id: '00000000-0000-4000-8000-000000000299' })
      }),
    )
    mount()
    await screen.findByText('原始执行：失败')
    await userEvent.click(screen.getByRole('button', { name: '创建 MCP 生成任务' }))
    const drawer = within(screen.getByRole('dialog'))
    await userEvent.click(drawer.getByRole('checkbox'))
    await userEvent.click(drawer.getByRole('button', { name: '创建 MCP 生成任务' }))
    await waitFor(() => expect(resolve).toBeTypeOf('function'))
    act(() => useAuthStore.setState((state) => ({ epoch: state.epoch + 1 })))
    await act(async () => {
      resolve!()
      await delay(50)
    })
    expect(screen.getByLabelText('URL')).not.toHaveTextContent('000000000299')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
describe('server-verified execution provenance', () => {
  const reportEntry = `/projects/${project.id}/reports?execution=${ids.execution}&node=node-A&attempt=2&control_kind=iteration&control_ordinal=0&selfTestBatch=${ids.batch}&selfTestScenario=ST-MCP-023&panel=verification`
  const asset = { id: ids.task, version: 3, fingerprint: 'a'.repeat(64) }
  const nativeDetail: ReportExecutionDetail = {
    summary: {
      id: ids.execution,
      workflow_id: ids.task,
      workflow_name: '真实固定流程',
      workflow_version: 3,
      status: 'failed',
      failure_category: 'assertion',
      total_nodes: 1,
      passed_nodes: 0,
      failed_nodes: 1,
      skipped_nodes: 0,
      duration_ms: 20,
      started_at: selfTestBatch.created_at,
      completed_at: selfTestBatch.sealed_at,
    },
    nodes: [
      {
        id: ids.scenario,
        node_id: 'assert-business',
        node_type: 'assert',
        name: '业务断言',
        status: 'failed',
        attempts: 1,
        duration_ms: 1,
        request: null,
        response: null,
        extraction: null,
        assertion: null,
        input_mappings: null,
        error_code: 'ASSERTION_FAILED',
        error_message: '冻结负向断言失败',
      },
    ],
    context: {},
    dataset_children: [],
  }
  it.each([true, false])(
    'shows exact native failure evidence only when the pinned report version matches (%s)',
    async (matches) => {
      server.use(
        http.get(`${base}/runs/${ids.batch}/scenarios/ST-MCP-023/executions/${ids.execution}`, () =>
          HttpResponse.json({
            batch: { ...selfTestBatch, verification_scope: 'diagnostic_subset' },
            scenario: {
              ...selfTestScenario,
              published_assets: {
                scenario_id: selfTestScenario.scenario_id,
                variant_key: selfTestScenario.variant_key,
                workflow: asset,
                case: asset,
              },
            },
            execution_id: ids.execution,
          }),
        ),
      )
      mount(
        <SelfTestReportPanels
          projectId={project.id}
          executionId={ids.execution}
          detail={{
            ...nativeDetail,
            summary: { ...nativeDetail.summary, workflow_version: matches ? 3 : 2 },
          }}
        />,
        reportEntry,
      )
      await screen.findByText('原始执行：失败')
      expect(screen.getByText('独立核验：符合预期')).toBeVisible()
      expect(screen.getByText('范围：所选子集 · 1 个场景')).toBeVisible()
      expect(screen.getByText('Workflow v3')).toBeVisible()
      expect(screen.getByText('原生 Case v3')).toBeVisible()
      expect(screen.getByText('契约与期望')).toBeVisible()
      expect(document.querySelectorAll('.self-test-chain-number')).toHaveLength(8)
      if (matches) {
        expect(screen.getByText('assert-business · ASSERTION_FAILED')).toBeVisible()
        expect(screen.getByText('错误码一致')).toBeVisible()
      } else {
        expect(screen.queryByText('实际失败位置与错误码')).not.toBeInTheDocument()
        expect(screen.getByText('当前摘要未提供，详见独立核验 JSON')).toBeVisible()
      }
    },
  )
  it('does not show a green matched receipt for a batch with zero required scenarios', async () => {
    server.use(
      http.get(`${base}/runs/${ids.batch}/scenarios/ST-MCP-023/executions/${ids.execution}`, () =>
        HttpResponse.json({
          batch: { ...selfTestBatch, required_scenario_set: [] },
          scenario: selfTestScenario,
          execution_id: ids.execution,
        }),
      ),
    )
    mount(<SelfTestReportPanels projectId={project.id} executionId={ids.execution} />, reportEntry)
    expect(
      await screen.findByText('自测响应格式或范围无效，请刷新并核对服务端接口版本。'),
    ).toBeVisible()
    expect(screen.queryByText('独立核验：符合预期')).not.toBeInTheDocument()
  })
  it('keeps execution/control coordinates while switching the execution-level panels', async () => {
    mount(<SelfTestReportPanels projectId={project.id} executionId={ids.execution} />, reportEntry)
    expect(await screen.findByText('原始执行：失败')).toBeVisible()
    await userEvent.click(screen.getByRole('tab', { name: '生成来源' }))
    expect(screen.getByLabelText('URL')).toHaveTextContent(
      'node=node-A&attempt=2&control_kind=iteration&control_ordinal=0',
    )
    expect(screen.getByLabelText('URL')).toHaveTextContent('panel=provenance')
  })
  it('refuses a forged execution relationship even with a valid-looking batch ID', async () => {
    server.use(
      http.get(`${base}/runs/${ids.batch}/scenarios/ST-MCP-023/executions/${ids.execution}`, () =>
        HttpResponse.json({
          batch: { ...selfTestBatch, project_id: '00000000-0000-4000-8000-000000000999' },
          scenario: selfTestScenario,
          execution_id: ids.execution,
        }),
      ),
    )
    mount(<SelfTestReportPanels projectId={project.id} executionId={ids.execution} />, reportEntry)
    expect(await screen.findByText(/未能确认当前项目/)).toBeVisible()
    expect(screen.queryByText('独立核验：符合预期')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '返回已核验自测批次' })).not.toBeInTheDocument()
  })
  it('shows a proposal backlink only for the exact server proposal identity', async () => {
    server.use(
      http.get(`${base}/runs/${ids.batch}/generation`, () =>
        HttpResponse.json({
          ...generation,
          proposals: [
            {
              change_set_id: ids.task,
              item_id: ids.scenario,
              route: 'controlled_write',
              content_fingerprint: 'a'.repeat(64),
              review_status: 'pending',
              materialized_resource_id: null,
            },
          ],
        }),
      ),
    )
    const { rerender } = mount(
      <SelfTestProposalBacklink
        projectId={project.id}
        proposalId={ids.execution}
        route="controlled_write"
      />,
      `/projects/${project.id}/mcp-changes?selfTestBatch=${ids.batch}`,
    )
    expect(await screen.findByText(/当前提案与自测来源尚未核验/)).toBeVisible()
    rerender(
      <ConfigProvider>
        <App>
          <QueryClientProvider client={new QueryClient()}>
            <ProjectTestProvider
              section="quality"
              initialEntry={`/projects/${project.id}/mcp-changes?selfTestBatch=${ids.batch}`}
            >
              <SelfTestProposalBacklink
                projectId={project.id}
                proposalId={ids.task}
                route="controlled_write"
              />
            </ProjectTestProvider>
          </QueryClientProvider>
        </App>
      </ConfigProvider>,
    )
    expect(await screen.findByRole('link', { name: '返回已核验的 MCP 自测生成批次' })).toBeVisible()
  })
})

describe('self-test command boundaries', () => {
  async function openPreview() {
    await screen.findByText('原始执行：失败')
    await userEvent.click(screen.getByRole('button', { name: '初始化自测' }))
    const drawer = within(screen.getByRole('dialog'))
    await userEvent.click(drawer.getByRole('combobox', { name: '固定自测包' }))
    await userEvent.click(await screen.findByText('真实 MCP 自测包 · 1.0.0'))
    await userEvent.click(drawer.getByRole('button', { name: '运行安全预检' }))
    return drawer
  }
  it('keeps an expired preview unusable and demands another confirmation', async () => {
    server.use(
      http.post(`${base}/installations/preview`, () =>
        HttpResponse.json({ ...selfTestPreview, expires_at: '2020-10-23T01:00:00Z' }),
      ),
    )
    mount()
    const drawer = await openPreview()
    await drawer.findByText('预检已过期，请重新预检并确认。')
    expect(drawer.getByRole('button', { name: '仅初始化' })).toBeDisabled()
    expect(drawer.getByRole('checkbox')).not.toBeChecked()
  })
  it('ignores a preview that arrives after the pack input changes', async () => {
    let finish: (() => void) | undefined
    server.use(
      http.get(`${base}/templates`, () =>
        HttpResponse.json(
          selfTestPage([
            selfTestTemplate,
            { ...selfTestTemplate, id: 'mcp-extended-v1', title: '扩展包' },
          ]),
        ),
      ),
      http.post(`${base}/installations/preview`, async () => {
        await new Promise<void>((done) => {
          finish = done
        })
        return HttpResponse.json(selfTestPreview)
      }),
    )
    mount()
    const drawer = await openPreview()
    await waitFor(() => expect(finish).toBeTypeOf('function'))
    await userEvent.click(drawer.getByRole('combobox', { name: '固定自测包' }))
    await userEvent.click(await screen.findByText('扩展包 · 1.0.0'))
    await act(async () => {
      finish!()
      await delay(30)
    })
    expect(drawer.queryByText('实例与环境一致')).not.toBeInTheDocument()
    expect(drawer.getByRole('button', { name: '仅初始化' })).toBeDisabled()
  })
  it('reuses the same idempotency key after a lost generation response and never auto retries', async () => {
    const keys: (string | null)[] = []
    server.use(
      http.post(`${base}/installations/${ids.installation}/generation-batches`, ({ request }) => {
        keys.push(request.headers.get('Idempotency-Key'))
        return HttpResponse.json(
          {
            error: {
              code: 'UNAVAILABLE',
              message: '回执暂未返回',
              trace_id: 'selftest-lost-response',
            },
          },
          { status: 503 },
        )
      }),
    )
    mount()
    await screen.findByText('原始执行：失败')
    await userEvent.click(screen.getByRole('button', { name: '创建 MCP 生成任务' }))
    const drawer = within(screen.getByRole('dialog'))
    await userEvent.click(drawer.getByRole('checkbox'))
    await userEvent.click(drawer.getByRole('button', { name: '创建 MCP 生成任务' }))
    await drawer.findByText(/selftest-lost-response/)
    expect(keys).toHaveLength(1)
    await userEvent.click(drawer.getByRole('button', { name: '创建 MCP 生成任务' }))
    await waitFor(() => expect(keys).toHaveLength(2))
    expect(keys[0]).toBe(keys[1])
  })
  it('permits edit-only generation while independently denying native execution', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/permissions`, () =>
        HttpResponse.json({ effective_role: 'editor', capabilities: ['read', 'edit'], matrix: {} }),
      ),
    )
    mount()
    await screen.findByText('原始执行：失败')
    expect(screen.getByRole('button', { name: '创建 MCP 生成任务' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '执行已发布产物' })).toBeDisabled()
  })
  it('respects a denied binding generation action even for a ready installation and editor', async () => {
    server.use(
      http.get(`${base}/bindings`, () =>
        HttpResponse.json(
          selfTestPage([
            { ...selfTestBinding, actions: { ...selfTestBinding.actions, can_generate: false } },
          ]),
        ),
      ),
    )
    mount()
    await screen.findByText('原始执行：失败')
    expect(screen.getByRole('button', { name: '初始化自测' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '创建 MCP 生成任务' })).toBeDisabled()
  })
  it('respects a denied binding execution action even when the fixed installation is ready', async () => {
    const fixed = {
      ...selfTestTemplate,
      id: 'core-v1',
      batch_kind: 'fixed_baseline',
      supported_modes: [],
    }
    server.use(
      http.get(`${base}/templates`, () => HttpResponse.json(selfTestPage([fixed]))),
      http.get(`${base}/bindings`, () =>
        HttpResponse.json(
          selfTestPage([
            { ...selfTestBinding, actions: { ...selfTestBinding.actions, can_execute: false } },
          ]),
        ),
      ),
      http.get(`${base}/installations/${ids.installation}`, () =>
        HttpResponse.json({ ...selfTestInstallation, template_id: 'core-v1' }),
      ),
    )
    mount(
      <QualityCenterPage />,
      `/projects/${project.id}/quality?tab=selftest&mode=native&binding=${ids.binding}&installation=${ids.installation}`,
    )
    await screen.findByText('安装状态：已就绪')
    expect(screen.getByRole('button', { name: '初始化自测' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '运行固定基准' })).toBeDisabled()
  })
  it('keeps viewer actions closed even when the server binding permits operations', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/permissions`, () =>
        HttpResponse.json({ effective_role: 'viewer', capabilities: ['read'], matrix: {} }),
      ),
    )
    mount()
    await screen.findByText('原始执行：失败')
    for (const name of ['初始化自测', '创建 MCP 生成任务', '执行已发布产物'])
      expect(screen.getByRole('button', { name })).toBeDisabled()
  })
  it('reports a 403 read failure with its trace instead of displaying an empty catalog', async () => {
    server.use(
      http.get(`${base}/bindings`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'FORBIDDEN',
              message: '绑定读取无权限',
              trace_id: 'binding-denied-trace',
            },
          },
          { status: 403 },
        ),
      ),
    )
    mount()
    expect(await screen.findByText('绑定读取无权限')).toBeVisible()
    expect(screen.getByText('Trace ID: binding-denied-trace')).toBeVisible()
    expect(screen.queryByText(/没有已登记的自测绑定/)).not.toBeInTheDocument()
  })
  it('retries only the run when initialization succeeded but the explicit run failed', async () => {
    const fixedTemplate = {
      ...selfTestTemplate,
      id: 'core-v1',
      title: '原生固定包',
      batch_kind: 'fixed_baseline',
      supported_modes: [],
    }
    const fixedInstallation = { ...selfTestInstallation, template_id: 'core-v1' }
    const fixedBatch = { ...selfTestBatch, batch_kind: 'fixed_baseline', generation_mode: null }
    const installed = vi.fn()
    const runKeys: (string | null)[] = []
    server.use(
      http.get(`${base}/templates`, () => HttpResponse.json(selfTestPage([fixedTemplate]))),
      http.get(`${base}/installations/${ids.installation}`, () =>
        HttpResponse.json(fixedInstallation),
      ),
      http.post(`${base}/installations/preview`, () =>
        HttpResponse.json({ ...selfTestPreview, template: fixedTemplate }),
      ),
      http.post(`${base}/installations`, () => {
        installed()
        return HttpResponse.json(fixedInstallation)
      }),
      http.post(`${base}/installations/${ids.installation}/runs`, ({ request }) => {
        runKeys.push(request.headers.get('Idempotency-Key'))
        return runKeys.length === 1
          ? HttpResponse.json(
              { error: { code: 'UNAVAILABLE', message: '启动失败', trace_id: 'run-start-trace' } },
              { status: 503 },
            )
          : HttpResponse.json(fixedBatch)
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
    expect(
      await drawer.findByText('初始化成功，启动失败。重试只启动运行，不重复初始化。'),
    ).toBeVisible()
    expect(installed).toHaveBeenCalledTimes(1)
    expect(runKeys).toHaveLength(1)
    await userEvent.click(drawer.getByRole('button', { name: '重试启动运行' }))
    await waitFor(() => expect(runKeys).toHaveLength(2))
    expect(runKeys[0]).toBe(runKeys[1])
    expect(installed).toHaveBeenCalledTimes(1)
  })
})

describe('published resource confirmation', () => {
  const asset = { id: ids.task, version: 3, fingerprint: 'a'.repeat(64) }
  const snapshot = {
    suite: asset,
    plan_id: ids.task,
    cases: [
      {
        scenario_id: 'ST-MCP-023',
        variant_key: 'default',
        workflow: asset,
        case: { ...asset, id: ids.scenario },
        environment_id: ids.binding,
        target_snapshot_digest: 'b'.repeat(64),
      },
    ],
  }
  const proposal = {
    change_set_id: ids.task,
    item_id: null,
    route: 'flow_spec_visual',
    content_fingerprint: 'a'.repeat(64),
    review_status: 'accepted',
    materialized_resource_id: ids.task,
  }
  const source = {
    host_evidence: {
      host: 'recorded-host',
      model: 'recorded-model',
      skill_digest: 'a'.repeat(64),
      prompt_digest: 'b'.repeat(64),
      authorized_budget_digest: 'c'.repeat(64),
      actual_tool_calls: 7,
    },
    scenario_id: 'ST-MCP-023',
    variant_key: 'default',
    workflow: asset,
    case: { ...asset, id: ids.scenario },
    design_fingerprint: 'a'.repeat(64),
    compilation_fingerprint: 'a'.repeat(64),
    oracle_mapping_digest: 'a'.repeat(64),
    workflow_proposal: proposal,
    case_proposal: {
      ...proposal,
      change_set_id: ids.scenario,
      route: 'controlled_write',
      item_id: ids.scenario,
    },
    api_sources_digest: 'a'.repeat(64),
    api_sources: [
      {
        project_id: project.id,
        api_definition_id: ids.binding,
        api_version: 2,
        contract_fingerprint: 'a'.repeat(64),
      },
    ],
    oracle_bindings: [
      {
        oracle_id: 'oracle-023',
        node_id: 'assert-023',
        phase: 'main',
        expression: 'response.body.flag',
        expected_value_digest: 'a'.repeat(64),
        assertion_name: '业务断言',
      },
    ],
    protocol_receipts_digest: 'a'.repeat(64),
    generation_manifest: { id: ids.task, sha256: 'a'.repeat(64), kind: 'generation' },
  }
  it('renders a real one-of-six subset and the three capability areas without an all-pack success banner', async () => {
    server.use(
      http.get(`${base}/templates`, () =>
        HttpResponse.json(
          selfTestPage([
            {
              ...selfTestTemplate,
              scenarios: Array.from({ length: 6 }, (_, index) => ({
                ...selfTestTemplate.scenarios[0],
                scenario_id: `ST-MCP-02${index}`,
              })),
            },
          ]),
        ),
      ),
      http.get(`${base}/runs/${ids.batch}`, () =>
        HttpResponse.json({ ...selfTestBatch, verification_scope: 'diagnostic_subset' }),
      ),
    )
    mount()
    expect(await screen.findByText('选定子集核验已完成，不代表全量通过')).toBeVisible()
    expect(screen.getByText('范围：所选子集 · 1 / 6 场景')).toBeVisible()
    const capabilities = within(screen.getByLabelText('自测能力'))
    for (const title of ['接口回归', '引擎验证', '独立核验'])
      expect(capabilities.getByText(title)).toBeVisible()
    expect(screen.getByLabelText('隔离检查与最近批次')).toBeVisible()
    expect(screen.queryByText('当前冻结包核验已完成')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /真实批次 1/ })).toBeVisible()
  })
  it('keeps real pending proposals and zero formal runs distinct from published assets', async () => {
    server.use(
      http.get(`${base}/runs/${ids.batch}`, () =>
        HttpResponse.json({
          ...selfTestBatch,
          phase: 'awaiting_review',
          verdict: 'pending',
          sealed_at: null,
          sealed_verdict: null,
          plan_run_ids: [],
        }),
      ),
      http.get(`${base}/runs/${ids.batch}/generation`, () =>
        HttpResponse.json({
          ...generation,
          stage: 'awaiting_review',
          proposals: [{ ...proposal, review_status: 'pending', materialized_resource_id: null }],
          sources: [],
        }),
      ),
    )
    mount()
    expect(await screen.findByText('1 项待审核')).toBeVisible()
    expect(screen.getByText('0 / 1 项来源已发布')).toBeVisible()
    expect(screen.getByText('尚无正式执行，需明确确认')).toBeVisible()
    expect(screen.getByRole('link', { name: '查看提案' })).toHaveAttribute(
      'href',
      expect.stringContaining(`proposal=${ids.task}`),
    )
    expect(screen.getByRole('button', { name: '执行已发布产物' })).toBeDisabled()
  })
  it('shows assisted lineage as a separate rerun with real prior batch and version links', async () => {
    server.use(
      http.get(`${base}/runs/${ids.batch}/generation`, () =>
        HttpResponse.json({
          ...generation,
          sources: [
            { ...source, fixture_batch_key: 'origin-fixture', assisted: selfTestAssistedLineage },
          ],
        }),
      ),
    )
    mount()
    expect(await screen.findByText('辅助重跑，不计首次生成')).toBeVisible()
    expect(
      screen.getByText('浏览器自动化测试审核者经原生审核链确认修订；不计为实际人工验收。'),
    ).toBeVisible()
    expect(screen.getByRole('link', { name: `修订前批次 ${ids.execution}` })).toHaveAttribute(
      'href',
      `/projects/${project.id}/quality?tab=selftest&mode=mcp_generation&batch=${ids.execution}`,
    )
    expect(screen.getByRole('link', { name: `首次生成批次 ${ids.scenario}` })).toHaveAttribute(
      'href',
      `/projects/${project.id}/quality?tab=selftest&mode=mcp_generation&batch=${ids.scenario}`,
    )
    expect(screen.getByText(`${ids.task}@2 → ${ids.task}@3`)).toBeVisible()
    expect(screen.getByText(`${ids.scenario}@2 → ${ids.scenario}@3`)).toBeVisible()
    expect(screen.getByText('$.workflow.nodes[1].expected')).toBeVisible()
    expect(screen.getByText('原始执行：失败')).toBeVisible()
    expect(screen.getByText('独立核验：符合预期')).toBeVisible()
  })
  it.each(['native', 'mcp_generation'] as const)(
    'recovers an unconfirmed dispatch for %s using the same batch and frozen run',
    async (mode) => {
      const fixed = mode === 'native'
      const batch = {
        ...selfTestBatch,
        batch_kind: fixed ? 'fixed_baseline' : 'mcp_generated',
        generation_mode: fixed ? null : 'deterministic_mcp',
        phase: 'running',
        sealed_at: null,
        sealed_verdict: null,
        verdict: 'blocked',
        readiness: 'blocked',
        reason_codes: ['SELFTEST_DISPATCH_UNCONFIRMED'],
        resource_snapshot: snapshot,
        plan_id: snapshot.plan_id,
        suite: asset,
      }
      const resumed = vi.fn()
      const newRun = vi.fn()
      server.use(
        http.get(`${base}/runs/${ids.batch}`, () => HttpResponse.json(batch)),
        http.get(`${base}/runs/${ids.batch}/generation`, () =>
          HttpResponse.json({ ...generation, sources: [source] }),
        ),
        http.get(`${base}/templates`, () =>
          HttpResponse.json(
            selfTestPage([
              fixed
                ? {
                    ...selfTestTemplate,
                    id: 'core-v1',
                    batch_kind: 'fixed_baseline',
                    supported_modes: [],
                  }
                : selfTestTemplate,
            ]),
          ),
        ),
        http.get(`${base}/installations/${ids.installation}`, () =>
          HttpResponse.json({
            ...selfTestInstallation,
            template_id: fixed ? 'core-v1' : 'mcp-core-v1',
          }),
        ),
        http.post(`${base}/runs/${ids.batch}/execute-materialized`, async ({ request }) => {
          resumed(await request.json(), request.headers.get('Idempotency-Key'))
          return HttpResponse.json({ ...batch, readiness: 'ready', reason_codes: [] })
        }),
        http.post(`${base}/installations/${ids.installation}/runs`, () => {
          newRun()
          return HttpResponse.json(batch)
        }),
      )
      mount(<QualityCenterPage />, entry.replace('mode=mcp_generation', `mode=${mode}`))
      const recover = await screen.findByRole('button', { name: '恢复原运行派发' })
      await waitFor(() => expect(recover).toBeEnabled())
      await userEvent.click(recover)
      const drawer = within(screen.getByRole('dialog'))
      const submit = drawer.getByRole('button', { name: '恢复原运行派发' })
      expect(submit).toBeDisabled()
      expect(drawer.getByText(`原生 Run：${ids.task}`)).toBeVisible()
      await userEvent.click(drawer.getByRole('checkbox'))
      await userEvent.click(submit)
      await waitFor(() => expect(resumed).toHaveBeenCalledTimes(1))
      expect(resumed.mock.calls[0][0]).toEqual({
        resource_digest: 'a'.repeat(64),
        environment_fingerprint: 'a'.repeat(64),
        confirmed: true,
      })
      expect(resumed.mock.calls[0][1]).toBeTruthy()
      expect(newRun).not.toHaveBeenCalled()
    },
  )
  it('requires the complete frozen source set and a fresh explicit execute confirmation', async () => {
    const executed = vi.fn()
    server.use(
      http.get(`${base}/runs/${ids.batch}`, () =>
        HttpResponse.json({
          ...selfTestBatch,
          phase: 'ready',
          sealed_at: null,
          verdict: 'pending',
          resource_snapshot: snapshot,
          plan_id: snapshot.plan_id,
          suite: asset,
        }),
      ),
      http.get(`${base}/runs/${ids.batch}/generation`, () =>
        HttpResponse.json({ ...generation, sources: [source] }),
      ),
      http.post(`${base}/runs/${ids.batch}/execute-materialized`, async ({ request }) => {
        executed(await request.json())
        return HttpResponse.json({
          ...selfTestBatch,
          phase: 'running',
          verdict: 'pending',
          sealed_at: null,
          resource_snapshot: snapshot,
          plan_id: snapshot.plan_id,
          suite: asset,
        })
      }),
    )
    mount()
    expect(await screen.findByText('recorded-host')).toBeVisible()
    expect(screen.getByText('recorded-model')).toBeVisible()
    const execute = await screen.findByRole('button', { name: '执行已发布产物' })
    await waitFor(() => expect(execute).toBeEnabled())
    await userEvent.click(execute)
    const drawer = within(screen.getByRole('dialog'))
    expect(drawer.getAllByText(`${ids.task}@3`).length).toBeGreaterThan(0)
    expect(drawer.getByRole('button', { name: '执行已发布固定版本' })).toBeDisabled()
    await userEvent.click(drawer.getByRole('checkbox'))
    await userEvent.click(drawer.getByRole('button', { name: '执行已发布固定版本' }))
    await waitFor(() => expect(executed).toHaveBeenCalledTimes(1))
    expect(executed).toHaveBeenCalledWith({
      resource_digest: 'a'.repeat(64),
      environment_fingerprint: 'a'.repeat(64),
      confirmed: true,
    })
  })
  it.each([
    { reason_codes: [] },
    { plan_run_ids: [] },
    { plan_run_ids: [ids.task, ids.execution] },
    { sealed_at: selfTestBatch.sealed_at },
  ])('keeps unsafe or finished dispatch recovery closed: %j', async (override) => {
    server.use(
      http.get(`${base}/runs/${ids.batch}`, () =>
        HttpResponse.json({
          ...selfTestBatch,
          phase: 'running',
          sealed_at: null,
          sealed_verdict: null,
          verdict: 'blocked',
          reason_codes: ['SELFTEST_DISPATCH_UNCONFIRMED'],
          resource_snapshot: snapshot,
          ...override,
        }),
      ),
      http.get(`${base}/runs/${ids.batch}/generation`, () =>
        HttpResponse.json({ ...generation, sources: [source] }),
      ),
    )
    mount()
    await screen.findByText('recorded-host')
    expect(screen.queryByRole('button', { name: '恢复原运行派发' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '执行已发布产物' })).toBeDisabled()
  })
  it('keeps execute disabled when the frozen snapshot exists but the MCP sources are absent', async () => {
    server.use(
      http.get(`${base}/runs/${ids.batch}`, () =>
        HttpResponse.json({ ...selfTestBatch, phase: 'ready', resource_snapshot: snapshot }),
      ),
    )
    mount()
    await screen.findByText('原始执行：失败')
    expect(screen.getByRole('button', { name: '执行已发布产物' })).toBeDisabled()
  })
  it('rejects a snapshot that drops a required frozen case', async () => {
    server.use(
      http.get(`${base}/runs/${ids.batch}`, () =>
        HttpResponse.json({
          ...selfTestBatch,
          phase: 'ready',
          resource_snapshot: { ...snapshot, cases: [] },
        }),
      ),
    )
    mount()
    expect((await screen.findAllByText(/自测响应格式或范围无效/)).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: '执行已发布产物' })).toBeDisabled()
  })
})

describe('scenario deep-link pagination', () => {
  it('reads the exact server-filtered scenario instead of guessing its original page', async () => {
    const read = vi.fn()
    server.use(
      http.get(`${base}/runs/${ids.batch}/scenarios`, ({ request }) => {
        const params = new URL(request.url).searchParams
        read(params.get('scenario_id'), params.get('page'))
        return HttpResponse.json(selfTestPage([selfTestScenario]))
      }),
    )
    mount(<QualityCenterPage />, `${entry}&scenario=ST-MCP-023`)
    await waitFor(() => expect(read).toHaveBeenCalledWith('ST-MCP-023', '1'))
    expect((await screen.findAllByText('冻结预期')).length).toBeGreaterThan(0)
  })
})

describe('authorized self-test artifacts', () => {
  const artifacts = [
    { id: ids.scenario, kind: 'execution_junit' as const, sha256: 'a'.repeat(64) },
    { id: ids.task, kind: 'verification_junit' as const, sha256: 'b'.repeat(64) },
  ]
  it('downloads raw and verification JUnit separately through their authorized IDs', async () => {
    const reads: string[] = []
    const download = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined)
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:selftest-artifact'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
    server.use(
      http.get(`${base}/runs/${ids.batch}/artifacts/:artifact`, ({ params }) => {
        reads.push(String(params.artifact))
        return HttpResponse.xml('<testsuite tests="1"/>')
      }),
    )
    mount(<SelfTestArtifacts projectId={project.id} batchId={ids.batch} artifacts={artifacts} />)
    await userEvent.click(screen.getByRole('button', { name: '原始执行 JUnit' }))
    await waitFor(() => expect(download).toHaveBeenCalledTimes(1))
    await userEvent.click(screen.getByRole('button', { name: '独立核验 JUnit' }))
    await waitFor(() => expect(download).toHaveBeenCalledTimes(2))
    expect(reads).toEqual([ids.scenario, ids.task])
    download.mockRestore()
  })
  it('preserves the standard error envelope and trace ID on an artifact 403', async () => {
    server.use(
      http.get(`${base}/runs/${ids.batch}/artifacts/:artifact`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'FORBIDDEN',
              message: '核验证据不可访问',
              trace_id: 'artifact-denied-trace',
            },
          },
          { status: 403 },
        ),
      ),
    )
    mount(<SelfTestArtifacts projectId={project.id} batchId={ids.batch} artifacts={artifacts} />)
    await userEvent.click(screen.getByRole('button', { name: '原始执行 JUnit' }))
    expect(await screen.findByText(/核验证据不可访问.*artifact-denied-trace/)).toBeVisible()
  })
})

describe('artifact selection changes', () => {
  function SwitchingArtifacts() {
    const [batchId, setBatchId] = useState(ids.batch)
    return (
      <>
        <button onClick={() => setBatchId(ids.binding)}>切换证据批次</button>
        <SelfTestArtifacts
          projectId={project.id}
          batchId={batchId}
          artifacts={[{ id: ids.task, kind: 'verification_junit', sha256: 'a'.repeat(64) }]}
        />
      </>
    )
  }
  it('does not download a late artifact into another batch or keep its controls busy', async () => {
    let finish: (() => void) | undefined
    const download = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined)
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:selftest-current'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
    server.use(
      http.get(`${base}/runs/:batch/artifacts/:artifact`, async ({ params }) => {
        if (params.batch === ids.batch)
          await new Promise<void>((done) => {
            finish = done
          })
        return HttpResponse.xml('<testsuite tests="1"/>')
      }),
    )
    mount(<SwitchingArtifacts />)
    await userEvent.click(screen.getByRole('button', { name: '独立核验 JUnit' }))
    await waitFor(() => expect(finish).toBeTypeOf('function'))
    await userEvent.click(screen.getByRole('button', { name: '切换证据批次' }))
    expect(screen.getByRole('button', { name: '独立核验 JUnit' })).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: '独立核验 JUnit' }))
    await waitFor(() => expect(download).toHaveBeenCalledTimes(1))
    await act(async () => {
      finish!()
      await delay(50)
    })
    expect(download).toHaveBeenCalledTimes(1)
    download.mockRestore()
  })
})
