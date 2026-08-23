import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import type {
  OperationContract,
  TestDesignDocument,
  TestEngineeringProposal,
} from '../features/test-engineering/test-engineering-service'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { apiDefinition, environment, project } from '../test/fixtures'
import { server } from '../test/server'
import TestEngineeringPage from './TestEngineeringPage'

const operationContract: OperationContract = {
  operation: 'orders.create',
  method: 'POST',
  path: '/orders',
  service: 'orders',
  auth: { required: true, kind: 'bearer', location: 'header', name: 'Authorization' },
  parameters: [
    { name: 'X-Tenant-Id', location: 'header', required: true, schema: { type: 'string' } },
  ],
  completeness: 'complete',
  warnings: [],
}

const design: TestDesignDocument = {
  schema_version: '1.0',
  intent: {
    key: 'orders.create',
    objective: '验证 POST /orders 的契约边界',
    acceptance_criteria: ['2xx success'],
    evidence_refs: ['evidence-contract'],
    confidence: 1,
    deterministic: true,
  },
  scenarios: [
    {
      id: 'scenario_happy_path',
      kind: 'happy_path',
      title: '有效订单',
      request_body: { quantity: 100 },
      request: {
        path_parameters: {},
        query_parameters: {},
        headers: {},
        cookies: {},
        body: { quantity: 100 },
        auth_disabled: false,
      },
      mutations: [],
      expected_category: 'success',
      negative: false,
      evidence_refs: ['evidence-contract'],
      confidence: 1,
      deterministic: true,
      requires_review: false,
      tags: ['contract'],
    },
    {
      id: 'scenario_auth_missing',
      kind: 'auth_missing',
      title: '缺失认证',
      request_body: { quantity: 100 },
      request: {
        path_parameters: {},
        query_parameters: {},
        headers: {},
        cookies: {},
        body: { quantity: 100 },
        auth_disabled: true,
      },
      mutations: [{ location: 'auth', path: 'auth', operation: 'omit', value: null }],
      expected_category: 'unauthorized',
      negative: true,
      evidence_refs: ['evidence-contract'],
      confidence: 1,
      deterministic: true,
      requires_review: false,
      tags: ['auth'],
    },
  ],
  oracles: [
    {
      id: 'oracle_success_status',
      kind: 'status',
      expression: '$.status',
      operator: 'equals',
      expected: 201,
      confidence: 1,
      evidence_refs: ['evidence-contract'],
      source_type: 'contract',
      deterministic: true,
      requires_review: false,
      applies_to: ['scenario_happy_path'],
    },
  ],
  coverage: {
    entries: [
      {
        target_ref: 'orders.create',
        dimension: 'endpoint',
        requirement: 'happy path',
        covered: true,
        evidence_refs: ['evidence-contract'],
        reason: '由 happy path 覆盖',
        recommended_scenario_kind: 'happy_path',
        priority: 'high',
      },
    ],
  },
  evidence_refs: [
    {
      id: 'evidence-contract',
      source_type: 'contract',
      source_ref: 'contract://orders.create',
      revision: 'sha256:contract',
      semantic_role: 'normative',
    },
  ],
  warnings: [],
  confidence: 1,
  review_requirements: [],
}

describe('TestEngineeringPage', () => {
  it('reviews generated scenarios and materializes an accepted draft', async () => {
    const serviceId = '00000000-0000-4000-8000-000000007000'
    const targetedApi = { ...apiDefinition, service_id: serviceId }
    let proposalPayload: Record<string, unknown> | null = null
    let proposal: TestEngineeringProposal = {
      change_set_id: '00000000-0000-4000-8000-000000007001',
      status: 'draft',
      review_status: 'pending',
      fingerprint: 'fingerprint-s47',
      design,
      scenario_ids: ['scenario_happy_path'],
      applied: false,
      contract_completeness: 'complete',
      contract_fingerprint: 'a'.repeat(64),
      contract: operationContract,
    }
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({ items: [targetedApi], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/environments`, () =>
        HttpResponse.json([environment]),
      ),
      http.get(
        `/api/v1/projects/${project.id}/environments/${environment.id}/service-endpoints`,
        () =>
          HttpResponse.json([
            {
              id: '00000000-0000-4000-8000-000000007005',
              service_id: serviceId,
              environment_id: environment.id,
              project_id: project.id,
              variant: 'blue',
              enabled: true,
            },
          ]),
      ),
      http.post(`/api/v1/projects/${project.id}/test-engineering/generate`, () =>
        HttpResponse.json({
          fingerprint: 'fingerprint-s47',
          design,
          persisted: false,
          contract_completeness: 'complete',
          contract_fingerprint: 'a'.repeat(64),
          contract: operationContract,
        }),
      ),
      http.post(
        `/api/v1/projects/${project.id}/test-engineering/proposals`,
        async ({ request }) => {
          proposalPayload = (await request.json()) as Record<string, unknown>
          return HttpResponse.json(proposal, { status: 201 })
        },
      ),
      http.post(
        `/api/v1/projects/${project.id}/test-engineering/proposals/${proposal.change_set_id}/review`,
        () => {
          proposal = { ...proposal, status: 'accepted', review_status: 'accepted' }
          return HttpResponse.json(proposal)
        },
      ),
      http.post(
        `/api/v1/projects/${project.id}/test-engineering/proposals/${proposal.change_set_id}/apply`,
        () =>
          HttpResponse.json({
            change_set_id: proposal.change_set_id,
            test_design_id: '00000000-0000-4000-8000-000000007002',
            workflow_ids: ['00000000-0000-4000-8000-000000007003'],
            test_case_ids: ['00000000-0000-4000-8000-000000007004'],
          }),
      ),
    )
    renderPage()
    const browser = userEvent.setup()

    await browser.click(await screen.findByRole('combobox', { name: 'API 契约' }))
    await browser.click((await screen.findAllByText(`${apiDefinition.name} · v1`)).at(-1)!)
    await browser.click(screen.getByRole('combobox', { name: '物化环境' }))
    await browser.click((await screen.findAllByText(environment.name)).at(-1)!)
    await browser.click(await screen.findByRole('combobox', { name: 'Endpoint Variant' }))
    await browser.click((await screen.findAllByText('blue')).at(-1)!)
    await browser.type(screen.getByPlaceholderText('订单创建契约测试'), '订单 Test Design')
    await browser.click(screen.getByRole('button', { name: '只读生成预览' }))

    expect(await screen.findByText('验证 POST /orders 的契约边界')).toBeVisible()
    expect(screen.getByText('Operation Identity').closest('tr')).toHaveTextContent(
      'orders · POST /orders · orders.create',
    )
    expect(screen.getByText('disabled')).toBeVisible()
    expect(screen.getByText('auth:disabled')).toBeVisible()
    expect(screen.getByText('normative')).toBeVisible()
    expect(screen.getAllByText('可物化')).toHaveLength(2)
    const rowCheckboxes = screen.getAllByRole('checkbox')
    await browser.click(rowCheckboxes[1])
    await browser.click(screen.getByRole('button', { name: '创建待审核 Draft' }))
    await waitFor(() =>
      expect(proposalPayload).toMatchObject({
        endpoint_variant: 'blue',
        scenario_ids: ['scenario_happy_path'],
      }),
    )

    await browser.click(await screen.findByRole('button', { name: '接受 Draft' }))
    expect(await screen.findByRole('button', { name: '物化为 Workflow / TestCase' })).toBeVisible()
    await browser.click(screen.getByRole('button', { name: '物化为 Workflow / TestCase' }))
    expect(await screen.findByText('已进入执行体系')).toBeVisible()
  })

  it('renders review warnings and gaps and keeps rejected drafts non-applicable', async () => {
    const previewDesign: TestDesignDocument = {
      ...design,
      scenarios: [
        ...design.scenarios,
        {
          ...design.scenarios[0],
          id: 'scenario_path_omitted',
          title: '缺失路径参数',
          mutations: [{ location: 'path', path: 'tenant_id', operation: 'omit', value: null }],
          expected_category: 'client_error',
          negative: true,
          tags: ['path'],
        },
      ],
      warnings: ['Oracle 需要人工复核'],
      review_requirements: ['state_evidence_unavailable', 'evidence_conflict'],
      oracles: [{ ...design.oracles[0], requires_review: true }],
      coverage: { entries: [] },
    }
    const proposalDesign: TestDesignDocument = {
      ...previewDesign,
      coverage: {
        entries: [
          {
            ...design.coverage.entries[0],
            covered: false,
            reason: '场景预算未覆盖',
            recommended_scenario_kind: 'boundary',
          },
        ],
      },
    }
    let proposal: TestEngineeringProposal = {
      change_set_id: '00000000-0000-4000-8000-000000007011',
      status: 'draft',
      review_status: 'pending',
      fingerprint: 'fingerprint-review',
      design: proposalDesign,
      scenario_ids: ['scenario_happy_path'],
      applied: false,
      contract_completeness: 'partial',
      contract_fingerprint: 'b'.repeat(64),
      contract: {
        ...operationContract,
        completeness: 'redacted_partial',
        warnings: ['sensitive enum values redacted'],
      },
    }
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({ items: [apiDefinition], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/environments`, () =>
        HttpResponse.json([environment]),
      ),
      http.post(`/api/v1/projects/${project.id}/test-engineering/generate`, () =>
        HttpResponse.json({
          fingerprint: 'fingerprint-review',
          design: previewDesign,
          persisted: false,
          contract_completeness: 'redacted_partial',
          contract_fingerprint: 'b'.repeat(64),
          contract: {
            ...operationContract,
            completeness: 'redacted_partial',
            warnings: ['sensitive enum values redacted'],
          },
        }),
      ),
      http.post(`/api/v1/projects/${project.id}/test-engineering/proposals`, () =>
        HttpResponse.json(proposal, { status: 201 }),
      ),
      http.post(
        `/api/v1/projects/${project.id}/test-engineering/proposals/${proposal.change_set_id}/review`,
        () => {
          proposal = { ...proposal, status: 'rejected', review_status: 'rejected' }
          return HttpResponse.json(proposal)
        },
      ),
    )
    renderPage()
    const browser = userEvent.setup()

    await browser.click(screen.getByRole('button', { name: '只读生成预览' }))
    expect(screen.getByText('请选择 API 契约并生成预览。')).toBeVisible()
    await browser.click(await screen.findByRole('combobox', { name: 'API 契约' }))
    await browser.click((await screen.findAllByText(`${apiDefinition.name} · v1`)).at(-1)!)
    await browser.click(screen.getByRole('combobox', { name: '物化环境' }))
    await browser.click((await screen.findAllByText(environment.name)).at(-1)!)
    await browser.type(screen.getByPlaceholderText('订单创建契约测试'), '待复核 Test Design')
    await browser.click(screen.getByRole('button', { name: '只读生成预览' }))

    expect(await screen.findByText('Oracle 需要人工复核')).toBeVisible()
    expect(screen.getByText('Canonical Contract 已安全净化')).toBeVisible()
    expect(screen.getByText('Evidence Conflict')).toBeVisible()
    expect(screen.getByText('缺少显式状态证据')).toBeVisible()
    expect(screen.getByText('需要')).toBeVisible()
    expect(screen.getByText('仅设计')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: '创建待审核 Draft' }))
    expect(await screen.findByText('Gap')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: '拒绝 Draft' }))

    expect(await screen.findByText('rejected')).toBeVisible()
    expect(
      screen.queryByRole('button', { name: '物化为 Workflow / TestCase' }),
    ).not.toBeInTheDocument()
  })
})

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <ProjectTestProvider section="test-engineering">
          <TestEngineeringPage />
        </ProjectTestProvider>
      </QueryClientProvider>
    </AntdApp>,
  )
}
