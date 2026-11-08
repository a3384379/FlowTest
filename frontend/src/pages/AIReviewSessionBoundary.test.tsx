import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, Link, RouterProvider } from 'react-router-dom'
import { afterEach, expect, it } from 'vitest'

import type { AIChangeItem, AIChangeSetDetail } from '../features/ai/ai-change-set-service'
import type { AIJob, AISuggestion } from '../features/ai/ai-service'
import { useAuthStore } from '../features/auth/auth-store'
import { DraftSessionProvider } from '../features/drafts/DraftSessionProvider'
import ProjectProvider from '../features/projects/ProjectProvider'
import { authenticateTestUser } from '../test/auth'
import { project, user, workflow } from '../test/fixtures'
import { server } from '../test/server'
import AIAssistantPage from './AIAssistantPage'
import AIChangeSetsPage from './AIChangeSetsPage'
import OrganizationGovernancePage from './OrganizationGovernancePage'

const organizationId = '00000000-0000-4000-8000-000000000801'
const date = '2026-10-22T00:00:00Z'
const catalog = (type: 'workflow' | 'test_case', projectId = project.id) =>
  type === 'workflow'
    ? ['workflows', projectId, 'catalog', '', 1]
    : ['test-cases', projectId, '', '', 'all', 1, { order: 'updated_desc' }]

afterEach(() => {
  localStorage.clear()
  useAuthStore.setState({ user: null, organizationId: null })
})

it.each(
  (['suggestion', 'change-set'] as const).flatMap((kind) =>
    (['workflow', 'test_case'] as const).map((type) => ({ kind, type })),
  ),
)(
  'marks only the original $type caches stale after a pending $kind accept leaves for real organization scope',
  async ({ kind, type }) => {
    authenticateTestUser(user)
    useAuthStore.setState({ organizationId: null })
    const { job, suggestion, item, detail } = boundaryRecords(type)
    let release!: () => void
    const response = new Promise<void>((resolve) => {
      release = resolve
    })
    let writes = 0
    let assetReads = 0
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get('/api/v1/ai/status', () =>
        HttpResponse.json({ enabled: true, sample_sharing_enabled: false }),
      ),
      http.get('/api/v1/ai/jobs', () =>
        HttpResponse.json({ items: [job], total: 1, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/ai/jobs/${job.id}`, () => HttpResponse.json(job)),
      http.get(`/api/v1/ai/jobs/${job.id}/suggestions`, () => HttpResponse.json([suggestion])),
      http.get('/api/v1/ai/change-sets', () =>
        HttpResponse.json({ items: [detail], total: 1, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/ai/change-sets/${detail.id}`, () => HttpResponse.json(detail)),
      http.get(`/api/v1/projects/${project.id}/impact/runs`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/release-risks`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/workflows`, () => {
        assetReads += 1
        return HttpResponse.json({ items: [workflow], total: 1, page: 1, page_size: 100 })
      }),
      http.get(`/api/v1/projects/${project.id}/test-cases`, () => {
        assetReads += 1
        return HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 })
      }),
      http.post(
        kind === 'suggestion'
          ? `/api/v1/ai/suggestions/${suggestion.id}/accept`
          : `/api/v1/ai/change-sets/${detail.id}/items/${item.id}/accept`,
        async () => {
          writes += 1
          await response
          return HttpResponse.json(boundaryReceipt(kind, type, suggestion, item))
        },
      ),
    )
    installOrganizationReads()
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: 15_000 }, mutations: { retry: false } },
    })
    const originalKey = catalog(type)
    const otherType = type === 'workflow' ? 'test_case' : 'workflow'
    client.setQueryData(originalKey, { items: [], total: 0, page: 1, page_size: 100 })
    client.setQueryData(catalog(otherType), { items: [], total: 0, page: 1, page_size: 100 })
    client.setQueryData(catalog(type, 'another-project'), {
      items: [],
      total: 0,
      page: 1,
      page_size: 100,
    })
    const router = renderBoundaryPage(kind, client, job.id, detail.id)
    const labels = {
      suggestion: { dialog: '接受建议', confirm: '确认接受', guard: '审核内容尚未保存' },
      'change-set': { dialog: '编辑并接受变更项', confirm: 'OK', guard: '审核修改尚未保存' },
    }[kind]
    const browser = userEvent.setup()
    if (kind === 'suggestion') {
      const title = await screen.findByText(suggestion.title)
      await browser.click(within(title.closest('tr')!).getByRole('button', { name: /接受/ }))
    } else await browser.click(await screen.findByRole('button', { name: '审核并接受' }))
    const title = await screen.findByText(labels.dialog, {
      selector: '.ant-modal-title',
    })
    const note = within(title.closest('.ant-modal') as HTMLElement).getByLabelText('审核备注')
    await browser.click(note)
    await browser.paste('已核对来源后提交')
    await browser.click(
      within(title.closest('.ant-modal') as HTMLElement).getByRole('button', {
        name: labels.confirm,
      }),
    )
    await waitFor(() => expect(writes).toBe(1))
    try {
      await browser.click(screen.getByRole('link', { name: '前往组织治理' }))
      const guardTitle = await screen.findByText(labels.guard, { selector: '.ant-modal-title' })
      await browser.click(
        within(guardTitle.closest('.ant-modal') as HTMLElement).getByRole('button', {
          name: '放弃修改并离开',
        }),
      )
      await screen.findByText('组织与角色')
      expect(useAuthStore.getState().organizationId).toBeNull()
      await browser.click(screen.getByRole('combobox', { name: '治理组织' }))
      await browser.click(
        screen.getByText('合成组织 · synthetic', { selector: '.ant-select-item-option-content' }),
      )
      await waitFor(() => expect(useAuthStore.getState().organizationId).toBe(organizationId))
    } finally {
      await act(async () => {
        release()
        await response
      })
    }
    await waitFor(() =>
      expect(
        client
          .getMutationCache()
          .getAll()
          .every((mutation) => mutation.state.status !== 'pending'),
      ).toBe(true),
    )
    expect.soft(client.getQueryState(originalKey)?.isInvalidated).toBe(true)
    expect(client.getQueryState(catalog(otherType))?.isInvalidated).toBe(false)
    expect(client.getQueryState(catalog(type, 'another-project'))?.isInvalidated).toBe(false)
    if (kind === 'suggestion')
      expect
        .soft(
          client.getQueryState(['ai-suggestions', project.id, job.id, 'completed'])?.isInvalidated,
        )
        .toBe(true)
    else {
      expect
        .soft(client.getQueryState(['ai-change-set', project.id, detail.id])?.isInvalidated)
        .toBe(true)
      const records = client.getQueryCache().findAll({ queryKey: ['ai-change-sets', project.id] })
      expect(records.length).toBeGreaterThan(0)
      expect.soft(records.every((query) => query.state.isInvalidated)).toBe(true)
    }
    expect(assetReads).toBe(0)
    expect(writes).toBe(1)
    expect(router.state.location.pathname).toBe('/organization')
    expect(screen.queryByText('boundary-result')).not.toBeInTheDocument()
    expect(screen.queryByText('审核结果已保存')).not.toBeInTheDocument()
    expect(screen.queryByText('变更项已接受并生成草稿')).not.toBeInTheDocument()
  },
)

function installOrganizationReads() {
  server.use(
    http.get('/api/v1/organizations', () =>
      HttpResponse.json([
        {
          id: organizationId,
          name: '合成组织',
          slug: 'synthetic',
          description: '',
          enabled: true,
          created_by_id: user.id,
          role: 'owner',
          member_count: 0,
          created_at: date,
          updated_at: date,
        },
      ]),
    ),
    http.get(`/api/v1/organizations/${organizationId}/members`, () => HttpResponse.json([])),
    http.get(`/api/v1/organizations/${organizationId}/service-accounts`, () =>
      HttpResponse.json([]),
    ),
    http.get(`/api/v1/organizations/${organizationId}/governance`, () =>
      HttpResponse.json({
        organization_id: organizationId,
        audit_retention_days: 365,
        quota_policies: {},
        runner_policy: {
          allowed_runner_types: [],
          allowed_runtimes: [],
          max_pools: 0,
          registration_requires_approval: false,
        },
        active_key_version: 1,
        updated_at: date,
      }),
    ),
    http.get(`/api/v1/organizations/${organizationId}/runner-governance`, () =>
      HttpResponse.json({
        pool_count: 0,
        runner_count: 0,
        current_load: 0,
        capacity: 0,
        pools: [],
      }),
    ),
    http.get(`/api/v1/organizations/${organizationId}/security`, () =>
      HttpResponse.json({
        organization_id: organizationId,
        enabled: false,
        active_key_version: 1,
        key_versions: [],
      }),
    ),
    http.get(`/api/v1/organizations/${organizationId}/support-bundle/redaction`, () =>
      HttpResponse.json({
        organization_id: organizationId,
        schema_version: 'synthetic',
        data_classification: 'internal-redacted',
        included_sections: [],
        redacted_fields: [],
        excluded_fields: [],
      }),
    ),
  )
}

function boundaryRecords(type: 'workflow' | 'test_case'): {
  job: AIJob
  suggestion: AISuggestion
  item: AIChangeItem
  detail: AIChangeSetDetail
} {
  const job: AIJob = {
    id: 'boundary-job',
    project_id: project.id,
    job_type: type === 'workflow' ? 'workflow_draft' : 'schema_cases',
    status: 'completed',
    input_sha256: 'a'.repeat(64),
    prompt_template_version: 'synthetic-v1',
    model_name: 'synthetic',
    sample_included: false,
    token_usage: {},
    error_code: null,
    error_message: null,
    created_by_id: user.id,
    created_at: date,
    updated_at: date,
  }
  const suggestion: AISuggestion = {
    id: 'boundary-suggestion',
    job_id: job.id,
    position: 0,
    suggestion_type: type,
    title: '合成边界建议',
    content: { name: '边界草稿', definition: { schema_version: '1.0' } },
    review_status: 'pending',
    review_note: '',
    accepted_resource_type: null,
    accepted_resource_id: null,
    created_at: date,
    updated_at: date,
  }
  const item: AIChangeItem = {
    id: 'boundary-item',
    position: 0,
    item_type: type,
    action: 'create',
    title: '合成边界变更',
    target_resource_id: null,
    target_snapshot_sha256: null,
    proposed_content: suggestion.content,
    review_status: 'pending',
    review_note: '',
    reviewed_by_id: null,
    reviewed_at: null,
    materialized_resource_type: null,
    materialized_resource_id: null,
    created_at: date,
    updated_at: date,
  }
  const detail: AIChangeSetDetail = {
    id: 'boundary-change-set',
    project_id: project.id,
    impact_run_id: 'boundary-impact',
    release_risk_id: 'boundary-risk',
    ai_job_id: job.id,
    title: '合成边界变更集',
    status: 'draft',
    source_fingerprint: 'b'.repeat(64),
    created_by_id: user.id,
    created_at: date,
    updated_at: date,
    source_snapshot: {},
    review_baselines: [],
    items: [item],
  }
  return { job, suggestion, item, detail }
}

function renderBoundaryPage(
  kind: 'suggestion' | 'change-set',
  client: QueryClient,
  jobId: string,
  changeSetId: string,
) {
  const path =
    kind === 'suggestion'
      ? `/projects/${project.id}/ai?job=${jobId}`
      : `/projects/${project.id}/ai-changes?focus=${changeSetId}`
  const router = createMemoryRouter(
    [
      {
        path: '/projects/:projectId/*',
        element: (
          <ProjectProvider>
            <DraftSessionProvider>
              <Link to="/organization">前往组织治理</Link>
              {kind === 'suggestion' ? <AIAssistantPage /> : <AIChangeSetsPage />}
            </DraftSessionProvider>
          </ProjectProvider>
        ),
      },
      { path: '/organization', element: <OrganizationGovernancePage /> },
    ],
    { initialEntries: [path] },
  )
  render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App>
        <QueryClientProvider client={client}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </App>
    </ConfigProvider>,
  )
  return router
}

function boundaryReceipt(
  kind: 'suggestion' | 'change-set',
  type: 'workflow' | 'test_case',
  suggestion: AISuggestion,
  item: AIChangeItem,
): AISuggestion | AIChangeItem {
  return kind === 'suggestion'
    ? {
        ...suggestion,
        review_status: 'accepted',
        accepted_resource_type: type,
        accepted_resource_id: 'boundary-result',
      }
    : {
        ...item,
        review_status: 'accepted',
        materialized_resource_type: type,
        materialized_resource_id: 'boundary-result',
      }
}
