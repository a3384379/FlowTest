import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

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
          items: [{ ...current.items[0], review_status: 'accepted' }],
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
          items: [{ ...current.items[0], review_status: 'accepted' }],
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

function renderPage(initialEntry: string) {
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
    ),
  )
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <ProjectTestProvider section="mcp-changes" initialEntry={initialEntry}>
          <MCPChangeSetsPage />
        </ProjectTestProvider>
      </QueryClientProvider>
    </AntdApp>,
  )
}
