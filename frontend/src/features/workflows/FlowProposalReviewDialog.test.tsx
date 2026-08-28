import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import type { FlowSpec, FlowSpecVisualProposal } from '../../lib/api'
import { apiDefinition, project, workflow, workflowDefinition } from '../../test/fixtures'
import { server } from '../../test/server'
import FlowProposalReviewDialog from './FlowProposalReviewDialog'

const changeSetId = '00000000-0000-4000-8000-000000005101'
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
    workflowDefinition.edges[0],
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
      http.get(`/api/v1/projects/${project.id}/flow-specs/change-sets`, () =>
        HttpResponse.json({ items: [summary(reviewStatus)], total: 1, page: 1, page_size: 100 }),
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

    expect(await within(dialog).findByText('Proposal Mode')).toBeInTheDocument()
    expect(within(dialog).getByText('Added Node')).toBeInTheDocument()
    expect(within(dialog).getByText('assert-status')).toBeInTheDocument()
    expect(within(dialog).getByText('Mapping Diff / Human Inspection')).toBeInTheDocument()
    expect(within(dialog).getByText('Assert Diff')).toBeInTheDocument()
    expect(within(dialog).getByText('Evidence / Confidence')).toBeInTheDocument()
    expect(within(dialog).getByText('Unresolved 0')).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: '发布版本' })).not.toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: '运行' })).not.toBeInTheDocument()

    expect(within(dialog).getByRole('button', { name: 'Apply to Workflow Draft' })).toBeDisabled()
    await browser.click(within(dialog).getByRole('button', { name: 'Accept' }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Apply to Workflow Draft' })).not.toBeDisabled(),
    )
    await browser.click(screen.getByRole('button', { name: 'Apply to Workflow Draft' }))
    await waitFor(() => expect(applyCalls).toBe(1))
    expect(appliedWorkflowId).toBe(workflow.id)
  })

  it('shows the captured existing graph and keeps raw mapping on the established path', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/flow-specs/change-sets`, () =>
        HttpResponse.json({ items: [summary('pending')], total: 1, page: 1, page_size: 100 }),
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
    await within(dialog).findByText('Proposal Mode')
    await browser.click(within(dialog).getByText('Existing Graph'))
    expect(await within(dialog).findByText('查询用户')).toBeInTheDocument()
    await browser.click(
      within(dialog).getByRole('button', { name: 'Raw JSON / Cross-instance Mapping' }),
    )
    expect(rawProposal?.proposal.target_workflow_id).toBe(workflow.id)
    expect(rawProposal?.proposal.spec.name).toBe('MCP 用户查询提案')
  })
})

function renderDialog(
  onApplied: (workflowId: string) => void,
  onOpenRawMapping: (proposal: FlowSpecVisualProposal) => void = () => undefined,
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
          resources={{
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
  return changeSet(reviewStatus)
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
