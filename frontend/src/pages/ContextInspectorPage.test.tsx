import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import type {
  ContextDetail,
  ContextSummary,
} from '../features/context-inspector/context-inspector-service'
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
    expect(await screen.findByText('OrderController.create 提供 POST /orders 路由')).toBeVisible()
    expect(screen.getByText('flowtest-java-spring 1.0.0')).toBeVisible()
    expect(screen.getAllByText('Order.CREATED')).toHaveLength(2)
    expect(screen.getByText('allows_state')).toBeVisible()
    expect(screen.getByText('LOMBOK_REVIEW：Lombok 语义需人工确认')).toBeVisible()
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

    expect(await screen.findByText('缺少 Evidence：数据画像')).toBeVisible()
    expect(screen.getByText('订单状态声明冲突')).toBeVisible()
    expect(screen.getAllByText('java://Order.status')).toHaveLength(1)
    expect(screen.getByText('当前 Revision 暂无 Finding')).toBeVisible()
    expect(screen.getByText('暂无 State Candidate')).toBeVisible()
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

    expect(await screen.findByText('OrderController.create 提供 POST /orders 路由')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: /已过期支付上下文/ }))

    expect((await screen.findAllByText('已过期支付上下文')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('已过期').length).toBeGreaterThan(0)
  })
})

function renderPage() {
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
        <ProjectTestProvider section="contexts" initialEntry={`/projects/${project.id}/contexts`}>
          <ContextInspectorPage />
        </ProjectTestProvider>
      </QueryClientProvider>
    </AntdApp>,
  )
}
