import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { apiDefinition, project, workflow } from '../../test/fixtures'
import { server } from '../../test/server'
import type { FlowSpec, FlowSpecChangeSetDetail, RequestService } from '../../lib/api'
import FlowSpecReviewDialog from './FlowSpecReviewDialog'

const targetService: RequestService = {
  id: '00000000-0000-4000-8000-000000008001',
  project_id: project.id,
  service_key: 'orders',
  name: '订单服务',
  description: '',
  owner_team: null,
  service_type: 'https',
  enabled: true,
  created_by_id: '00000000-0000-4000-8000-000000008002',
  created_at: '2026-08-23T00:00:00Z',
  updated_at: '2026-08-23T00:00:00Z',
}

const spec: FlowSpec = {
  schema_version: 'flowtest-flow-spec-v1',
  fingerprint_version: 'flowtest-flow-spec-fingerprint-v2',
  project_id: '00000000-0000-4000-8000-000000008099',
  name: '订单流程',
  description: '',
  source_evidence: [],
  services: [{ ref: 'service.orders', name: 'Orders', service_type: 'https' }],
  operations: [
    {
      ref: 'orders.create',
      service_ref: 'service.orders',
      name: 'Create Order',
      method: 'POST',
      path: '/orders',
    },
  ],
  nodes: [
    {
      id: 'request',
      kind: 'api',
      name: 'Create Order',
      position: { x: 0, y: 0 },
      config: {},
      depends_on: [],
      operation_ref: 'orders.create',
      target: { service_ref: 'service.orders', endpoint_variant: 'canary' },
    },
  ],
  edges: [],
  variables: {},
  settings: { fail_fast: true, concurrency: 1, default_timeout_seconds: 30 },
  bindings: [],
  parameters: [],
  assertions: [],
  cleanup: [],
  security_policy: { secret_refs_only: true, max_requests: 20, allow_private_network: false },
  confidence: { overall: 1, unresolved: [] },
}

describe('FlowSpecReviewDialog', () => {
  it('requires portable mappings before draft review and apply', async () => {
    let importPayload: Record<string, unknown> | null = null
    let reviewCalls = 0
    let applyCalls = 0
    let proposal = changeSet('pending')
    server.use(
      http.get(`/api/v1/projects/${project.id}/services`, () => HttpResponse.json([targetService])),
      http.post(`/api/v1/projects/${project.id}/flow-specs/imports`, async ({ request }) => {
        importPayload = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(proposal, { status: 201 })
      }),
      http.post(
        `/api/v1/projects/${project.id}/flow-specs/change-sets/${proposal.id}/review`,
        () => {
          reviewCalls += 1
          proposal = changeSet('accepted')
          return HttpResponse.json(proposal)
        },
      ),
      http.post(
        `/api/v1/projects/${project.id}/flow-specs/change-sets/${proposal.id}/apply`,
        () => {
          applyCalls += 1
          return HttpResponse.json({
            change_set_id: proposal.id,
            workflow_id: workflow.id,
            draft_revision: 2,
            fingerprint: 'fingerprint-s47',
            applied_at: '2026-08-23T00:00:00Z',
          })
        },
      ),
    )
    renderDialog()
    const browser = userEvent.setup()
    fireEvent.change(screen.getByRole('textbox', { name: 'FlowSpec JSON' }), {
      target: { value: JSON.stringify(spec) },
    })

    expect(screen.getByRole('button', { name: '创建 ChangeSet Draft' })).toBeDisabled()
    await browser.click(screen.getByRole('combobox', { name: 'Service Mapping service.orders' }))
    await browser.click((await screen.findAllByText('订单服务 · orders')).at(-1)!)
    await browser.click(screen.getByRole('combobox', { name: 'Operation Mapping orders.create' }))
    await browser.click((await screen.findAllByText(`${apiDefinition.name} · v1`)).at(-1)!)
    await browser.click(screen.getByRole('button', { name: '创建 ChangeSet Draft' }))

    await waitFor(() =>
      expect(importPayload).toMatchObject({
        service_mappings: { 'service.orders': targetService.id },
        operation_mappings: { 'orders.create': apiDefinition.id },
      }),
    )
    await browser.click(await screen.findByRole('button', { name: '接受 Mapping 与 Diff' }))
    await waitFor(() => expect(reviewCalls).toBe(1))
    expect((await screen.findAllByText('accepted')).length).toBeGreaterThan(0)
    const applyButton = await screen.findByRole('button', { name: /应用到 Workflow 草稿/ })
    await waitFor(() => expect(applyButton).not.toBeDisabled())
    await browser.click(applyButton)
    await waitFor(() => expect(applyCalls).toBe(1))
  })

  it('shows parse and compatibility failures and creates a resource-free draft', async () => {
    const portableFreeSpec: FlowSpec = {
      ...spec,
      name: '无可移植引用流程',
      services: [],
      operations: [],
      nodes: spec.nodes.map((node) => ({
        id: node.id,
        kind: node.kind,
        name: node.name,
        position: node.position,
        config: node.config,
        depends_on: node.depends_on,
      })),
    }
    const proposal = changeSet('pending', portableFreeSpec)
    let importCalls = 0
    server.use(
      http.get(`/api/v1/projects/${project.id}/services`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${project.id}/flow-specs/workflows/${workflow.id}/export`, () =>
        HttpResponse.json({
          workflow_id: workflow.id,
          version: null,
          draft_revision: 1,
          fingerprint: 'fingerprint-export',
          spec: portableFreeSpec,
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
      http.post(`/api/v1/projects/${project.id}/flow-specs/validate`, () =>
        HttpResponse.json({
          fingerprint: 'fingerprint-invalid',
          spec: portableFreeSpec,
          validation: {
            valid: false,
            issues: [{ code: 'NODE_INVALID', path: '$.nodes[0]', message: '节点无效' }],
            warnings: [],
            requires_review: true,
          },
          compatibility: {
            compatible: false,
            source_schema_version: spec.schema_version,
            target_schema_version: spec.schema_version,
            blockers: [{ code: 'TARGET_BLOCKED', path: '$.project_id', message: '目标项目不兼容' }],
            warnings: [],
            requires_review: true,
          },
        }),
      ),
      http.post(`/api/v1/projects/${project.id}/flow-specs/imports`, () => {
        importCalls += 1
        return HttpResponse.json(proposal, { status: 201 })
      }),
    )
    renderDialog()
    const browser = userEvent.setup()
    const dialog = screen.getByRole('dialog')
    const input = within(dialog).getByRole('textbox', { name: 'FlowSpec JSON' })

    fireEvent.change(input, { target: { value: '1' } })
    expect(await within(dialog).findByText('FlowSpec JSON 无法解析')).toBeInTheDocument()
    fireEvent.change(input, { target: { value: '{' } })
    expect(await within(dialog).findByText('FlowSpec JSON 无法解析')).toBeInTheDocument()
    await browser.click(within(dialog).getByRole('button', { name: '导出当前草稿' }))
    await waitFor(() =>
      expect(within(dialog).getByRole('button', { name: /导出当前草稿/ })).not.toHaveClass(
        'ant-btn-loading',
      ),
    )

    expect(await within(dialog).findByText('该 FlowSpec 不含可移植资源引用。')).toBeInTheDocument()
    expect(within(dialog).getByText('valid')).toBeInTheDocument()
    expect(within(dialog).getByText('compatible')).toBeInTheDocument()
    await browser.click(within(dialog).getByRole('button', { name: /校验与兼容性检查/ }))
    expect(await within(dialog).findByText('NODE_INVALID')).toBeInTheDocument()
    await waitFor(() =>
      expect(within(dialog).getByRole('button', { name: /校验与兼容性检查/ })).not.toHaveClass(
        'ant-btn-loading',
      ),
    )
    expect(within(dialog).getByText('TARGET_BLOCKED')).toBeInTheDocument()
    expect(within(dialog).getByText('invalid')).toBeInTheDocument()
    expect(within(dialog).getByText('blocked')).toBeInTheDocument()

    await browser.click(within(dialog).getByRole('button', { name: /创建 ChangeSet Draft/ }))
    await waitFor(() => expect(importCalls).toBe(1))
  })
})

function changeSet(
  reviewStatus: 'pending' | 'accepted' | 'rejected',
  flowSpec: FlowSpec = spec,
): FlowSpecChangeSetDetail {
  return {
    id: '00000000-0000-4000-8000-000000008003',
    project_id: project.id,
    title: flowSpec.name,
    status: reviewStatus === 'pending' ? 'draft' : reviewStatus,
    source_type: 'flow_spec',
    source_ref: 'ui://flow-spec-review',
    source_fingerprint: 'fingerprint-s47',
    target_workflow_id: workflow.id,
    target_revision: 1,
    target_snapshot_sha256: 'snapshot-s47',
    review_status: reviewStatus,
    reviewed_by_id: null,
    reviewed_at: null,
    applied_at: null,
    created_by_id: targetService.created_by_id,
    created_at: '2026-08-23T00:00:00Z',
    updated_at: '2026-08-23T00:00:00Z',
    spec: flowSpec,
    validation: { valid: true, issues: [], warnings: [], requires_review: true },
    compatibility: {
      compatible: true,
      source_schema_version: spec.schema_version,
      target_schema_version: spec.schema_version,
      blockers: [],
      warnings: [],
      requires_review: true,
    },
    diff: [{ path: '$.nodes', before: [], after: spec.nodes }],
  }
}

function renderDialog() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <FlowSpecReviewDialog
          open
          projectId={project.id}
          workflowId={workflow.id}
          apis={[apiDefinition]}
          onClose={() => undefined}
        />
      </QueryClientProvider>
    </AntdApp>,
  )
}
