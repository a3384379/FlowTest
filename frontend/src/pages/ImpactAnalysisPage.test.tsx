import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import type {
  ImpactCatalog,
  ImpactMapping,
  ImpactRunDetail,
  ImpactRunSummary,
} from '../features/impact/impact-service'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { project, user } from '../test/fixtures'
import { server } from '../test/server'
import ImpactAnalysisPage from './ImpactAnalysisPage'

const contractId = '00000000-0000-4000-8000-000000002001'
const baselineContractId = '00000000-0000-4000-8000-000000002002'
const schemaId = '00000000-0000-4000-8000-000000002003'
const baselineSchemaId = '00000000-0000-4000-8000-000000002004'
const mapping: ImpactMapping = {
  id: '00000000-0000-4000-8000-000000002010',
  project_id: project.id,
  source_kind: 'git',
  source_selector: 'backend/app/api/*',
  target_type: 'openapi_contract',
  target_id: contractId,
  target_name: '订单 OpenAPI',
  target_version: 'current.yaml',
  created_by_id: user.id,
  created_at: '2026-08-12T08:00:00Z',
}

const catalog: ImpactCatalog = {
  targets: [
    {
      id: baselineContractId,
      target_type: 'openapi_contract',
      name: '订单 OpenAPI 基线',
      version: 'baseline.yaml',
    },
    {
      id: contractId,
      target_type: 'openapi_contract',
      name: '订单 OpenAPI',
      version: 'current.yaml',
    },
  ],
  schemas: [
    { id: baselineSchemaId, protocol: 'graphql', name: '订单 GraphQL', version: 1 },
    { id: schemaId, protocol: 'graphql', name: '订单 GraphQL', version: 2 },
  ],
}

const run: ImpactRunDetail = {
  id: '00000000-0000-4000-8000-000000002020',
  project_id: project.id,
  title: '订单变更影响分析',
  source_ref: 'feature/order-v2',
  status: 'completed',
  source_fingerprint: 'a'.repeat(64),
  source_summary: { git: { file_count: 2 } },
  change_count: 2,
  summary: {
    change_count: 2,
    breaking_change_count: 1,
    selected_asset_count: 1,
    covered_change_count: 1,
    gap_count: 1,
    coverage_percent: 50,
  },
  created_by_id: user.id,
  created_at: '2026-08-12T08:10:00Z',
  changes: [
    {
      key: 'change-1',
      source_kind: 'git',
      source_key: 'backend/app/api/orders.py',
      change_type: 'changed',
      severity: 'warning',
      label: 'backend/app/api/orders.py',
      detail: '新增 2 行 / 删除 1 行',
      before: null,
      after: null,
    },
    {
      key: 'change-2',
      source_kind: 'graphql',
      source_key: 'Query.order',
      change_type: 'changed',
      severity: 'breaking',
      label: 'Query.order',
      detail: 'GraphQL 字段类型或参数签名发生变化',
      before: '(id:ID!)->Order',
      after: '(id:ID!)->Order!',
    },
  ],
  graph: {
    nodes: [
      { id: 'change:change-1', kind: 'change', label: 'backend/app/api/orders.py' },
      {
        id: `asset:openapi_contract:${contractId}`,
        kind: 'asset',
        label: '订单 OpenAPI',
        asset_type: 'contract',
      },
    ],
    edges: [
      {
        from: 'change:change-1',
        to: `asset:openapi_contract:${contractId}`,
        reason: '映射 backend/app/api/*',
      },
    ],
  },
  selection: {
    id: '00000000-0000-4000-8000-000000002021',
    strategy: 'explicit_mapping_v1',
    selected_assets: [
      {
        asset_type: 'contract',
        target_type: 'openapi_contract',
        target_id: contractId,
        name: '订单 OpenAPI',
        version: 'current.yaml',
        risk: 'medium',
        change_keys: ['change-1'],
        reasons: ['backend/app/api/* 命中 backend/app/api/orders.py'],
      },
    ],
    explanations: [],
    created_at: '2026-08-12T08:10:00Z',
  },
  coverage: {
    id: '00000000-0000-4000-8000-000000002022',
    total_changes: 2,
    covered_changes: 1,
    coverage_percent: 50,
    matrix: [
      {
        change_key: 'change-1',
        source_kind: 'git',
        source_key: 'backend/app/api/orders.py',
        label: 'backend/app/api/orders.py',
        severity: 'warning',
        case_count: 0,
        workflow_count: 0,
        contract_count: 1,
        performance_count: 0,
        covered: true,
      },
      {
        change_key: 'change-2',
        source_kind: 'graphql',
        source_key: 'Query.order',
        label: 'Query.order',
        severity: 'breaking',
        case_count: 0,
        workflow_count: 0,
        contract_count: 0,
        performance_count: 0,
        covered: false,
      },
    ],
    gaps: [
      {
        change_key: 'change-2',
        source_kind: 'graphql',
        source_key: 'Query.order',
        label: 'Query.order',
        reason: '没有显式资产映射覆盖此变更',
      },
    ],
    created_at: '2026-08-12T08:10:00Z',
  },
}

describe('ImpactAnalysisPage', () => {
  it('renders explainable impact evidence and creates a Git mapping and analysis', async () => {
    const mappings = [mapping]
    const runs: ImpactRunSummary[] = [run]
    let mappingPayload: Record<string, unknown> | null = null
    let runPayload: Record<string, unknown> | null = null
    installHandlers({ mappings, runs })
    server.use(
      http.post(`/api/v1/projects/${project.id}/impact/mappings`, async ({ request }) => {
        mappingPayload = (await request.json()) as Record<string, unknown>
        mappings.push({ ...mapping, id: '00000000-0000-4000-8000-000000002011' })
        return HttpResponse.json(mappings.at(-1), { status: 201 })
      }),
      http.post(`/api/v1/projects/${project.id}/impact/runs`, async ({ request }) => {
        runPayload = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(
          { ...run, id: '00000000-0000-4000-8000-000000002023' },
          { status: 201 },
        )
      }),
    )
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByRole('heading', { name: '变更影响分析' })).toBeVisible()
    expect(await screen.findByText('订单变更影响分析 · feature/order-v2')).toBeVisible()
    expect(screen.getByText('GraphQL 字段类型或参数签名发生变化')).toBeVisible()
    expect(screen.getByText('backend/app/api/* 命中 backend/app/api/orders.py')).toBeVisible()
    expect(screen.getByText('1 个覆盖缺口')).toBeVisible()

    await browser.click(screen.getByRole('button', { name: /登记资产映射/ }))
    await browser.type(screen.getByPlaceholderText(/backend\/app\/api/), 'frontend/src/*')
    await browser.click(screen.getByLabelText('关联平台资产'))
    await browser.click(await screen.findByText(/OpenAPI 契约 · 订单 OpenAPI · vcurrent.yaml/))
    await browser.click(
      within(screen.getByRole('dialog', { name: '登记影响资产映射' })).getByRole('button', {
        name: 'OK',
      }),
    )
    await waitFor(() => expect(mappingPayload).not.toBeNull())
    expect(mappingPayload).toEqual({
      source_kind: 'git',
      source_selector: 'frontend/src/*',
      target_type: 'openapi_contract',
      target_id: contractId,
    })

    await browser.click(screen.getByRole('button', { name: /新建影响分析/ }))
    await browser.clear(screen.getByLabelText('标准 Git unified diff'))
    await browser.type(
      screen.getByLabelText('标准 Git unified diff'),
      'diff --git a/frontend/src/App.tsx b/frontend/src/App.tsx\n--- a/frontend/src/App.tsx\n+++ b/frontend/src/App.tsx\n@@ -1 +1 @@\n-old\n+new',
    )
    await browser.click(
      within(screen.getByRole('dialog', { name: '新建变更影响分析' })).getByRole('button', {
        name: 'OK',
      }),
    )
    await waitFor(() => expect(runPayload).not.toBeNull())
    expect(runPayload).toMatchObject({
      title: '变更影响分析',
      git_diff: expect.stringContaining('diff --git'),
      openapi_diffs: [],
      schema_diffs: [],
    })
  })

  it('builds platform-version references, selects history, and deletes mappings', async () => {
    const older = { ...run, id: '00000000-0000-4000-8000-000000002024', title: '较早分析' }
    let runPayload: Record<string, unknown> | null = null
    let deleted = 0
    installHandlers({ mappings: [mapping], runs: [run, older], details: [run, older] })
    server.use(
      http.post(`/api/v1/projects/${project.id}/impact/runs`, async ({ request }) => {
        runPayload = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(run, { status: 201 })
      }),
      http.delete(`/api/v1/projects/${project.id}/impact/mappings/${mapping.id}`, () => {
        deleted += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    renderPage()
    const browser = userEvent.setup()

    await screen.findByText('订单变更影响分析 · feature/order-v2')
    await browser.click(screen.getByRole('button', { name: /新建影响分析/ }))
    await browser.click(screen.getByLabelText('OpenAPI 基线'))
    await browser.click(await screen.findByText(/订单 OpenAPI 基线/))
    await browser.click(screen.getByLabelText('OpenAPI 当前版本'))
    await browser.click((await screen.findAllByText(/订单 OpenAPI · vcurrent.yaml/)).at(-1)!)
    await browser.click(screen.getByLabelText('Schema 基线'))
    await browser.click(await screen.findByText(/订单 GraphQL · v1/))
    await browser.click(screen.getByLabelText('Schema 当前版本'))
    await browser.click((await screen.findAllByText(/订单 GraphQL · v2/)).at(-1)!)
    await browser.click(
      within(screen.getByRole('dialog', { name: '新建变更影响分析' })).getByRole('button', {
        name: 'OK',
      }),
    )
    await waitFor(() => expect(runPayload).not.toBeNull())
    expect(runPayload).toMatchObject({
      openapi_diffs: [{ baseline_run_id: baselineContractId, current_run_id: contractId }],
      schema_diffs: [{ baseline_artifact_id: baselineSchemaId, current_artifact_id: schemaId }],
    })

    await browser.click(screen.getByText('较早分析'))
    expect(await screen.findByText('较早分析 · feature/order-v2')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: `删除映射 ${mapping.source_selector}` }))
    const confirmation = await screen.findByText('确认删除此映射？')
    await browser.click(
      within(confirmation.closest('.ant-popconfirm')!).getByRole('button', { name: 'OK' }),
    )
    await waitFor(() => expect(deleted).toBe(1))
  })

  it('shows an empty state and requires at least one complete source', async () => {
    installHandlers({ mappings: [], runs: [] })
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByText('登记映射并创建首个影响分析')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: /新建影响分析/ }))
    await browser.click(
      within(screen.getByRole('dialog', { name: '新建变更影响分析' })).getByRole('button', {
        name: 'OK',
      }),
    )
    expect(await screen.findByText('至少提供 Git Diff 或一组完整 Schema 版本')).toBeInTheDocument()
  })
})

function installHandlers({
  mappings,
  runs,
  details = [run],
}: {
  mappings: ImpactMapping[]
  runs: ImpactRunSummary[]
  details?: ImpactRunDetail[]
}) {
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
    ),
    http.get(`/api/v1/projects/${project.id}/impact/mappings`, () =>
      HttpResponse.json({ items: mappings, total: mappings.length, page: 1, page_size: 100 }),
    ),
    http.get(`/api/v1/projects/${project.id}/impact/catalog`, () => HttpResponse.json(catalog)),
    http.get(`/api/v1/projects/${project.id}/impact/runs`, () =>
      HttpResponse.json({ items: runs, total: runs.length, page: 1, page_size: 100 }),
    ),
    ...details.map((detail) =>
      http.get(`/api/v1/projects/${project.id}/impact/runs/${detail.id}`, () =>
        HttpResponse.json(detail),
      ),
    ),
  )
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <ProjectTestProvider section="impact">
          <ImpactAnalysisPage />
        </ProjectTestProvider>
      </QueryClientProvider>
    </AntdApp>,
  )
}
