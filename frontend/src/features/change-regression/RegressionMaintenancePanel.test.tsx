import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../../test/server'
import { project } from '../../test/fixtures'
import RegressionMaintenancePanel from './RegressionMaintenancePanel'
import type { ChangeRegressionRun } from './change-regression-service'
import type { RegressionMaintenance } from './regression-maintenance-service'

const root = `/api/v1/projects/${project.id}/change-regressions/run/context-maintenance`
const snapshot: RegressionMaintenance = {
  schema_version: 's47.4-change-regression-v4',
  impact_run_id: 'impact',
  context_diff_ref: 'context-diff://context/before/after',
  knowledge_diff_ref: 'context-diff://context/before/after/knowledge',
  comparison: {
    context_id: 'context',
    before_revision: 2,
    after_revision: 3,
    before_revision_id: 'before',
    after_revision_id: 'after',
    difference: {
      before_fingerprint: 'a'.repeat(64),
      after_fingerprint: 'b'.repeat(64),
      changed: true,
      evidence: { added: ['evidence'], removed: [] },
      conflicts: { added: [], removed: [] },
      knowledge: {
        changed: true,
        nodes: [{ node_id: 'event', changed_fact_names: ['revision'] }],
        edges: { added: [], removed: [] },
      },
    },
  },
  affected: {
    total_workflows: 2,
    scanned_workflow_ids: ['flow'],
    analysis_complete: false,
    diagnostics: [
      { code: 'CONTEXT_CHANGE_UNMAPPED', workflow_id: null },
      { code: 'NODE_NOT_ANALYZED', workflow_id: 'other' },
    ],
    affected_workflows: [
      {
        workflow_id: 'flow',
        draft_revision: 1,
        reasons: [
          {
            source_ref: 'knowledge://event',
            match_strength: 'instance',
            knowledge_relation: 'explicit',
          },
        ],
      },
      {
        workflow_id: 'heuristic',
        draft_revision: 1,
        reasons: [
          {
            source_ref: 'knowledge://guess',
            match_strength: 'portable',
            knowledge_relation: 'heuristic',
          },
        ],
      },
    ],
  },
  proposals: [],
  review: null,
  required_workflows: [],
  preview_counts_as_execution: false,
  automatic_apply_allowed: false,
}

function mount(maintenance: RegressionMaintenance | null = snapshot, status = 'review_required') {
  const run = {
    id: 'run',
    project_id: project.id,
    impact_run_id: 'impact',
    status,
    context_maintenance: maintenance,
  } as ChangeRegressionRun
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <ConfigProvider theme={{ token: { motion: false } }}>
        <RegressionMaintenancePanel run={run} />
      </ConfigProvider>
    </QueryClientProvider>,
  )
}

describe('S59D existing regression integration', () => {
  it('binds immutable revisions without rewriting a historical run automatically', async () => {
    const user = userEvent.setup()
    let bound: unknown
    server.use(
      http.get(`/api/v1/projects/${project.id}/contexts`, () =>
        HttpResponse.json({
          items: [{ id: 'context', name: '订单证据', current_revision: 3 }],
          total: 1,
        }),
      ),
      http.put(root, async ({ request }) => {
        bound = await request.json()
        return HttpResponse.json({})
      }),
    )
    mount(null)
    expect(screen.getByText(/历史 v3/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '绑定 / 刷新 Context 对比' }))
    await user.click(screen.getByLabelText('Context'))
    await user.click(await screen.findByText('订单证据 · r3'))
    await user.type(screen.getByLabelText('前版本'), '2')
    await user.type(screen.getByLabelText('后版本（当前 Ready 版本）'), '3')
    await user.click(screen.getByRole('button', { name: '固定对比证据' }))
    await waitFor(() =>
      expect(bound).toEqual({ context_id: 'context', before_revision: 2, after_revision: 3 }),
    )
  })

  it('shows frozen evidence and existing review links, but no mutations on terminal runs', () => {
    mount(
      {
        ...snapshot,
        affected: { ...snapshot.affected, analysis_complete: true },
        proposals: [
          {
            change_set_id: 'proposal',
            workflow_id: 'flow',
            review_status: 'accepted',
            applied: true,
          },
          {
            change_set_id: 'pending',
            workflow_id: 'flow',
            review_status: 'pending',
            applied: false,
          },
        ],
        review: {
          actor_id: 'actor',
          reviewed_at: '2026-09-05',
          note: '固定审核证据',
          acknowledged_incomplete_analysis: true,
        },
        required_workflows: [
          { workflow_id: 'flow', workflow_version: 2, fingerprint: 'f'.repeat(64) },
        ],
      },
      'passed',
    )
    expect(screen.getByText('分析完整')).toBeInTheDocument()
    expect(screen.getByText(/正式回归要求：flow v2/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '审核维护提案 proposal' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/workflows?proposal=proposal`,
    )
    expect(screen.queryByRole('button', { name: '确认维护证据审核' })).not.toBeInTheDocument()
  })

  it('records explicit human review and surfaces backend blockers', async () => {
    const user = userEvent.setup()
    let reviewed: unknown
    server.use(
      http.post(`${root}/review`, async ({ request }) => {
        reviewed = await request.json()
        return HttpResponse.json(
          { error: { code: 'PLAN_GAP', message: '请先发布并加入固定计划', trace_id: 'fixture' } },
          { status: 409 },
        )
      }),
    )
    mount()
    expect(screen.getByText('分析不完整，需人工补充检查')).toBeInTheDocument()
    await user.type(screen.getByLabelText('维护证据审核说明'), '已检查全部差异并补充人工验证')
    await user.click(screen.getByLabelText('已检查未覆盖诊断并完成人工补充检查'))
    await user.click(screen.getByRole('button', { name: '确认维护证据审核' }))
    await waitFor(() =>
      expect(reviewed).toEqual({
        note: '已检查全部差异并补充人工验证',
        acknowledge_incomplete_analysis: true,
      }),
    )
    expect(await screen.findByText('请先发布并加入固定计划')).toBeInTheDocument()
  })

  it('explicitly links an existing proposal instead of parsing a URI', async () => {
    const user = userEvent.setup()
    let linked: unknown
    server.use(
      http.post(`${root}/proposals`, async ({ request }) => {
        linked = await request.json()
        return HttpResponse.json({})
      }),
    )
    mount()
    await user.type(screen.getByLabelText('已有维护提案 ID'), 'proposal')
    await user.click(screen.getByRole('button', { name: '关联已有提案' }))
    await waitFor(() => expect(linked).toEqual({ change_set_id: 'proposal' }))
  })

  it('creates only an explicit manual patch, with server-bound revisions and an idempotency key', async () => {
    const user = userEvent.setup()
    let submitted: Record<string, unknown> | undefined
    let key: string | null = null
    server.use(
      http.get(`/api/v1/projects/${project.id}/flow-specs/workflows/flow/export`, () =>
        HttpResponse.json({ spec: { variables: {} } }),
      ),
      http.post(`${root}/workflows/flow/proposals`, async ({ request }) => {
        submitted = (await request.json()) as Record<string, unknown>
        key = request.headers.get('Idempotency-Key')
        return HttpResponse.json({}, { status: 201 })
      }),
    )
    mount()
    expect(screen.getByRole('button', { name: '读取当前 FlowSpec' })).toBeDisabled()
    await user.click(screen.getByLabelText('精确受影响流程'))
    expect(screen.queryByRole('option', { name: 'heuristic' })).not.toBeInTheDocument()
    await user.click(screen.getByText('flow', { selector: '.ant-select-item-option-content' }))
    await user.click(screen.getByRole('button', { name: '读取当前 FlowSpec' }))
    await waitFor(() =>
      expect(screen.getByLabelText('修改后的完整 FlowSpec JSON')).toHaveValue(
        JSON.stringify({ variables: {} }, null, 2),
      ),
    )
    await user.type(screen.getByLabelText('维护理由'), '更新测试数据')
    await user.click(screen.getByRole('button', { name: '创建并原子关联维护提案' }))
    await waitFor(() =>
      expect(submitted).toMatchObject({
        context_id: 'context',
        before_revision: 2,
        after_revision: 3,
        impact_run_id: 'impact',
        expected_target_revision: 1,
        kind: 'data',
        proposed_spec: { variables: {} },
      }),
    )
    expect(key).toBeTruthy()
  })
})
