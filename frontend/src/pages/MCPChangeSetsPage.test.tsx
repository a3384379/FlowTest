import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp, Button } from 'antd'
import { http, HttpResponse } from 'msw'
import { useNavigate } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { MCPChangeSet } from '../features/mcp/mcp-change-set-service'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { project, user, workflowDefinition } from '../test/fixtures'
import { server } from '../test/server'
import MCPChangeSetsPage from './MCPChangeSetsPage'

const changeSetId = '00000000-0000-4000-8000-000000009001'
const itemId = '00000000-0000-4000-8000-000000009002'

const changeSet: MCPChangeSet = {
  id: changeSetId,
  project_id: project.id,
  title: 'TestPlan 更新建议',
  status: 'draft',
  source_type: 'mcp',
  source_ref: 'mcp://proposal/test-plan',
  actor_type: 'service_account',
  source_fingerprint: 'a'.repeat(64),
  created_by_id: user.id,
  created_at: '2026-09-08T01:00:00Z',
  updated_at: '2026-09-08T01:00:00Z',
  applied_at: null,
  governance: {
    confidence: 0.9,
    risk_level: 'medium',
    requires_review: true,
    manual_approval_required: false,
    reason_codes: [],
  },
  approval: null,
  items: [
    {
      id: itemId,
      position: 0,
      item_type: 'test_plan_update',
      action: 'update',
      title: '加入回归 Workflow',
      proposed_content: { test_plan_id: 'plan-1', targets: [] },
      review_status: 'pending',
      review_note: '',
      reviewed_by_id: null,
      reviewed_at: null,
      materialized_resource_type: null,
      materialized_resource_id: null,
    },
  ],
}

describe('MCPChangeSetsPage', () => {
  it('keeps high-risk proposal evidence readable without viewer approval or materialization', async () => {
    handlers(() => ({
      ...changeSet,
      governance: { ...changeSet.governance, manual_approval_required: true },
    }))
    let writes = 0
    server.use(
      http.get(`/api/v1/projects/${project.id}/permissions`, () =>
        HttpResponse.json({
          effective_role: 'viewer',
          capabilities: ['read'],
          matrix: {},
        }),
      ),
      http.post(`/api/v1/mcp/write/change-sets/${changeSetId}/*`, () => {
        writes += 1
        return HttpResponse.json({})
      }),
    )
    renderPage(`/projects/${project.id}/mcp-changes?focus=${changeSetId}`)
    expect(await screen.findByText('加入回归 Workflow')).toBeInTheDocument()
    for (const name of ['批准变更集', '拒绝', '接受并物化']) {
      const button = screen.getByRole('button', { name: new RegExp(name) })
      expect(button).toBeDisabled()
      fireEvent.click(button)
    }
    expect(writes).toBe(0)
  })

  it('rejects a focused change set that belongs to another project', async () => {
    handlers(() => ({ ...changeSet, project_id: 'other-project' }))
    renderPage(`/projects/${project.id}/mcp-changes?focus=${changeSetId}`)
    expect(await screen.findByText(/该变更集不属于当前项目/)).toBeInTheDocument()
    expect(screen.queryByText('加入回归 Workflow')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '接受并物化' })).not.toBeInTheDocument()
  })

  it('previews a new control workflow and links its reviewed draft', async () => {
    const definition = {
      ...workflowDefinition,
      schema_version: '4.0',
      nodes: [
        ...workflowDefinition.nodes,
        {
          id: 'group',
          type: 'capability' as const,
          name: '步骤组',
          position: { x: 300, y: 0 },
          config: {},
          capability_id: 'flow.control.group',
          capability_version: '1.0.0',
          configuration: { body: { kind: 'inline', region_id: 'body' } },
        },
      ],
      regions: [
        {
          id: 'body',
          owner_node_id: 'group',
          role: 'body',
          nodes: [
            {
              id: 'wait',
              type: 'delay' as const,
              name: '等待',
              position: { x: 0, y: 0 },
              config: { seconds: 1 },
            },
          ],
          edges: [],
          entry_node_id: 'wait',
          exit_node_ids: ['wait'],
          inputs: {},
          outputs: {},
        },
      ],
    }
    let current: MCPChangeSet = {
      ...changeSet,
      title: '新建控制流提案',
      items: [
        {
          ...changeSet.items[0],
          item_type: 'workflow',
          action: 'create',
          title: '新建控制流提案',
          proposed_content: { name: '新建控制流提案', definition },
        },
      ],
    }
    handlers(() => current)
    server.use(
      http.post(`/api/v1/mcp/write/change-sets/${changeSetId}/items/${itemId}/accept`, () => {
        current = {
          ...current,
          status: 'accepted',
          items: [
            {
              ...current.items[0],
              review_status: 'accepted',
              materialized_resource_id: '00000000-0000-4000-8000-000000009011',
              materialized_resource_type: 'workflow',
            },
          ],
        }
        return HttpResponse.json(envelope(current))
      }),
    )
    renderPage(`/projects/${project.id}/mcp-changes?focus=${changeSetId}`)
    const browser = userEvent.setup()

    expect(await screen.findByText('flow.control.group')).toBeVisible()
    expect(screen.getByText('区域 body：等待')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: '查看提案图' }))
    expect(await screen.findByText('主连线 2')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Close', hidden: true }))
    await browser.click(screen.getByRole('button', { name: '接受并物化' }))
    expect(await screen.findByRole('link', { name: '查看已创建草稿' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/workflows?focus=00000000-0000-4000-8000-000000009011`,
    )
  })

  it('shows a native control block before human acceptance', async () => {
    const workflowId = '00000000-0000-4000-8000-000000009010'
    let current: MCPChangeSet = {
      ...changeSet,
      title: '控制块提案：重复检查',
      workflow_id: workflowId,
      base_revision: 3,
      items: [
        {
          ...changeSet.items[0],
          item_type: 'workflow',
          title: '重复检查',
          target_resource_id: workflowId,
          proposed_content: {
            expected_revision: 3,
            edge_id: 'health-end',
            node: { name: '重复检查', capability_id: 'flow.control.repeat' },
            regions: [{ id: 'body', role: 'body', nodes: [{ name: '等待一秒' }] }],
          },
        },
      ],
    }
    handlers(() => current)
    server.use(
      http.get(`/api/v1/mcp/write/change-sets/${changeSetId}/control-block-preview`, () =>
        HttpResponse.json({
          workflow_id: workflowId,
          base_revision: 3,
          existing_definition: workflowDefinition,
          proposed_definition: {
            ...workflowDefinition,
            schema_version: '4.0',
            nodes: [
              ...workflowDefinition.nodes,
              {
                id: 'repeat',
                type: 'capability',
                name: '重复检查',
                position: { x: 160, y: 0 },
                config: {},
                capability_id: 'flow.control.repeat',
                capability_version: '1.0.0',
                configuration: { body: { kind: 'inline', region_id: 'body' }, count: 3 },
              },
            ],
            edges: [
              ...workflowDefinition.edges.map((edge) =>
                edge.id === 'api-end' ? { ...edge, target: 'repeat' } : edge,
              ),
              {
                id: 'repeat-end',
                source: 'repeat',
                target: 'end',
                condition: null,
                mappings: [],
              },
            ],
            regions: [
              {
                id: 'body',
                owner_node_id: 'repeat',
                role: 'body',
                nodes: [
                  {
                    id: 'wait',
                    type: 'delay',
                    name: '等待一秒',
                    position: { x: 0, y: 0 },
                    config: { seconds: 1 },
                  },
                ],
                edges: [],
                entry_node_id: 'wait',
                exit_node_ids: ['wait'],
                inputs: {},
                outputs: {},
              },
            ],
          },
        }),
      ),
      http.post(`/api/v1/mcp/write/change-sets/${changeSetId}/items/${itemId}/accept`, () => {
        current = {
          ...current,
          status: 'accepted',
          items: [
            {
              ...current.items[0],
              review_status: 'accepted',
              materialized_resource_type: 'workflow',
              materialized_resource_id: workflowId,
            },
          ],
        }
        return HttpResponse.json(envelope(current))
      }),
    )
    renderPage(`/projects/${project.id}/mcp-changes?focus=${changeSetId}`)
    const browser = userEvent.setup()

    expect(await screen.findByText('flow.control.repeat')).toBeVisible()
    expect(screen.getByText('插入连线：health-end')).toBeVisible()
    expect(screen.getByText('区域 body：等待一秒')).toBeVisible()
    expect(screen.getByText(/基线修订号 3/)).toBeVisible()
    expect(screen.getByRole('link', { name: '查看目标工作流' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/workflows?focus=${workflowId}`,
    )
    await browser.click(screen.getByRole('button', { name: '查看图形差异' }))
    expect(await screen.findByText('新增节点 1')).toBeInTheDocument()
    expect(screen.getByText('重接连线 1')).toBeInTheDocument()
    expect(screen.getByText('新增区域 1')).toBeInTheDocument()
    expect(screen.getByText('原草稿')).toBeInTheDocument()
    expect(screen.getByText('提案结果')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Close', hidden: true }))
    await browser.click(screen.getByRole('button', { name: '接受并物化' }))
    expect(await screen.findByText('已接受')).toBeVisible()
  })

  it('loads the exact focused proposal and reviews its item', async () => {
    let reviewed = false
    let current = changeSet
    handlers(() => current)
    server.use(
      http.post(`/api/v1/mcp/write/change-sets/${changeSetId}/items/${itemId}/accept`, () => {
        reviewed = true
        current = {
          ...current,
          status: 'accepted',
          items: [
            {
              ...current.items[0],
              review_status: 'accepted',
              materialized_resource_type: 'test_plan',
              materialized_resource_id: 'plan-1',
            },
          ],
        }
        return HttpResponse.json(envelope(current))
      }),
    )
    renderPage(`/projects/${project.id}/mcp-changes?focus=${changeSetId}`)
    const browser = userEvent.setup()

    expect(await screen.findByText('TestPlan 更新建议')).toBeVisible()
    expect(screen.getByText('加入回归 Workflow')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: '接受并物化' }))
    await waitFor(() => expect(reviewed).toBe(true))
    expect(await screen.findByText('已接受')).toBeVisible()
  })

  it('shows envelope warnings, copyable trace, confidence and approval evidence', async () => {
    const current = {
      ...changeSet,
      approval: {
        id: 'approval-1',
        decision: 'approved',
        approved_by_id: user.id,
        approved_at: '2026-10-22T01:02:03Z',
      },
      governance: {
        ...changeSet.governance,
        reason_codes: ['low_confidence_assertion_review', 'future_reason'],
      },
    }
    server.use(
      http.get(`/api/v1/mcp/write/change-sets/${changeSetId}`, () =>
        HttpResponse.json({
          ...envelope(current),
          warnings: ['已有警告必须在审核前可见'],
          trace_id: 'mcp-trace-exact',
        }),
      ),
    )
    renderPage(`/projects/${project.id}/mcp-changes?focus=${changeSetId}`)
    expect(await screen.findByText('已有警告必须在审核前可见')).toBeVisible()
    expect(screen.getByText('mcp-trace-exact')).toBeVisible()
    expect(screen.getByText('90%')).toBeVisible()
    expect(screen.getByText(/future_reason/)).toBeVisible()
    expect(screen.getByText('approval-1')).toBeVisible()
    expect(screen.getByText('2026-10-22T01:02:03Z')).toBeVisible()
    const browser = userEvent.setup()
    const copy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
    await browser.click(screen.getByRole('button', { name: '复制 Trace ID' }))
    expect(copy).toHaveBeenCalledWith('mcp-trace-exact')
  })

  it('shows fixed plan actions and explicitly identifies missing before environment and retry', async () => {
    handlers(() => ({
      ...changeSet,
      items: [
        {
          ...changeSet.items[0],
          proposed_content: {
            test_plan_id: 'plan-precise',
            rationale: '补充支付回归',
            targets: [
              {
                target_type: 'workflow',
                target_id: 'workflow-precise',
                target_version: 5,
                workflow_version: 5,
                environment_id: 'environment-new',
                max_retries: 2,
                runtime_variables: { tenant: 'blue' },
                runtime_headers: {},
              },
            ],
            target_actions: [
              {
                target_type: 'workflow',
                target_id: 'workflow-precise',
                action: 'update',
                current_version: 4,
                requested_version: 5,
                current_fingerprint: 'old-fingerprint',
                requested_fingerprint: 'new-fingerprint',
                reason: '目标版本变化',
              },
            ],
            unpublished_dependencies: ['待发布依赖'],
          },
        },
      ],
    }))
    renderPage(`/projects/${project.id}/mcp-changes?focus=${changeSetId}`)
    expect(await screen.findByText('测试计划更新预览')).toBeVisible()
    expect(screen.getByText('environment-new')).toBeVisible()
    expect(screen.getByText('4 → 5')).toBeVisible()
    expect(screen.getByText('old-fingerprint')).toBeVisible()
    expect(screen.getByText('new-fingerprint')).toBeVisible()
    expect(screen.getByText(/未保存原环境、重试及运行参数/)).toBeVisible()
    expect(screen.getByText('待发布依赖')).toBeVisible()
    expect(screen.getByText('补充支付回归')).toBeVisible()
  })

  it('previews a test case as its fixed workflow and environment without invented assertions', async () => {
    handlers(() => ({
      ...changeSet,
      items: [
        {
          ...changeSet.items[0],
          item_type: 'test_case',
          action: 'create',
          proposed_content: {
            name: '支付测试用例',
            description: '真实提案说明',
            tags: ['smoke'],
            definition: {
              workflow_id: 'workflow-fixed',
              workflow_version: null,
              environment_id: 'environment-fixed',
              runtime_variables: { customer: 'authorized@example.com' },
              runtime_headers: {},
            },
          },
        },
      ],
    }))
    renderPage(`/projects/${project.id}/mcp-changes?focus=${changeSetId}`)
    expect(await screen.findByText('测试用例预览')).toBeVisible()
    expect(screen.getByText('未固定，发布时需确认')).toBeVisible()
    expect(screen.getByText('environment-fixed')).toBeVisible()
    expect(screen.getByText(/断言沿用所引用工作流/)).toBeVisible()
  })

  it('keeps high-risk materialization disabled when a stored approval is rejected', async () => {
    handlers(() => ({
      ...changeSet,
      governance: { ...changeSet.governance, manual_approval_required: true },
      approval: {
        id: 'rejected-approval',
        decision: 'rejected',
        approved_by_id: user.id,
        approved_at: '2026-10-22T01:00:00Z',
      },
    }))
    renderPage(`/projects/${project.id}/mcp-changes?focus=${changeSetId}`)
    expect(await screen.findByRole('button', { name: '接受并物化' })).toBeDisabled()
    expect(screen.getByText(/审批尚未通过/)).toBeVisible()
  })

  it('opens real materialized case and plan objects using their returned result types', async () => {
    const accepted = {
      ...changeSet,
      status: 'accepted' as const,
      items: [
        {
          ...changeSet.items[0],
          id: 'case-result-item',
          item_type: 'test_case' as const,
          review_status: 'accepted' as const,
          materialized_resource_type: 'test_case',
          materialized_resource_id: 'case-result',
          proposed_content: {},
        },
        {
          ...changeSet.items[0],
          id: 'plan-result-item',
          review_status: 'accepted' as const,
          materialized_resource_type: 'test_plan',
          materialized_resource_id: 'plan-result',
        },
      ],
    }
    handlers(() => accepted)
    renderPage(`/projects/${project.id}/mcp-changes?focus=${changeSetId}`)
    expect(await screen.findByRole('link', { name: '查看物化测试用例' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/assets?type=case&focus=case-result&version=draft`,
    )
    expect(screen.getByRole('link', { name: '查看更新后的计划' })).toHaveAttribute(
      'href',
      `/projects/${project.id}/tasks?focus=plan-result`,
    )
  })

  it('opens the saved design through an exact read instead of inventing a TestEngineering URL', async () => {
    const savedId = 'saved-design-id'
    const designItem = {
      ...changeSet.items[0],
      item_type: 'test_design' as const,
      action: 'create' as const,
      review_status: 'accepted' as const,
      materialized_resource_type: 'test_design',
      materialized_resource_id: savedId,
      proposed_content: {
        intent: { key: 'proposal', objective: '原始提案内容', acceptance_criteria: [] },
        oracles: [],
        scenarios: [],
        coverage: { entries: [] },
        evidence_refs: [],
        warnings: [],
        review_requirements: [],
      },
    }
    handlers(() => ({ ...changeSet, items: [designItem] }))
    let reads = 0
    server.use(
      http.get(
        `/api/v1/mcp/write/change-sets/${changeSetId}/items/${itemId}/materialized-design`,
        () => {
          reads += 1
          return HttpResponse.json({
            id: savedId,
            project_id: project.id,
            source_change_set_id: changeSetId,
            name: '已保存设计',
            status: 'approved',
            fingerprint: 'stored-fingerprint',
            reviewed_by_id: user.id,
            reviewed_at: '2026-10-22T01:00:00Z',
            design: {
              ...designItem.proposed_content,
              intent: {
                key: 'saved',
                objective: '数据库中实际保存的设计',
                acceptance_criteria: ['保存后的验收要求'],
              },
            },
          })
        },
      ),
    )
    renderPage(`/projects/${project.id}/mcp-changes?focus=${changeSetId}`)
    await userEvent.click(await screen.findByRole('button', { name: '查看已物化测试设计' }))
    const drawer = screen.getByRole('dialog', { name: '已物化测试设计（只读）' })
    expect(await within(drawer).findByText('数据库中实际保存的设计')).toBeVisible()
    expect(within(drawer).queryByText('原始提案内容')).not.toBeInTheDocument()
    expect(within(drawer).getByText(savedId)).toBeVisible()
    expect(screen.queryByRole('link', { name: /测试设计/ })).not.toBeInTheDocument()
    expect(reads).toBe(1)
  })

  it('disables review after cached evidence or permissions fail to refresh', async () => {
    handlers(() => changeSet)
    const view = renderPage(`/projects/${project.id}/mcp-changes?focus=${changeSetId}`)
    const accept = await screen.findByRole('button', { name: '接受并物化' })
    expect(accept).toBeEnabled()
    server.use(
      http.get(`/api/v1/mcp/write/change-sets/${changeSetId}`, () =>
        HttpResponse.json(
          { error: { code: 'UNAVAILABLE', message: '证据暂不可用', trace_id: 'mcp-read-stale' } },
          { status: 503 },
        ),
      ),
    )
    await act(async () => {
      await view.queryClient.invalidateQueries({ queryKey: ['mcp-change-set'] })
    })
    expect(await screen.findByText(/保留的审核证据可能过期/)).toBeVisible()
    expect(accept).toBeDisabled()
  })

  it('keeps a revision conflict visible without marking any item accepted', async () => {
    handlers(() => changeSet)
    server.use(
      http.post(`/api/v1/mcp/write/change-sets/${changeSetId}/items/${itemId}/accept`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'TEST_PLAN_SUGGESTION_STALE',
              message: '计划目标已变化，整个动作已拒绝',
              trace_id: 'mcp-conflict-trace',
            },
          },
          { status: 409 },
        ),
      ),
    )
    renderPage(`/projects/${project.id}/mcp-changes?focus=${changeSetId}`)
    await userEvent.click(await screen.findByRole('button', { name: '接受并物化' }))
    expect(await screen.findByText('审核结果未确认')).toBeVisible()
    expect(screen.getByText('Trace ID: mcp-conflict-trace')).toBeVisible()
    expect(screen.queryByText('已接受')).not.toBeInTheDocument()
  })

  it('does not apply an old review receipt or success notice to another project', async () => {
    handlers(() => changeSet)
    let finish: (response: Response) => void = () => undefined
    let called = false
    const sibling = { ...project, id: '00000000-0000-4000-8000-000000009099', name: '另一个项目' }
    const otherChange = '00000000-0000-4000-8000-000000009088'
    server.use(
      http.post(`/api/v1/mcp/write/change-sets/${changeSetId}/items/${itemId}/accept`, () => {
        called = true
        return new Promise<Response>((resolve) => {
          finish = resolve
        })
      }),
      http.get(`/api/v1/mcp/write/change-sets/${otherChange}`, () =>
        HttpResponse.json(
          envelope({
            ...changeSet,
            id: otherChange,
            project_id: sibling.id,
            title: '另一个项目的审核',
            items: [{ ...changeSet.items[0], id: 'other-item' }],
          }),
        ),
      ),
    )
    renderPage(`/projects/${project.id}/mcp-changes?focus=${changeSetId}`, [project, sibling])
    await userEvent.click(await screen.findByRole('button', { name: '接受并物化' }))
    await waitFor(() => expect(called).toBe(true))
    await userEvent.click(screen.getByRole('button', { name: '打开另一个项目提案' }))
    expect(await screen.findByText('另一个项目的审核')).toBeVisible()
    await act(async () => {
      finish(
        HttpResponse.json(
          envelope({
            ...changeSet,
            status: 'accepted',
            items: [
              {
                ...changeSet.items[0],
                review_status: 'accepted',
                materialized_resource_type: 'test_plan',
                materialized_resource_id: 'old-plan',
              },
            ],
          }),
        ),
      )
    })
    expect(screen.queryByText('变更项已接受并物化')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '查看更新后的计划' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '接受并物化' })).toBeEnabled()
  })

  it('blocks review if a previously loaded project permission fails to refresh', async () => {
    handlers(() => changeSet)
    const view = renderPage(`/projects/${project.id}/mcp-changes?focus=${changeSetId}`)
    const accept = await screen.findByRole('button', { name: '接受并物化' })
    expect(accept).toBeEnabled()
    server.use(
      http.get(`/api/v1/projects/${project.id}/permissions`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'UNAVAILABLE',
              message: '权限暂不可用',
              trace_id: 'mcp-permission-stale',
            },
          },
          { status: 503 },
        ),
      ),
    )
    await act(async () => {
      await view.queryClient.invalidateQueries({ queryKey: ['project-permissions'] })
    })
    expect(await screen.findByText('权限暂不可用')).toBeVisible()
    expect(accept).toBeDisabled()
    expect(screen.getByRole('button', { name: '拒绝' })).toBeDisabled()
  })

  it('blocks other review actions while manual approval is in progress', async () => {
    handlers(() => ({
      ...changeSet,
      governance: { ...changeSet.governance, manual_approval_required: true },
    }))
    let finish: (response: Response) => void = () => undefined
    server.use(
      http.post(
        `/api/v1/mcp/write/change-sets/${changeSetId}/approve`,
        () =>
          new Promise<Response>((resolve) => {
            finish = resolve
          }),
      ),
    )
    renderPage(`/projects/${project.id}/mcp-changes?focus=${changeSetId}`)
    await userEvent.click(await screen.findByRole('button', { name: '批准变更集' }))
    expect(screen.getByRole('button', { name: '拒绝' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '接受并物化' })).toBeDisabled()
    await act(async () => {
      finish(
        HttpResponse.json(
          envelope({
            ...changeSet,
            approval: {
              id: 'approval-late',
              decision: 'approved',
              approved_by_id: user.id,
              approved_at: '2026-10-22T02:00:00Z',
            },
          }),
        ),
      )
    })
  })

  it.each([
    { status: 'pending' as const, resourceType: 'workflow' },
    { status: 'accepted' as const, resourceType: 'test_case' },
  ])(
    'does not link a workflow result with $status review and $resourceType type',
    async ({ status, resourceType }) => {
      handlers(() => ({
        ...changeSet,
        items: [
          {
            ...changeSet.items[0],
            item_type: 'workflow',
            action: 'create',
            review_status: status,
            proposed_content: { name: '结果绑定反例', definition: workflowDefinition },
            materialized_resource_id: 'wrong-or-pending-id',
            materialized_resource_type: resourceType,
          },
        ],
      }))
      renderPage(`/projects/${project.id}/mcp-changes?focus=${changeSetId}`)
      await screen.findByText('结果绑定反例')
      expect(screen.queryByRole('link', { name: '查看已创建草稿' })).not.toBeInTheDocument()
      expect(screen.queryByRole('link', { name: '查看物化工作流' })).not.toBeInTheDocument()
      if (status === 'accepted')
        expect(screen.getByText('物化结果类型与变更项不匹配，无法提供安全定位')).toBeVisible()
    },
  )

  it.each(['missing-item', 'pending-item', 'wrong-result-type'])(
    'does not claim materialization for an inconsistent %s receipt',
    async (kind) => {
      handlers(() => changeSet)
      server.use(
        http.post(`/api/v1/mcp/write/change-sets/${changeSetId}/items/${itemId}/accept`, () =>
          HttpResponse.json(
            envelope({
              ...changeSet,
              items:
                kind === 'missing-item'
                  ? []
                  : [
                      {
                        ...changeSet.items[0],
                        review_status: kind === 'pending-item' ? 'pending' : 'accepted',
                        materialized_resource_type: 'test_case',
                        materialized_resource_id: 'wrong-result',
                      },
                    ],
            }),
          ),
        ),
      )
      renderPage(`/projects/${project.id}/mcp-changes?focus=${changeSetId}`)
      await userEvent.click(await screen.findByRole('button', { name: '接受并物化' }))
      expect(await screen.findByText('审核结果未确认')).toBeVisible()
      expect(screen.queryByText('变更项已接受并物化')).not.toBeInTheDocument()
      expect(screen.queryByText('已接受')).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: '重新读取变更集' })).toBeEnabled()
      expect(screen.getByRole('button', { name: '接受并物化' })).toBeDisabled()
    },
  )

  it('does not claim approval when the receipt has no approved decision', async () => {
    const current = {
      ...changeSet,
      governance: { ...changeSet.governance, manual_approval_required: true },
    }
    handlers(() => current)
    server.use(
      http.post(`/api/v1/mcp/write/change-sets/${changeSetId}/approve`, () =>
        HttpResponse.json(envelope(current)),
      ),
    )
    renderPage(`/projects/${project.id}/mcp-changes?focus=${changeSetId}`)
    await userEvent.click(await screen.findByRole('button', { name: '批准变更集' }))
    expect(await screen.findByText('审核结果未确认')).toBeVisible()
    expect(screen.queryByText('MCP 变更集已完成人工批准')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '接受并物化' })).toBeDisabled()
  })

  it('requires explicit approval before accepting a high-risk proposal', async () => {
    let current: MCPChangeSet = {
      ...changeSet,
      governance: {
        ...changeSet.governance,
        risk_level: 'high',
        manual_approval_required: true,
      },
    }
    handlers(() => current)
    server.use(
      http.post(`/api/v1/mcp/write/change-sets/${changeSetId}/approve`, () => {
        current = {
          ...current,
          approval: {
            id: '00000000-0000-4000-8000-000000009003',
            decision: 'approved',
            approved_by_id: user.id,
            approved_at: '2026-09-08T02:00:00Z',
          },
        }
        return HttpResponse.json(envelope(current))
      }),
    )
    renderPage(`/projects/${project.id}/mcp-changes?focus=${changeSetId}`)
    const browser = userEvent.setup()

    const accept = await screen.findByRole('button', { name: '接受并物化' })
    expect(accept).toBeDisabled()
    await browser.click(screen.getByRole('button', { name: /批准变更集/ }))
    await waitFor(() => expect(accept).toBeEnabled())
  })

  it('does not substitute another proposal when no focus id is provided', async () => {
    renderPage(`/projects/${project.id}/mcp-changes`)
    expect(await screen.findByText('请从资源发现结果打开一个 MCP 变更集。')).toBeVisible()
    expect(screen.queryByText('加入回归 Workflow')).not.toBeInTheDocument()
  })
})

function handlers(current: () => MCPChangeSet) {
  server.use(
    http.get(`/api/v1/mcp/write/change-sets/${changeSetId}`, () =>
      HttpResponse.json(envelope(current())),
    ),
  )
}

function envelope(data: MCPChangeSet) {
  return { data, warnings: [], trace_id: 'test-trace' }
}

function renderPage(initialEntry: string, projects = [project]) {
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: projects, total: projects.length, page: 1, page_size: 100 }),
    ),
  )
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const view = render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <ProjectTestProvider section="mcp-changes" initialEntry={initialEntry}>
          <MCPChangeSetsPage />
          <NavigationProbe />
        </ProjectTestProvider>
      </QueryClientProvider>
    </AntdApp>,
  )
  return { ...view, queryClient }
}

function NavigationProbe() {
  const navigate = useNavigate()
  return (
    <Button
      onClick={() =>
        navigate(
          '/projects/00000000-0000-4000-8000-000000009099/mcp-changes?focus=00000000-0000-4000-8000-000000009088',
        )
      }
    >
      打开另一个项目提案
    </Button>
  )
}
