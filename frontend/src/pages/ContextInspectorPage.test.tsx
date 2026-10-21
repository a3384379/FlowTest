import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import type {
  ContextDetail,
  ContextSummary,
} from '../features/context-inspector/context-inspector-service'
import { useLocation } from 'react-router-dom'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { project } from '../test/fixtures'
import { server } from '../test/server'
import ContextInspectorPage from './ContextInspectorPage'

const contextId = '00000000-0000-4000-8000-000000005701'
const revisionId = '00000000-0000-4000-8000-000000005702'
const proposalId = '00000000-0000-4000-8000-000000005703'
const timestamp = '2026-08-31T08:00:00Z'

const summary: ContextSummary = {
  id: contextId,
  project_id: project.id,
  name: 'RuoYi 订单上下文',
  objective: '检查 Controller 到 Mapper 的可追溯证据',
  status: 'ready',
  current_revision: 3,
  revision_id: revisionId,
  revision_fingerprint: 'a'.repeat(64),
  completeness: {
    required: ['repository', 'data_profile'],
    present: ['repository', 'data_profile'],
    missing: [],
    complete: true,
  },
  conflict_count: 0,
  evidence_count: 1,
  provider_count: 1,
  proposal_count: 1,
  expires_at: '2026-09-01T08:00:00Z',
  created_at: timestamp,
  updated_at: timestamp,
}

const detail: ContextDetail = {
  ...summary,
  organization_id: '00000000-0000-4000-8000-000000005704',
  target_environment_id: null,
  created_by_type: 'service_account',
  created_by_id: '00000000-0000-4000-8000-000000005705',
  closed_at: null,
  revision: {
    schema_version: 'flowtest-context-revision-v1',
    repository_revisions: [{ source_ref: 'repository://ruoyi', revision: 'ruoyi-fixed' }],
    contract_revisions: [],
    data_profile_revisions: [],
    existing_test_revision: null,
    knowledge_snapshot: {
      schema_version: 'flowtest-context-knowledge-v1',
      nodes: [
        {
          id: 'operation.create_order',
          kind: 'operation',
          label: 'POST /orders',
          facts: [{ name: 'evidence_ref', value: `evidence://context/${'b'.repeat(64)}` }],
        },
        {
          id: 'state.order_created',
          kind: 'state_candidate',
          label: 'Order.CREATED',
          facts: [{ name: 'evidence_ref', value: `evidence://context/${'b'.repeat(64)}` }],
        },
      ],
      edges: [
        {
          source: 'operation.create_order',
          target: 'state.order_created',
          relation: 'allows_state',
        },
      ],
    },
    conflict_snapshot: {
      schema_version: 'flowtest-context-conflicts-v1',
      conflicts: [],
    },
    completeness: summary.completeness,
    evidence_fingerprints: ['b'.repeat(64)],
  },
  providers: [
    {
      source_type: 'repository',
      provider_name: 'flowtest-java-spring',
      provider_version: '1.0.0',
      finding_count: 1,
      deterministic_count: 1,
      conflict_count: 0,
    },
  ],
  evidence_items: [
    {
      id: '00000000-0000-4000-8000-000000005706',
      source_type: 'repository',
      provider_name: 'flowtest-java-spring',
      provider_version: '1.0.0',
      source_ref: 'repository://ruoyi',
      source_revision: 'ruoyi-fixed',
      subject_ref: 'java://com.ruoyi.OrderController.create',
      finding: {
        id: 'route-create-order',
        kind: 'operation',
        semantic_role: 'normative',
        source_ref: 'repository://ruoyi',
        source_revision: 'ruoyi-fixed',
        subject_ref: 'java://com.ruoyi.OrderController.create',
        source_path: 'src/OrderController.java:20',
        source_content: 'structured_analysis',
        content_role: 'untrusted_data',
        statement: 'OrderController.create 提供 POST /orders 路由',
        confidence: 1,
        deterministic: true,
        semantic_fingerprint: 'c'.repeat(64),
      },
      semantic_role: 'normative',
      deterministic: true,
      confidence: 1,
      fingerprint: 'b'.repeat(64),
      warnings: [{ code: 'LOMBOK_REVIEW', message: 'Lombok 语义需人工确认' }],
      redaction_count: 0,
      created_at: timestamp,
      expires_at: summary.expires_at,
    },
  ],
  proposals: [
    {
      id: proposalId,
      title: 'RuoYi 订单 Flow Proposal',
      status: 'draft',
      review_status: 'pending',
      applied: false,
      target_workflow_id: null,
      target_revision: null,
      source_ref: `mcp://contexts/${contextId}/revisions/${revisionId}/flow-drafts`,
      created_at: timestamp,
      updated_at: timestamp,
    },
  ],
}

describe('ContextInspectorPage', () => {
  it('reaches older contexts beyond the first one hundred without fetching all pages', async () => {
    const pages: number[] = []
    server.use(
      http.get(`/api/v1/projects/${project.id}/contexts`, ({ request }) => {
        const url = new URL(request.url)
        const page = Number(url.searchParams.get('page'))
        pages.push(page)
        expect(url.searchParams.get('page_size')).toBe('20')
        return HttpResponse.json({
          items: [{ ...summary, name: page === 6 ? '第一百零一个上下文' : summary.name }],
          total: 101,
          page,
          page_size: 20,
        })
      }),
      http.get(`/api/v1/projects/${project.id}/contexts/${contextId}`, () =>
        HttpResponse.json(detail),
      ),
    )
    renderPage()
    expect(await screen.findByRole('button', { name: /RuoYi 订单上下文/ })).toBeVisible()
    await userEvent.click(screen.getByTitle('6'))
    expect(await screen.findByRole('button', { name: /第一百零一个上下文/ })).toBeVisible()
    expect(pages).toEqual([1, 6])
  })

  it('shows revision evidence, state knowledge and a proposal deep-link', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/contexts`, () =>
        HttpResponse.json({ items: [summary], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/contexts/${contextId}`, () =>
        HttpResponse.json(detail),
      ),
    )
    renderPage()

    expect(await screen.findByRole('heading', { name: '上下文检查器' })).toBeVisible()
    await userEvent.click(await findContextTab('证据'))
    expect(await screen.findByText('OrderController.create 提供 POST /orders 路由')).toBeVisible()
    await userEvent.click(getContextButton(`查看证据 ${detail.evidence_items[0].id}`))
    expect(screen.getByText('flowtest-java-spring 1.0.0')).toBeVisible()
    expect(screen.getByText('LOMBOK_REVIEW：Lombok 语义需人工确认')).toBeVisible()
    await userEvent.click(await findContextTab('知识关系'))
    expect(screen.getAllByText('Order.CREATED')).toHaveLength(2)
    expect(screen.getByText('allows_state')).toBeVisible()
    await userEvent.click(await findContextTab('关联提案'))
    expect(screen.getByText('RuoYi 订单 Flow Proposal')).toBeVisible()
    expect(screen.getByRole('link', { name: /打开 Proposal/ })).toHaveAttribute(
      'href',
      `/projects/${project.id}/workflows?proposal=${proposalId}`,
    )
  })

  it('shows a stable empty state without requesting detail', async () => {
    let detailReads = 0
    server.use(
      http.get(`/api/v1/projects/${project.id}/contexts`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/contexts/:contextId`, () => {
        detailReads += 1
        return HttpResponse.json(detail)
      }),
    )
    renderPage()

    expect(await screen.findByText('暂无 Test Context')).toBeVisible()
    expect(screen.getByText('选择 Context 查看当前 Revision')).toBeVisible()
    expect(detailReads).toBe(0)
  })

  it('renders missing evidence, conflicts and bounded empty detail sections', async () => {
    const conflictedSummary: ContextSummary = {
      ...summary,
      status: 'conflicted',
      conflict_count: 1,
      evidence_count: 0,
      provider_count: 0,
      proposal_count: 0,
      completeness: {
        required: ['repository', 'data_profile'],
        present: ['repository'],
        missing: ['data_profile'],
        complete: false,
      },
    }
    const conflictedDetail: ContextDetail = {
      ...detail,
      ...conflictedSummary,
      revision: {
        ...detail.revision,
        completeness: conflictedSummary.completeness,
        knowledge_snapshot: {
          schema_version: 'flowtest-context-knowledge-v1',
          nodes: [],
          edges: [],
        },
        conflict_snapshot: {
          schema_version: 'flowtest-context-conflicts-v1',
          conflicts: [
            {
              subject_ref: 'java://Order.status',
              finding_fingerprints: ['d'.repeat(64), 'e'.repeat(64)],
              summary: '订单状态声明冲突',
            },
          ],
        },
        evidence_fingerprints: [],
      },
      providers: [],
      evidence_items: [],
      proposals: [],
    }
    server.use(
      http.get(`/api/v1/projects/${project.id}/contexts`, () =>
        HttpResponse.json({ items: [conflictedSummary], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/contexts/${contextId}`, () =>
        HttpResponse.json(conflictedDetail),
      ),
    )
    renderPage()

    await userEvent.click(await screen.findByRole('tab', { name: '完整性与冲突' }))
    expect(await screen.findByText('缺少 Evidence：数据画像')).toBeVisible()
    expect(screen.getByText('订单状态声明冲突')).toBeVisible()
    expect(screen.getAllByText('java://Order.status')).toHaveLength(1)
    await userEvent.click(screen.getByRole('tab', { name: '证据' }))
    expect(screen.getByText('当前 Revision 暂无 Finding')).toBeVisible()
    await userEvent.click(screen.getByRole('tab', { name: '知识关系' }))
    expect(screen.getByText('暂无 State Candidate')).toBeVisible()
    await userEvent.click(screen.getByRole('tab', { name: '关联提案' }))
    expect(screen.getByText('当前 Revision 暂无关联 Proposal')).toBeVisible()
    expect(screen.getAllByText('有冲突').length).toBeGreaterThan(0)
  })

  it('switches the active context without changing the project scope', async () => {
    const secondContextId = '00000000-0000-4000-8000-000000005707'
    const secondSummary: ContextSummary = {
      ...summary,
      id: secondContextId,
      name: '已过期支付上下文',
      status: 'expired',
    }
    server.use(
      http.get(`/api/v1/projects/${project.id}/contexts`, () =>
        HttpResponse.json({ items: [summary, secondSummary], total: 2, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/contexts/:contextId`, ({ params }) =>
        HttpResponse.json(
          params.contextId === secondContextId
            ? { ...detail, ...secondSummary, proposals: [] }
            : detail,
        ),
      ),
    )
    renderPage()
    const browser = userEvent.setup()

    await userEvent.click(await screen.findByRole('tab', { name: '证据' }))
    expect(await screen.findByText('OrderController.create 提供 POST /orders 路由')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: /已过期支付上下文/ }))

    expect((await screen.findAllByText('已过期支付上下文')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('已过期').length).toBeGreaterThan(0)
  })
  it('links a conflict to its exact frozen finding and reports filtered and total evidence counts without writes', async () => {
    let writes = 0,
      reads = 0
    const other = {
      ...detail.evidence_items[0],
      id: 'other-evidence',
      source_type: 'contract' as const,
      fingerprint: 'd'.repeat(64),
      deterministic: false,
      warnings: [],
      finding: {
        ...detail.evidence_items[0].finding,
        statement: '第二条契约来源',
        source_path: 'contract#/status',
        deterministic: false,
      },
    }
    const linked = {
      ...detail,
      evidence_count: 2,
      conflict_count: 1,
      evidence_items: [detail.evidence_items[0], other],
      revision: {
        ...detail.revision,
        conflict_snapshot: {
          schema_version: 'flowtest-context-conflicts-v1',
          conflicts: [
            {
              subject_ref: detail.evidence_items[0].subject_ref,
              finding_fingerprints: [detail.evidence_items[0].fingerprint],
              summary: '固定冲突来源',
            },
          ],
        },
      },
    }
    server.use(
      http.get(`/api/v1/projects/${project.id}/contexts`, () =>
        HttpResponse.json({ items: [summary], total: 1, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/contexts/${contextId}`, () => {
        reads++
        return HttpResponse.json(linked)
      }),
      http.post('/api/v1/*', () => {
        writes++
        return HttpResponse.json({})
      }),
    )
    renderPage()
    await userEvent.click(await screen.findByRole('tab', { name: '完整性与冲突' }))
    await userEvent.click(getContextButton('定位冲突证据 1'))
    expect(await screen.findByText('显示 1 / 2 条证据')).toBeVisible()
    await userEvent.click(getContextButton(`查看证据 ${detail.evidence_items[0].id}`))
    const finding = screen.getByRole('region', { name: '证据详情' })
    expect(within(finding).getByText('ruoyi-fixed', { exact: true })).toBeInTheDocument()
    expect(
      within(finding).getByText('src/OrderController.java:20', { exact: true }),
    ).toBeInTheDocument()
    expect(screen.getByTestId('context-route')).toHaveTextContent(
      `evidence=${detail.evidence_items[0].id}`,
    )
    expect(screen.getByTestId('context-route')).toHaveTextContent(`revision=${revisionId}`)
    await userEvent.click(screen.getByRole('button', { name: '清除证据筛选' }))
    expect(screen.getByText('显示 2 / 2 条证据')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('combobox', { name: '证据确定性' }))
    await userEvent.click(
      screen.getByText('需复核', { selector: '.ant-select-item-option-content' }),
    )
    expect(screen.getByText('显示 1 / 2 条证据')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('checkbox', { name: '仅含警告' }))
    expect(screen.getByText('显示 0 / 2 条证据')).toBeInTheDocument()
    expect(reads).toBe(1)
    expect(writes).toBe(0)
  })
  it('restores a knowledge node and resolves only evidence references present in the selected revision', async () => {
    server.use(
      http.get(`/api/v1/projects/${project.id}/contexts`, () =>
        HttpResponse.json({ items: [summary], total: 1, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/contexts/${contextId}`, () =>
        HttpResponse.json(detail),
      ),
    )
    renderPage(
      `/projects/${project.id}/contexts?focus=${contextId}&revision=${revisionId}&panel=knowledge&knowledge=state.order_created`,
    )
    await userEvent.click(await screen.findByRole('button', { name: '定位关联证据' }))
    expect(await screen.findByRole('region', { name: '证据详情' })).toHaveTextContent(
      'OrderController.create 提供 POST /orders 路由',
    )
    expect(screen.getByTestId('context-route')).toHaveTextContent(
      `evidence=${detail.evidence_items[0].id}`,
    )
    expect(screen.getByTestId('context-route')).toHaveTextContent(`focus=${contextId}`)
  })
  it('does not substitute a newer current revision for a fixed older revision', async () => {
    const currentRevision = '00000000-0000-4000-8000-000000005799'
    server.use(
      http.get(`/api/v1/projects/${project.id}/contexts`, () =>
        HttpResponse.json({ items: [summary], total: 1, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/contexts/${contextId}`, () =>
        HttpResponse.json({ ...detail, current_revision: 4, revision_id: currentRevision }),
      ),
    )
    renderPage(
      `/projects/${project.id}/contexts?focus=${contextId}&revision=${revisionId}&panel=evidence&evidence=${detail.evidence_items[0].id}`,
    )
    expect(await screen.findByText('所选固定修订不可读取')).toBeVisible()
    expect(screen.queryByRole('region', { name: '证据详情' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '查看当前修订' }))
    await waitFor(() =>
      expect(screen.getByTestId('context-route')).toHaveTextContent(`revision=${currentRevision}`),
    )
    expect(screen.queryByText('所选固定修订不可读取')).not.toBeInTheDocument()
  })
  it('preserves unknown conflict and knowledge references without inventing source links or making writes', async () => {
    let writes = 0,
      reads = 0
    const unknown = 'javascript:unknown-evidence'
    const missing = 'e'.repeat(64)
    const current = {
      ...detail,
      revision: {
        ...detail.revision,
        knowledge_snapshot: {
          ...detail.revision.knowledge_snapshot,
          nodes: [
            {
              id: 'unknown-node',
              kind: 'state_candidate',
              label: '未知引用节点',
              facts: [{ name: 'evidence_ref', value: unknown }],
            },
          ],
        },
        conflict_snapshot: {
          schema_version: 'flowtest-context-conflicts-v1',
          conflicts: [
            {
              subject_ref: 'unknown://subject',
              summary: '未载入的冲突引用',
              finding_fingerprints: [missing],
            },
          ],
        },
      },
    }
    server.use(
      http.get(`/api/v1/projects/${project.id}/contexts`, () =>
        HttpResponse.json({ items: [summary], total: 1, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/contexts/${contextId}`, () => {
        reads++
        return HttpResponse.json(current)
      }),
      http.post('/api/v1/*', () => {
        writes++
        return HttpResponse.json({})
      }),
    )
    renderPage(
      `/projects/${project.id}/contexts?focus=${contextId}&revision=${revisionId}&panel=knowledge&knowledge=unknown-node`,
    )
    expect(await screen.findByText('当前修订没有可唯一定位的证据引用')).toBeInTheDocument()
    expect(screen.getAllByText(unknown).length).toBeGreaterThan(0)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '定位关联证据' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: '完整性与冲突' }))
    await userEvent.click(screen.getByRole('button', { name: '定位冲突证据 1' }))
    expect(screen.getByText('显示 0 / 1 条证据')).toBeInTheDocument()
    expect(screen.getByText(missing, { exact: true })).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: `查看证据 ${detail.evidence_items[0].id}` }),
    ).not.toBeInTheDocument()
    expect(reads).toBe(1)
    expect(writes).toBe(0)
  })
  it('rejects a foreign-project response and retries without substituting another context', async () => {
    let valid = false
    server.use(
      http.get(`/api/v1/projects/${project.id}/contexts`, () =>
        HttpResponse.json({ items: [summary], total: 1, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/contexts/${contextId}`, () =>
        HttpResponse.json({ ...detail, project_id: valid ? project.id : 'foreign' }),
      ),
    )
    renderPage(`/projects/${project.id}/contexts?focus=${contextId}&revision=${revisionId}`)
    expect(await screen.findByText('上下文响应项目或ID不匹配')).toBeVisible()
    expect(screen.queryByRole('tab', { name: '证据' })).not.toBeInTheDocument()
    valid = true
    await userEvent.click(screen.getByRole('button', { name: '重试详情' }))
    await userEvent.click(await screen.findByRole('tab', { name: '证据' }))
    expect(screen.getByText(detail.evidence_items[0].finding.statement)).toBeVisible()
  })
})

async function findContextTab(name: string): Promise<HTMLElement> {
  const contextDetails = screen.getByLabelText('上下文详情')
  const tab = await within(contextDetails).findByText(name, { selector: '[role="tab"]' })
  expect(tab).toHaveRole('tab')
  expect(tab).toHaveAccessibleName(name)
  expect(tab).toBeVisible()
  expect(tab.closest('[aria-hidden="true"]')).toBeNull()
  return tab
}

function getContextButton(name: string): HTMLElement {
  const contextDetails = screen.getByLabelText('上下文详情')
  const button = within(contextDetails).getByLabelText(name, { selector: 'button' })
  expect(button).toHaveRole('button')
  expect(button).toHaveAccessibleName(name)
  expect(button).toBeVisible()
  expect(button.closest('[aria-hidden="true"]')).toBeNull()
  return button
}

function renderPage(initialEntry = `/projects/${project.id}/contexts`) {
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
    ),
  )
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <ProjectTestProvider section="contexts" initialEntry={initialEntry}>
            <ContextInspectorPage />
            <InspectorRouteProbe />
          </ProjectTestProvider>
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
}

function InspectorRouteProbe() {
  const location = useLocation()
  return <output data-testid="context-route">{location.search}</output>
}
