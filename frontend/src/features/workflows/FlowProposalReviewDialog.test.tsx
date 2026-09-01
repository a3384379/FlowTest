import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import type { FlowSpec, FlowSpecVisualProposal } from '../../lib/api'
import {
  apiDefinition,
  environment,
  project,
  workflow,
  workflowDefinition,
} from '../../test/fixtures'
import { server } from '../../test/server'
import FlowProposalReviewDialog from './FlowProposalReviewDialog'

const changeSetId = '00000000-0000-4000-8000-000000005101'
const secondChangeSetId = '00000000-0000-4000-8000-000000005105'
const proposedDefinition = {
  ...workflowDefinition,
  nodes: [
    ...workflowDefinition.nodes.filter((node) => node.id !== 'end'),
    {
      id: 'assert-status',
      type: 'assert' as const,
      name: '校验状态',
      position: { x: 200, y: 0 },
      config: {
        source_node_id: 'api',
        expression: 'status_code',
        operator: 'equals',
        expected: 200,
      },
    },
    { ...workflowDefinition.nodes.at(-1)!, position: { x: 300, y: 0 } },
  ],
  edges: [
    { ...workflowDefinition.edges[0]!, condition: 'true' as const },
    {
      id: 'api-assert',
      source: 'api',
      target: 'assert-status',
      condition: null,
      mappings: [],
    },
    {
      id: 'assert-end',
      source: 'assert-status',
      target: 'end',
      condition: null,
      mappings: [],
    },
  ],
}

describe('FlowProposalReviewDialog', () => {
  it('reuses proposal mode for evidence review and gates apply behind human acceptance', async () => {
    let reviewStatus: 'pending' | 'accepted' = 'pending'
    let applyCalls = 0
    server.use(
      http.get(`/api/v1/projects/${project.id}/flow-specs/change-sets/proposals`, () =>
        HttpResponse.json({ items: [summary(reviewStatus)], next_cursor: null, page_size: 100 }),
      ),
      http.get(
        `/api/v1/projects/${project.id}/flow-specs/change-sets/${changeSetId}/visual-proposal`,
        () => HttpResponse.json(visualProposal(reviewStatus)),
      ),
      http.post(
        `/api/v1/projects/${project.id}/flow-specs/change-sets/${changeSetId}/review`,
        () => {
          reviewStatus = 'accepted'
          return HttpResponse.json(changeSet(reviewStatus))
        },
      ),
      http.post(
        `/api/v1/projects/${project.id}/flow-specs/change-sets/${changeSetId}/apply`,
        () => {
          applyCalls += 1
          return HttpResponse.json({
            change_set_id: changeSetId,
            workflow_id: workflow.id,
            draft_revision: 2,
            fingerprint: 'f'.repeat(64),
            applied_at: '2026-08-28T00:00:00Z',
          })
        },
      ),
    )
    let appliedWorkflowId = ''
    renderDialog((workflowId) => {
      appliedWorkflowId = workflowId
    })
    const browser = userEvent.setup()
    const dialog = await screen.findByRole('dialog')

    expect(await within(dialog).findByText('提案模式')).toBeInTheDocument()
    expect(within(dialog).getByText('新增节点')).toBeInTheDocument()
    expect(within(dialog).getByText('assert-status')).toBeInTheDocument()
    expect(within(dialog).getByText('修改连线')).toBeInTheDocument()
    expect(within(dialog).getByText('start-api')).toBeInTheDocument()
    expect(within(dialog).getByText('映射差异 / 人工检查')).toBeInTheDocument()
    expect(within(dialog).getByText('断言差异')).toBeInTheDocument()
    expect(within(dialog).getByText('证据 / 置信度')).toBeInTheDocument()
    expect(within(dialog).getByText('未决项 0')).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: '发布版本' })).not.toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: '运行' })).not.toBeInTheDocument()

    expect(within(dialog).getByRole('button', { name: '应用到工作流草稿' })).toBeDisabled()
    await browser.click(within(dialog).getByRole('button', { name: '接受' }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '应用到工作流草稿' })).not.toBeDisabled(),
    )
    await browser.click(screen.getByRole('button', { name: '应用到工作流草稿' }))
    await waitFor(() => expect(applyCalls).toBe(1))
    expect(screen.getByRole('button', { name: '应用到工作流草稿' })).toBeDisabled()
    await browser.click(screen.getByRole('button', { name: '应用到工作流草稿' }))
    expect(applyCalls).toBe(1)
    expect(appliedWorkflowId).toBe(workflow.id)
  })

  it('shows the captured existing graph and keeps raw mapping on the established path', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/flow-specs/change-sets/proposals`, () =>
        HttpResponse.json({ items: [summary('pending')], next_cursor: null, page_size: 100 }),
      ),
      http.get(
        `/api/v1/projects/${project.id}/flow-specs/change-sets/${changeSetId}/visual-proposal`,
        () => HttpResponse.json(visualProposal('pending')),
      ),
    )
    let rawProposal: FlowSpecVisualProposal | undefined
    renderDialog(
      () => undefined,
      (proposal) => {
        rawProposal = proposal
      },
    )
    const browser = userEvent.setup()
    const dialog = await screen.findByRole('dialog')
    await within(dialog).findByText('提案模式')
    await browser.click(within(dialog).getByText('现有流程图'))
    expect(await within(dialog).findByText('查询用户')).toBeInTheDocument()
    await browser.click(within(dialog).getByRole('button', { name: '原始 JSON / 跨实例映射' }))
    expect(rawProposal?.proposal.target_workflow_id).toBe(workflow.id)
    expect(rawProposal?.proposal.spec.name).toBe('MCP 用户查询提案')
  })

  it('loads stable unified proposal cursor pages only when requested', async () => {
    const requestedCursors: Array<string | null> = []
    const cursorId = '00000000-0000-4000-8000-000000005100'
    server.use(
      http.get(`/api/v1/projects/${project.id}/flow-specs/change-sets/proposals`, ({ request }) => {
        const cursor = new URL(request.url).searchParams.get('cursor_id')
        requestedCursors.push(cursor)
        if (cursor === null) {
          return HttpResponse.json({
            items: [
              {
                ...summary('pending'),
                id: cursorId,
                title: '首页 MCP 提案',
              },
            ],
            next_cursor: {
              created_at: '2026-08-28T00:00:00Z',
              id: cursorId,
            },
            page_size: 100,
          })
        }
        return HttpResponse.json({
          items: [summary('pending')],
          next_cursor: null,
          page_size: 100,
        })
      }),
      http.get(
        `/api/v1/projects/${project.id}/flow-specs/change-sets/:proposalId/visual-proposal`,
        ({ params }) => {
          const proposal = visualProposal('pending')
          if (params.proposalId === cursorId) {
            proposal.proposal = {
              ...proposal.proposal,
              id: cursorId,
              title: '首页 MCP 提案',
            }
          }
          return HttpResponse.json(proposal)
        },
      ),
    )

    renderDialog(() => undefined)
    const browser = userEvent.setup()
    const dialog = await screen.findByRole('dialog')

    await within(dialog).findByText('提案模式')
    expect(requestedCursors).toEqual([null])
    await browser.click(within(dialog).getByRole('button', { name: '加载更多提案' }))
    await waitFor(() => expect(requestedCursors).toEqual([null, cursorId]))
    await browser.click(within(dialog).getByRole('combobox', { name: '流程提案' }))

    expect(
      await screen.findByText('MCP 用户查询提案 · 草稿 · 00000000', {
        selector: '.ant-select-item-option-content',
      }),
    ).toBeInTheDocument()
  })

  it('classifies a rewired edge with semantic changes as both rewired and modified', async () => {
    const proposal = visualProposal('pending')
    proposal.proposed_definition = {
      ...workflowDefinition,
      edges: workflowDefinition.edges.map((edge) =>
        edge.id === 'start-api' ? { ...edge, target: 'end', condition: 'true' as const } : edge,
      ),
    }
    server.use(
      http.get(`/api/v1/projects/${project.id}/flow-specs/change-sets/proposals`, () =>
        HttpResponse.json({ items: [summary('pending')], next_cursor: null, page_size: 100 }),
      ),
      http.get(
        `/api/v1/projects/${project.id}/flow-specs/change-sets/${changeSetId}/visual-proposal`,
        () => HttpResponse.json(proposal),
      ),
    )

    renderDialog(() => undefined)

    const dialog = await screen.findByRole('dialog')
    await within(dialog).findByText('修改连线')
    expect(within(dialog).getAllByText('start-api')).toHaveLength(2)
    expect(within(dialog).getByText('重连连线')).toBeInTheDocument()
  })

  it('localizes the empty assertion diff state', async () => {
    const proposal = visualProposal('pending')
    proposal.proposal.diff = []
    server.use(
      http.get(`/api/v1/projects/${project.id}/flow-specs/change-sets/proposals`, () =>
        HttpResponse.json({ items: [summary('pending')], next_cursor: null, page_size: 100 }),
      ),
      http.get(
        `/api/v1/projects/${project.id}/flow-specs/change-sets/${changeSetId}/visual-proposal`,
        () => HttpResponse.json(proposal),
      ),
    )

    renderDialog(() => undefined)

    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('没有断言变化')).toBeInTheDocument()
    expect(within(dialog).queryByText('没有 Assert 变化')).not.toBeInTheDocument()
  })

  it('does not show an applied override under a proposal selected while apply is pending', async () => {
    let finishApply!: () => void
    const applyPending = new Promise<void>((resolve) => {
      finishApply = resolve
    })
    const first = visualProposal('accepted')
    const second = visualProposal('pending')
    second.proposal = {
      ...second.proposal,
      id: secondChangeSetId,
      title: '第二个 MCP 提案',
    }
    second.proposed_definition = {
      ...second.proposed_definition,
      nodes: second.proposed_definition.nodes.map((node) =>
        node.id === 'api' ? { ...node, name: '第二提案查询' } : node,
      ),
    }
    server.use(
      http.get(`/api/v1/projects/${project.id}/flow-specs/change-sets/proposals`, () =>
        HttpResponse.json({
          items: [first.proposal, second.proposal],
          next_cursor: null,
          page_size: 100,
        }),
      ),
      http.get(
        `/api/v1/projects/${project.id}/flow-specs/change-sets/:proposalId/visual-proposal`,
        ({ params }) => HttpResponse.json(params.proposalId === secondChangeSetId ? second : first),
      ),
      http.post(
        `/api/v1/projects/${project.id}/flow-specs/change-sets/${changeSetId}/apply`,
        async () => {
          await applyPending
          return HttpResponse.json({
            change_set_id: changeSetId,
            workflow_id: workflow.id,
            draft_revision: 2,
            fingerprint: 'f'.repeat(64),
            applied_at: '2026-08-28T00:00:00Z',
          })
        },
      ),
    )
    renderDialog(() => undefined)
    const browser = userEvent.setup()
    const dialog = await screen.findByRole('dialog')

    await within(dialog).findByText('提案模式')
    await browser.click(within(dialog).getByRole('button', { name: '应用到工作流草稿' }))
    await browser.click(within(dialog).getByRole('combobox', { name: '流程提案' }))
    await browser.click(
      await screen.findByText('第二个 MCP 提案 · 草稿 · 00000000', {
        selector: '.ant-select-item-option-content',
      }),
    )
    expect(await within(dialog).findByText('第二提案查询')).toBeInTheDocument()

    finishApply()

    await waitFor(() =>
      expect(within(dialog).getByRole('button', { name: '接受' })).toBeInTheDocument(),
    )
    expect(within(dialog).getByText('第二提案查询')).toBeInTheDocument()
  })

  it('runs an accepted proposal only in sandbox and renders live preview evidence', async () => {
    const executionId = '00000000-0000-4000-8000-000000005500'
    const approvalId = '00000000-0000-4000-8000-000000005501'
    let approvalEnvironment = ''
    let executeCalls = 0
    server.use(
      http.get(`/api/v1/projects/${project.id}/flow-specs/change-sets/proposals`, () =>
        HttpResponse.json({ items: [summary('accepted')], next_cursor: null, page_size: 100 }),
      ),
      http.get(
        `/api/v1/projects/${project.id}/flow-specs/change-sets/${changeSetId}/visual-proposal`,
        () => HttpResponse.json(visualProposal('accepted')),
      ),
      http.post(
        `/api/v1/projects/${project.id}/flow-specs/change-sets/${changeSetId}/preview-approvals`,
        async ({ request }) => {
          const body = (await request.json()) as { environment_id: string }
          approvalEnvironment = body.environment_id
          return HttpResponse.json({ id: approvalId }, { status: 201 })
        },
      ),
      http.post(
        `/api/v1/projects/${project.id}/flow-specs/change-sets/${changeSetId}/preview-executions`,
        () => {
          executeCalls += 1
          return HttpResponse.json({ execution: { id: executionId } }, { status: 202 })
        },
      ),
      http.get(`/api/v1/projects/${project.id}/workflow-executions/${executionId}`, () =>
        HttpResponse.json({
          execution: {
            id: executionId,
            environment_id: environment.id,
            run_purpose: 'preview',
            status: 'passed',
            cleanup_status: 'passed',
            preview_approval_id: approvalId,
            preview_evidence: {
              binding_trace: [{ node_id: 'api', mappings: [] }],
              assert_result: [{ node_id: 'assert-status', assertions: [{ passed: true }] }],
              cleanup_result: { required_failures: [] },
              budget_usage: { requests: { limit: 10, used: 2, remaining: 8 } },
            },
          },
          nodes: [{ node_id: 'api', status: 'passed' }],
        }),
      ),
      http.get(
        `/api/v1/projects/${project.id}/workflow-executions/${executionId}/checkpoints`,
        () => HttpResponse.json([{ node_id: 'assert-status', status: 'passed' }]),
      ),
    )

    renderDialog(() => undefined)
    const browser = userEvent.setup()
    const dialog = await screen.findByRole('dialog')
    const previewButton = await within(dialog).findByRole('button', {
      name: '一次性批准并运行 Sandbox Preview',
    })
    expect(previewButton).not.toBeDisabled()
    await browser.click(previewButton)

    expect(await within(dialog).findByText('Sandbox Preview Evidence')).toBeInTheDocument()
    expect(within(dialog).getByText('Binding Trace')).toBeInTheDocument()
    expect(within(dialog).getByText('Assert Result')).toBeInTheDocument()
    expect(within(dialog).getByText('Cleanup Result')).toBeInTheDocument()
    expect(within(dialog).getByText('Budget Usage')).toBeInTheDocument()
    expect(within(dialog).getByText(/"used": 2/)).toBeInTheDocument()
    expect(approvalEnvironment).toBe(environment.id)
    expect(executeCalls).toBe(1)
  })

  it('discovers a repair proposal from the unified proposal list after reopening', async () => {
    const repair = visualProposal('pending')
    repair.proposal = {
      ...repair.proposal,
      title: '失败执行数据修复',
      source_ref: 'repair://workflow-executions/00000000-0000-4000-8000-000000005800',
    }
    server.use(
      http.get(`/api/v1/projects/${project.id}/flow-specs/change-sets/proposals`, () =>
        HttpResponse.json({
          items: [
            {
              ...summary('pending'),
              title: repair.proposal.title,
              source_ref: repair.proposal.source_ref,
              proposal_origin: 'repair',
            },
          ],
          next_cursor: null,
          page_size: 100,
        }),
      ),
      http.get(
        `/api/v1/projects/${project.id}/flow-specs/change-sets/${changeSetId}/visual-proposal`,
        () => HttpResponse.json(repair),
      ),
    )

    renderDialog(() => undefined)

    const dialog = await screen.findByRole('dialog', {
      name: 'Repair Proposal 可视化审核',
    })
    expect(
      await within(dialog).findByText(
        'Repair Proposal 不会自动修改测试；人工接受后需使用新的单次审批 Re-preview。',
      ),
    ).toBeInTheDocument()
    expect(within(dialog).getByText('失败执行数据修复 · 草稿 · 00000000')).toBeInTheDocument()
    expect(within(dialog).queryByText('暂无流程提案')).not.toBeInTheDocument()
  })
})

function renderDialog(
  onApplied: (workflowId: string) => void,
  onOpenRawMapping: (proposal: FlowSpecVisualProposal) => void = () => undefined,
  initialProposalId?: string,
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <FlowProposalReviewDialog
          open
          projectId={project.id}
          initialProposalId={initialProposalId}
          resources={{
            environments: [
              { ...environment, classification: 'sandbox' },
              {
                ...environment,
                id: '00000000-0000-4000-8000-000000005599',
                name: '生产环境',
                classification: 'production',
              },
            ],
            apis: [apiDefinition],
            artifacts: [],
            workflows: [workflow],
            credentials: [],
            graphqlSchemas: [],
            grpcDescriptors: [],
            eventSources: [],
          }}
          onClose={() => undefined}
          onApplied={onApplied}
          onOpenRawMapping={onOpenRawMapping}
        />
      </QueryClientProvider>
    </AntdApp>,
  )
}

function visualProposal(reviewStatus: 'pending' | 'accepted'): FlowSpecVisualProposal {
  return {
    schema_version: 'flowtest-visual-flow-proposal-v1',
    proposal: changeSet(reviewStatus),
    existing_definition: workflowDefinition,
    proposed_definition: proposedDefinition,
    integration_plan: {
      schema_version: 'flowtest-integration-plan-v1',
      plan_fingerprint: 'a'.repeat(64),
      context_revision_id: '00000000-0000-4000-8000-000000005102',
      context_fingerprint: 'b'.repeat(64),
      objective: '检查查询与断言流程',
      operations: [
        {
          ref: 'users.query',
          service_ref: 'users',
          name: 'Query Users',
          method: 'GET',
          path: '/users',
          evidence_refs: ['contract://users/query'],
        },
      ],
      bindings: [],
      oracles: [
        {
          id: 'status-ok',
          step_id: 'api',
          kind: 'status',
          expression: 'status_code',
          requires_review: false,
          evidence_refs: ['contract://users/query/status'],
        },
      ],
      unresolved_items: [],
      review_requirements: ['检查 Operation Mapping'],
      confidence: { overall: 0.96, evidence_coverage: 1, deterministic: true },
      diagnostics: [],
      evidence_refs: ['contract://users/query', 'context://s51/operator'],
    },
    compilation: {
      compiler_version: 'flowtest-integration-plan-compiler-v1',
      plan_fingerprint: 'a'.repeat(64),
      flow_spec: flowSpec(),
      flow_spec_fingerprint: 'c'.repeat(64),
      importable: true,
      diagnostics: [],
      node_evidence: [{ resource_id: 'api', evidence_refs: ['contract://users/query'] }],
      edge_evidence: [],
      diff: [{ path: '$.assertions', before: [], after: ['status-ok'] }],
    },
    service_mappings: { users: '00000000-0000-4000-8000-000000005103' },
    operation_mappings: { 'users.query': apiDefinition.id },
    operation_version_mappings: { 'users.query': 1 },
  }
}

function summary(reviewStatus: 'pending' | 'accepted') {
  return { ...changeSet(reviewStatus), proposal_origin: 'mcp' as const }
}

function changeSet(reviewStatus: 'pending' | 'accepted') {
  return {
    id: changeSetId,
    project_id: project.id,
    title: 'MCP 用户查询提案',
    status: reviewStatus === 'pending' ? 'draft' : 'accepted',
    source_type: 'flow_spec' as const,
    source_ref: 'mcp://contexts/s51/flow-drafts',
    source_fingerprint: 'c'.repeat(64),
    target_workflow_id: workflow.id,
    target_revision: 1,
    target_snapshot_sha256: 'd'.repeat(64),
    review_status: reviewStatus,
    reviewed_by_id: null,
    reviewed_at: null,
    applied_at: null,
    created_by_id: '00000000-0000-4000-8000-000000005104',
    created_at: '2026-08-28T00:00:00Z',
    updated_at: '2026-08-28T00:00:00Z',
    spec: flowSpec(),
    validation: { valid: true, issues: [], warnings: [], requires_review: true },
    compatibility: {
      compatible: true,
      source_schema_version: 'flowtest-flow-spec-v1',
      target_schema_version: 'flowtest-flow-spec-v1',
      blockers: [],
      warnings: [],
      requires_review: true,
    },
    diff: [{ path: '$.assertions', before: [], after: ['status-ok'] }],
  }
}

function flowSpec(): FlowSpec {
  return {
    schema_version: 'flowtest-flow-spec-v1',
    fingerprint_version: 'flowtest-flow-spec-fingerprint-v3',
    project_id: project.id,
    name: 'MCP 用户查询提案',
    description: '',
    source_evidence: ['contract://users/query'],
    services: [{ ref: 'users', name: 'Users', service_type: 'http' }],
    operations: [
      {
        ref: 'users.query',
        service_ref: 'users',
        name: 'Query Users',
        method: 'GET',
        path: '/users',
        version_strategy: 'pinned',
        source_version: 1,
        contract_fingerprint: 'e'.repeat(64),
      },
    ],
    nodes: [],
    edges: [],
    variables: {},
    settings: workflowDefinition.settings,
    bindings: [],
    parameters: [],
    assertions: [],
    cleanup: [],
    security_policy: { secret_refs_only: true, max_requests: 20, allow_private_network: false },
    confidence: { overall: 0.96, unresolved: [] },
  }
}
