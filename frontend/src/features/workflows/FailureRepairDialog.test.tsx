import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import type { ContextSummary } from '../context-inspector/context-inspector-service'
import type { FailureDiagnosisResponse, FlowSpec, WorkflowExecution } from '../../lib/api'
import { project, workflow, workflowExecutionDetail } from '../../test/fixtures'
import { server } from '../../test/server'
import FailureRepairDialog from './FailureRepairDialog'

const execution: WorkflowExecution = {
  ...workflowExecutionDetail.execution,
  status: 'failed',
  error_code: 'TEST_DATA_MISSING',
  error_message: '缺少测试数据',
}
const context: ContextSummary = {
  id: '00000000-0000-4000-8000-000000005801',
  project_id: project.id,
  name: '订单修复上下文',
  objective: '修复缺失数据',
  status: 'ready',
  current_revision: 2,
  revision_id: '00000000-0000-4000-8000-000000005802',
  revision_fingerprint: 'a'.repeat(64),
  completeness: { required: ['contract'], present: ['contract'], missing: [], complete: true },
  conflict_count: 0,
  evidence_count: 1,
  provider_count: 1,
  proposal_count: 0,
  expires_at: '2099-09-01T00:00:00Z',
  created_at: '2026-08-31T00:00:00Z',
  updated_at: '2026-08-31T00:00:00Z',
}
const spec: FlowSpec = {
  schema_version: 'flowtest-flow-spec-v1',
  fingerprint_version: 'flowtest-flow-spec-fingerprint-v3',
  project_id: project.id,
  name: workflow.name,
  description: '',
  source_evidence: [],
  services: [],
  operations: [],
  nodes: [
    {
      id: 'start',
      kind: 'start',
      name: '开始',
      position: { x: 0, y: 0 },
      config: {},
      depends_on: [],
    },
    {
      id: 'end',
      kind: 'end',
      name: '结束',
      position: { x: 200, y: 0 },
      config: {},
      depends_on: ['start'],
    },
  ],
  edges: [{ id: 'start-end', source: 'start', target: 'end', condition: null, mappings: [] }],
  variables: {},
  settings: { fail_fast: true, concurrency: 20, default_timeout_seconds: 30 },
  bindings: [],
  parameters: [],
  assertions: [],
  cleanup: [],
  security_policy: { secret_refs_only: true, max_requests: 20, allow_private_network: false },
  confidence: { overall: 1, unresolved: [] },
}

describe('FailureRepairDialog', () => {
  it('creates a scoped repair proposal from a failed execution', async () => {
    let submitted: Record<string, unknown> | undefined
    const diagnosis = failureDiagnosis()
    server.use(
      http.get(
        `/api/v1/projects/${project.id}/workflow-executions/${execution.id}/failure-diagnosis`,
        () => HttpResponse.json(diagnosis),
      ),
      http.get(`/api/v1/projects/${project.id}/flow-specs/workflows/${workflow.id}/export`, () =>
        HttpResponse.json({
          workflow_id: workflow.id,
          version: null,
          draft_revision: 1,
          fingerprint: 'b'.repeat(64),
          spec,
          validation: { valid: true, issues: [], warnings: [], requires_review: false },
          compatibility: {
            compatible: true,
            source_schema_version: spec.schema_version,
            target_schema_version: spec.schema_version,
            blockers: [],
            warnings: [],
            requires_review: false,
          },
        }),
      ),
      http.get(`/api/v1/projects/${project.id}/contexts`, () =>
        HttpResponse.json({ items: [context], total: 1, page: 1, page_size: 100 }),
      ),
      http.post(
        `/api/v1/projects/${project.id}/workflow-executions/${execution.id}/repair-proposals`,
        async ({ request }) => {
          submitted = (await request.json()) as Record<string, unknown>
          return HttpResponse.json(
            {
              schema_version: 'flowtest-repair-proposal-v1',
              execution_id: execution.id,
              diagnosis: diagnosis.diagnosis,
              proposal: {
                id: '00000000-0000-4000-8000-000000005803',
                project_id: project.id,
                title: workflow.name,
                status: 'draft',
                source_type: 'flow_spec',
                source_ref: `repair://workflow-executions/${execution.id}`,
                source_fingerprint: 'c'.repeat(64),
                target_workflow_id: workflow.id,
                target_revision: 1,
                target_snapshot_sha256: 'd'.repeat(64),
                review_status: 'pending',
                reviewed_by_id: null,
                reviewed_at: null,
                applied_at: null,
                created_by_id: '00000000-0000-4000-8000-000000000001',
                created_at: '2026-08-31T00:00:00Z',
                updated_at: '2026-08-31T00:00:00Z',
                spec: { ...spec, variables: { customer_id: 'fixture-customer' } },
                validation: { valid: true, issues: [], warnings: [], requires_review: false },
                compatibility: {
                  compatible: true,
                  source_schema_version: spec.schema_version,
                  target_schema_version: spec.schema_version,
                  blockers: [],
                  warnings: [],
                  requires_review: false,
                },
                diff: [],
              },
            },
            { status: 201 },
          )
        },
      ),
    )
    let proposalId = ''
    renderDialog((value) => {
      proposalId = value
    })
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('BAD_TEST_DATA')).toBeInTheDocument()
    expect(await within(dialog).findByText('Test Data')).toBeInTheDocument()
    expect(await within(dialog).findByText(/订单修复上下文/)).toBeInTheDocument()

    const changed = { ...spec, variables: { customer_id: 'fixture-customer' } }
    fireEvent.change(within(dialog).getByLabelText('Proposed FlowSpec Patch'), {
      target: { value: JSON.stringify(changed, null, 2) },
    })
    await userEvent.click(within(dialog).getByRole('button', { name: '创建 Repair Proposal' }))

    await waitFor(() => expect(proposalId).toBe('00000000-0000-4000-8000-000000005803'))
    expect(submitted?.kind).toBe('data')
    expect(submitted?.context_revision_id).toBe(context.revision_id)
    expect((submitted?.proposed_spec as FlowSpec).variables).toEqual({
      customer_id: 'fixture-customer',
    })
  })

  it('shows Product Defect Guard without offering a test repair proposal', async () => {
    const guarded = failureDiagnosis()
    guarded.diagnosis.triage.primary_classification = 'PRODUCT_DEFECT'
    guarded.diagnosis.triage.recommended_action = '修复产品并补充回归'
    guarded.diagnosis.repair_policy = {
      proposal_allowed: false,
      allowed_kinds: [],
      requires_human_review: true,
      product_defect_guard: true,
      reason_codes: ['PRODUCT_DEFECT_TEST_MUTATION_FORBIDDEN'],
    }
    server.use(
      http.get(
        `/api/v1/projects/${project.id}/workflow-executions/${execution.id}/failure-diagnosis`,
        () => HttpResponse.json(guarded),
      ),
      http.get(`/api/v1/projects/${project.id}/flow-specs/workflows/${workflow.id}/export`, () =>
        HttpResponse.json({
          workflow_id: workflow.id,
          version: null,
          draft_revision: 1,
          fingerprint: 'b'.repeat(64),
          spec,
          validation: { valid: true, issues: [], warnings: [], requires_review: false },
          compatibility: {
            compatible: true,
            source_schema_version: spec.schema_version,
            target_schema_version: spec.schema_version,
            blockers: [],
            warnings: [],
            requires_review: false,
          },
        }),
      ),
      http.get(`/api/v1/projects/${project.id}/contexts`, () =>
        HttpResponse.json({ items: [context], total: 1, page: 1, page_size: 100 }),
      ),
    )

    renderDialog(() => undefined)
    const dialog = await screen.findByRole('dialog')

    expect(
      await within(dialog).findByText('Product Defect Guard 已阻止修改测试'),
    ).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: '创建 Repair Proposal' })).toBeNull()
  })
})

function renderDialog(onCreated: (proposalId: string) => void) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <FailureRepairDialog
          open
          projectId={project.id}
          execution={execution}
          onClose={() => undefined}
          onCreated={onCreated}
        />
      </QueryClientProvider>
    </AntdApp>,
  )
}

function failureDiagnosis(): FailureDiagnosisResponse {
  return {
    execution_id: execution.id,
    workflow_id: workflow.id,
    diagnosis: {
      schema_version: 'flowtest-failure-diagnosis-v1',
      triage: {
        algorithm_version: 's47-failure-triage-v2',
        primary_classification: 'BAD_TEST_DATA',
        secondary_candidates: [],
        confidence: 0.85,
        reason_codes: ['STRUCTURED_TEST_DATA_CODE'],
        affected_service: null,
        endpoint_variant: null,
        affected_operation: null,
        evidence_refs: [`flowtest://runs/${execution.id}/nodes/start`],
        retry_signal: false,
        recommended_action: '修复数据集前置条件或数据映射',
        recommended_regression: ['重跑相同数据分片'],
      },
      repair_policy: {
        proposal_allowed: true,
        allowed_kinds: ['data', 'binding'],
        requires_human_review: true,
        product_defect_guard: false,
        reason_codes: ['TYPED_REPAIR_PROPOSAL_REQUIRES_REVIEW'],
      },
    },
  }
}
