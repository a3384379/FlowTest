import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { useLocation } from 'react-router-dom'

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
    {
      id: 'oracle_unauthorized_status',
      kind: 'status',
      expression: '$.status',
      operator: 'equals',
      expected: 401,
      confidence: 1,
      evidence_refs: ['evidence-contract'],
      source_type: 'contract',
      deterministic: true,
      requires_review: false,
      applies_to: ['scenario_auth_missing'],
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
  it('allows read-only generation but keeps proposal review and materialization disabled for viewers', async () => {
    let writes = 0
    const proposal: TestEngineeringProposal = {
      change_set_id: 'readonly-proposal',
      status: 'draft',
      review_status: 'pending',
      fingerprint: 'viewer-fingerprint',
      design,
      scenario_ids: ['scenario_happy_path'],
      applied: false,
      contract_completeness: 'complete',
      contract_fingerprint: 'd'.repeat(64),
      contract: operationContract,
    }
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/permissions`, () =>
        HttpResponse.json({ effective_role: 'viewer', capabilities: ['read'], matrix: {} }),
      ),
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({ items: [apiDefinition], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/environments`, () =>
        HttpResponse.json([environment]),
      ),
      http.get(
        `/api/v1/projects/${project.id}/test-engineering/proposals/${proposal.change_set_id}`,
        () => HttpResponse.json(proposal),
      ),
      http.post(`/api/v1/projects/${project.id}/test-engineering/proposals/*`, () => {
        writes += 1
        return HttpResponse.json(proposal)
      }),
    )
    renderPage(`/projects/${project.id}/test-engineering?proposal=${proposal.change_set_id}`)
    expect(await screen.findByText(design.intent.objective)).toBeVisible()
    expect(screen.getByText('必须认证 · Bearer 令牌 · 请求头（Authorization）')).toBeVisible()
    expect(actionButton('只读生成预览')).not.toBeDisabled()
    expect(actionButton('创建待审核草稿')).toBeDisabled()
    for (const name of ['接受设计草稿', '拒绝设计草稿']) {
      const button = actionButton(name)
      expect(button).toBeDisabled()
      await userEvent.click(button)
    }
    expect(writes).toBe(0)
  })

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
      http.get(
        `/api/v1/projects/${project.id}/test-engineering/proposals/${proposal.change_set_id}`,
        () => HttpResponse.json(proposal),
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
    await browser.click(
      await screen.findByText(apiDefinition.name, { selector: '.api-resource-option-name' }),
    )
    await browser.click(screen.getByRole('combobox', { name: '目标环境' }))
    await browser.click((await screen.findAllByText(environment.name)).at(-1)!)
    await browser.click(await screen.findByRole('combobox', { name: '服务端点' }))
    await browser.click((await screen.findAllByText('blue')).at(-1)!)
    await browser.type(screen.getByPlaceholderText('订单创建契约测试'), '订单 Test Design')
    await browser.click(actionButton('只读生成预览'))

    expect(await screen.findByText('验证 POST /orders 的契约边界')).toBeVisible()
    expect(screen.getByText('操作标识').closest('tr')).toHaveTextContent(
      'orders · POST /orders · orders.create',
    )
    await browser.click(screen.getByLabelText('查看场景：缺失认证'))
    expect(screen.getByText('禁用认证')).toBeVisible()
    const sources = screen.getByText('完整设计来源（1条）').closest<HTMLElement>('.ant-card')!
    expect(within(sources).getByText('规范性证据')).toBeVisible()
    expect(screen.getAllByText('可生成草稿')).toHaveLength(2)
    const rowCheckboxes = screen.getAllByRole('checkbox')
    await browser.click(rowCheckboxes[1])
    await browser.click(actionButton('创建待审核草稿'))
    await waitFor(() =>
      expect(proposalPayload).toMatchObject({
        endpoint_variant: 'blue',
        scenario_ids: ['scenario_happy_path'],
      }),
    )

    await browser.click(await findButton('接受设计草稿'))
    expect(await findButton('生成工作流与用例草稿')).toBeVisible()
    await browser.click(actionButton('生成工作流与用例草稿'))
    expect(await screen.findByText('已生成资产草稿')).toBeVisible()
    expect(actionButton('打开工作流 00000000-0000-4000-8000-000000007003')).toBeVisible()
    expect(actionButton('打开用例 00000000-0000-4000-8000-000000007004')).toBeVisible()
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
      http.get(
        `/api/v1/projects/${project.id}/test-engineering/proposals/${proposal.change_set_id}`,
        () => HttpResponse.json(proposal),
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

    await browser.click(actionButton('只读生成预览'))
    expect(screen.getByText('请选择 API 契约并生成预览。')).toBeVisible()
    await browser.click(await screen.findByRole('combobox', { name: 'API 契约' }))
    await browser.click(
      await screen.findByText(apiDefinition.name, { selector: '.api-resource-option-name' }),
    )
    await browser.click(screen.getByRole('combobox', { name: '目标环境' }))
    await browser.click((await screen.findAllByText(environment.name)).at(-1)!)
    await browser.type(screen.getByPlaceholderText('订单创建契约测试'), '待复核 Test Design')
    await browser.click(actionButton('只读生成预览'))

    expect(await screen.findByText('Oracle 需要人工复核')).toBeVisible()
    expect(screen.getByText('来源契约已按策略处理')).toBeVisible()
    expect(screen.getByText('来源证据存在冲突')).toBeVisible()
    expect(screen.getByText('缺少显式状态证据')).toBeVisible()
    expect(screen.getByText('仅保留为设计，尚不能生成可执行资产')).toBeVisible()
    expect(screen.getAllByText('仅设计')).toHaveLength(3)
    await browser.click(actionButton('创建待审核草稿'))
    const coverage = screen.getByText('完整设计覆盖与缺口').closest<HTMLElement>('.ant-card')!
    expect(await within(coverage).findByText('待补齐')).toBeVisible()
    await browser.click(actionButton('拒绝设计草稿'))

    expect(await screen.findByText('已拒绝')).toBeVisible()
    expect(screen.queryByText('生成工作流与用例草稿', { exact: true })).not.toBeInTheDocument()
  })

  it.each([
    { location: 'auth', path: 'auth', target: 'orders.create.auth' },
    { location: 'body', path: 'body.quantity', target: 'orders.create.body.quantity' },
    { location: 'body', path: 'quantity', target: 'orders.create.body.quantity' },
  ])(
    'matches direct scenario coverage for $location / $path without duplicating its location',
    async ({ location, path, target }) => {
      const entry = {
        ...design.coverage!.entries[0],
        target_ref: target,
        dimension: 'authorization',
        requirement: 'auth missing',
      }
      const selected = {
        ...design.scenarios[1],
        mutations: [{ location, path, operation: 'omit', value: null }],
      }
      const saved = installLinkedProposal({
        design: {
          ...design,
          scenarios: [design.scenarios[0], selected],
          coverage: { entries: [entry, { ...entry, target_ref: `${target}.unrelated` }] },
        },
      })
      renderPage(`/projects/${project.id}/test-engineering?proposal=${saved.change_set_id}`)
      const browser = userEvent.setup()
      await browser.click(await screen.findByLabelText('查看场景：缺失认证'))
      const direct = within(
        screen.getByText('本场景的直接覆盖项').closest('.ant-card') as HTMLElement,
      )
      expect(await direct.findByText(target, { exact: true })).toBeVisible()
      expect(direct.getByText('认证与权限', { exact: true })).toBeVisible()
      expect(direct.queryByText(`${target}.unrelated`, { exact: true })).not.toBeInTheDocument()
    },
  )

  it('restores generated asset references and protects unsaved targets before opening the exact asset', async () => {
    let writes = 0
    const workflowId = '00000000-0000-4000-8000-000000007901'
    const caseId = '00000000-0000-4000-8000-000000007902'
    const saved = installLinkedProposal({
      applied: true,
      status: 'accepted',
      review_status: 'accepted',
      materialization: {
        change_set_id: '00000000-0000-4000-8000-000000007999',
        test_design_id: '00000000-0000-4000-8000-000000007900',
        workflow_ids: [workflowId],
        test_case_ids: [caseId],
        references_complete: true,
        assets: [
          { scenario_id: 'scenario_happy_path', workflow_id: workflowId, test_case_id: caseId },
        ],
      },
    })
    server.use(
      http.post(`/api/v1/projects/${project.id}/test-engineering/*`, () => {
        writes++
        return new HttpResponse(null, { status: 500 })
      }),
    )
    renderPage(`/projects/${project.id}/test-engineering?proposal=${saved.change_set_id}`)
    await screen.findByText('本次生成的资产')
    const link = screen.getByLabelText(`打开工作流${workflowId}`)
    expect(link).toHaveRole('button')
    expect(screen.getByLabelText(`打开用例${caseId}`)).toHaveRole('button')
    const browser = userEvent.setup()
    await browser.type(screen.getByPlaceholderText('订单创建契约测试'), '新的未保存目标')
    await browser.click(link)
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('还有未保存的设计目标')
    await browser.click(within(dialog).getByText('留在当前页面'))
    expect(screen.getByPlaceholderText('订单创建契约测试')).toHaveValue('新的未保存目标')
    expect(screen.getByTestId('design-route')).toHaveTextContent(`proposal=${saved.change_set_id}`)
    await browser.click(link)
    const confirm = await screen.findByRole('dialog')
    await browser.click(within(confirm).getByText('放弃并打开'))
    await waitFor(() =>
      expect(screen.getByTestId('design-route')).toHaveTextContent(
        `/workflows?focus=${workflowId}`,
      ),
    )
    expect(writes).toBe(0)
  })

  it('inspects the fixed source version and retains its identity and field path across read failure and retry', async () => {
    const reference = {
      ...design.evidence_refs[0],
      source_ref: `api-definition://${apiDefinition.id}/version/1`,
      revision: 'old-v1',
    }
    const saved = installLinkedProposal({
      design: { ...design, evidence_refs: [reference] },
      evidence_details: [
        {
          ...reference,
          path: 'body.quantity',
          confidence: 1,
          deterministic: true,
        },
      ],
    })
    const versions: string[] = []
    let writes = 0
    server.use(
      http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}`, ({ request }) => {
        versions.push(new URL(request.url).searchParams.get('version') ?? 'latest')
        if (versions.length === 1)
          return HttpResponse.json(
            {
              error: {
                code: 'UNAVAILABLE',
                message: '合成来源暂不可读',
                trace_id: 'source-read-trace',
              },
            },
            { status: 503 },
          )
        return HttpResponse.json({
          definition: { ...apiDefinition, current_version: 99 },
          version: { version: 1, method: 'POST', path: '/frozen-orders' },
        })
      }),
      http.post(`/api/v1/projects/${project.id}/test-engineering/*`, () => {
        writes++
        return new HttpResponse(null, { status: 500 })
      }),
    )
    renderPage(`/projects/${project.id}/test-engineering?proposal=${saved.change_set_id}`)
    const allSources = (await screen.findByText('完整设计来源（1条）')).closest<HTMLElement>(
      '.ant-card',
    )!
    const source = within(allSources).getByLabelText(`查看来源：${reference.id}`)
    expect(source).toHaveRole('button')
    await userEvent.click(source)
    const drawer = screen.getByRole('dialog', { name: '来源证据' })
    expect(await within(drawer).findByText('Trace ID: source-read-trace')).toBeVisible()
    expect(within(drawer).getByText('body.quantity')).toBeVisible()
    expect(within(drawer).getByText('old-v1')).toBeVisible()
    await userEvent.click(within(drawer).getByLabelText('重试'))
    expect(await within(drawer).findByText('POST /frozen-orders')).toBeVisible()
    expect(within(drawer).getByText('v1')).toBeVisible()
    expect(versions).toEqual(['1', '1'])
    expect(writes).toBe(0)
  })

  it('keeps an unrecognized source reference as text without inventing navigation or fetching a target', async () => {
    const reference = { ...design.evidence_refs[0], source_ref: 'javascript:untrusted-source' }
    const saved = installLinkedProposal({ design: { ...design, evidence_refs: [reference] } })
    let details = 0
    server.use(
      http.get(`/api/v1/projects/${project.id}/apis/${apiDefinition.id}`, () => {
        details++
        return new HttpResponse(null, { status: 500 })
      }),
    )
    renderPage(`/projects/${project.id}/test-engineering?proposal=${saved.change_set_id}`)
    const sources = (await screen.findByText('完整设计来源（1条）')).closest<HTMLElement>(
      '.ant-card',
    )!
    await userEvent.click(within(sources).getByLabelText(`查看来源：${reference.id}`))
    const drawer = screen.getByRole('dialog', { name: '来源证据' })
    expect(within(drawer).getByText(reference.source_ref)).toBeVisible()
    expect(within(drawer).getByText('该来源没有可确认的产品对象入口，保留原始引用。')).toBeVisible()
    expect(within(drawer).queryByText('打开来源资产（当前目录）')).not.toBeInTheDocument()
    expect(within(drawer).queryByRole('link')).not.toBeInTheDocument()
    expect(details).toBe(0)
  })

  it('keeps an accepted design-only scenario blocked and never sends an apply request', async () => {
    let writes = 0
    const saved = installLinkedProposal({
      status: 'accepted',
      review_status: 'accepted',
      design: { ...design, oracles: [] },
    })
    server.use(
      http.post(`/api/v1/projects/${project.id}/test-engineering/proposals/*/apply`, () => {
        writes++
        return new HttpResponse(null, { status: 500 })
      }),
    )
    renderPage(`/projects/${project.id}/test-engineering?proposal=${saved.change_set_id}`)
    const generate = await findButton('生成工作流与用例草稿')
    expect(generate).toBeDisabled()
    expect(screen.getByText('有效订单：缺少唯一的确定性状态码预期')).toBeVisible()
    await userEvent.click(generate)
    expect(writes).toBe(0)
    expect(screen.queryByText('已生成资产草稿')).not.toBeInTheDocument()
  })

  it('recovers source inspection after a missing reference without retaining a stale drawer or warning', async () => {
    const missing = 'evidence-not-provided'
    const saved = installLinkedProposal({
      design: {
        ...design,
        oracles: [{ ...design.oracles[0], evidence_refs: [missing] }, design.oracles[1]],
      },
    })
    renderPage(`/projects/${project.id}/test-engineering?proposal=${saved.change_set_id}`)
    const sources = (await screen.findByText('完整设计来源（1条）')).closest<HTMLElement>(
      '.ant-card',
    )!
    const browser = userEvent.setup()
    await browser.click(screen.getAllByLabelText(`查看预期${design.oracles[0].id}的来源1`)[0])
    expect(await screen.findByText(`引用 ${missing} 未提供唯一来源`)).toBeVisible()
    expect(screen.queryByRole('dialog', { name: '来源证据' })).not.toBeInTheDocument()
    await browser.click(within(sources).getByLabelText('查看来源：evidence-contract'))
    const drawer = screen.getByRole('dialog', { name: '来源证据' })
    expect(within(drawer).getByText('contract://orders.create')).toBeVisible()
    expect(screen.queryByText(`引用 ${missing} 未提供唯一来源`)).not.toBeInTheDocument()
  })

  it('loads the exact proposal from a proposal deep link', async () => {
    const proposal: TestEngineeringProposal = {
      change_set_id: '00000000-0000-4000-8000-000000007099',
      status: 'draft',
      review_status: 'pending',
      fingerprint: 'deep-link-fingerprint',
      design,
      scenario_ids: ['scenario_happy_path'],
      applied: false,
      contract_completeness: 'complete',
      contract_fingerprint: 'd'.repeat(64),
      contract: operationContract,
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
      http.get(
        `/api/v1/projects/${project.id}/test-engineering/proposals/${proposal.change_set_id}`,
        () => HttpResponse.json(proposal),
      ),
    )
    renderPage(`/projects/${project.id}/test-engineering?proposal=${proposal.change_set_id}`)

    expect(await screen.findByText('验证 POST /orders 的契约边界')).toBeVisible()
    expect(actionButton('接受设计草稿')).toBeVisible()
  })
})

function renderPage(initialEntry?: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <ProjectTestProvider section="test-engineering" initialEntry={initialEntry}>
            <TestEngineeringPage />
            <RouteProbe />
          </ProjectTestProvider>
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
}

function actionButton(name: string): HTMLButtonElement {
  const element = screen.getByText(name, { exact: true }).closest('button')
  expect(element).toHaveRole('button')
  return element as HTMLButtonElement
}

async function findButton(name: string): Promise<HTMLButtonElement> {
  const element = (await screen.findByText(name, { exact: true })).closest('button')
  expect(element).toHaveRole('button')
  return element as HTMLButtonElement
}

function RouteProbe() {
  const location = useLocation()
  return (
    <div data-testid="design-route">
      {location.pathname}
      {location.search}
    </div>
  )
}

function installLinkedProposal(
  input: Partial<TestEngineeringProposal> = {},
): TestEngineeringProposal {
  const proposal: TestEngineeringProposal = {
    change_set_id: '00000000-0000-4000-8000-000000007999',
    status: 'draft',
    review_status: 'pending',
    fingerprint: 'saved-design',
    design,
    scenario_ids: ['scenario_happy_path'],
    applied: false,
    contract_completeness: 'complete',
    contract_fingerprint: 'f'.repeat(64),
    contract: operationContract,
    ...input,
  }
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
    ),
    http.get(`/api/v1/projects/${project.id}/apis`, () =>
      HttpResponse.json({ items: [apiDefinition], total: 1, page: 1, page_size: 100 }),
    ),
    http.get(`/api/v1/projects/${project.id}/environments`, () => HttpResponse.json([environment])),
    http.get(
      `/api/v1/projects/${project.id}/test-engineering/proposals/${proposal.change_set_id}`,
      () => HttpResponse.json(proposal),
    ),
  )
  return proposal
}
