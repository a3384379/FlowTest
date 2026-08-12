import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import type { AIChangeItem, AIChangeSetDetail } from '../features/ai/ai-change-set-service'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { project, user } from '../test/fixtures'
import { server } from '../test/server'
import AIChangeSetsPage from './AIChangeSetsPage'

const changeSetId = '00000000-0000-4000-8000-000000000201'
const riskId = '00000000-0000-4000-8000-000000000202'
const impactId = '00000000-0000-4000-8000-000000000203'

const item: AIChangeItem = {
  id: '00000000-0000-4000-8000-000000000204',
  position: 0,
  item_type: 'workflow',
  action: 'create',
  title: '新增异常流程',
  target_resource_id: null,
  target_snapshot_sha256: null,
  proposed_content: { name: '异常流程', definition: { schema_version: '1.0' } },
  review_status: 'pending',
  review_note: '',
  reviewed_by_id: null,
  reviewed_at: null,
  materialized_resource_type: null,
  materialized_resource_id: null,
  created_at: '2026-08-13T01:00:00Z',
  updated_at: '2026-08-13T01:00:00Z',
}

const detail: AIChangeSetDetail = {
  id: changeSetId,
  project_id: project.id,
  impact_run_id: impactId,
  release_risk_id: riskId,
  ai_job_id: '00000000-0000-4000-8000-000000000205',
  title: '开票变更集',
  status: 'draft',
  source_fingerprint: 'a'.repeat(64),
  created_by_id: user.id,
  created_at: '2026-08-13T01:00:00Z',
  updated_at: '2026-08-13T01:00:00Z',
  source_snapshot: { metadata: { review_policy: { draft_only: true } } },
  items: [item],
}

describe('AIChangeSetsPage', () => {
  it('shows the draft-only boundary and accepts an edited item', async () => {
    let accepted: Record<string, unknown> | null = null
    handlers(detail)
    server.use(
      http.post(
        `/api/v1/ai/change-sets/${changeSetId}/items/${item.id}/accept`,
        async ({ request }) => {
          accepted = (await request.json()) as Record<string, unknown>
          return HttpResponse.json({
            ...item,
            review_status: 'accepted',
            materialized_resource_type: 'workflow',
            materialized_resource_id: '00000000-0000-4000-8000-000000000206',
          })
        },
      ),
    )
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByRole('heading', { name: 'AI 测试资产变更审核' })).toBeVisible()
    expect(screen.getByText(/AI 只生成草稿/)).toBeVisible()
    expect(await screen.findByText('新增异常流程')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: '审核并接受' }))
    const dialog = await screen.findByRole('dialog', { name: '编辑并接受变更项' })
    await waitFor(() => expect(within(dialog).getByText(/接受后只创建或更新草稿/)).toBeVisible())
    fireEvent.change(within(dialog).getByLabelText('变更内容 JSON'), {
      target: { value: '{"name":"人工编辑流程"}' },
    })
    await browser.type(within(dialog).getByLabelText('审核备注'), '已核对变更')
    await browser.click(within(dialog).getByRole('button', { name: 'OK' }))
    await waitFor(() =>
      expect(accepted).toEqual({ content: { name: '人工编辑流程' }, note: '已核对变更' }),
    )
  })

  it('blocks malformed review JSON and rejects without sending edited content', async () => {
    let rejected: Record<string, unknown> | null = null
    handlers(detail)
    server.use(
      http.post(
        `/api/v1/ai/change-sets/${changeSetId}/items/${item.id}/reject`,
        async ({ request }) => {
          rejected = (await request.json()) as Record<string, unknown>
          return HttpResponse.json({ ...item, review_status: 'rejected' })
        },
      ),
    )
    renderPage()
    const browser = userEvent.setup()
    await screen.findByText('新增异常流程')

    await browser.click(screen.getByRole('button', { name: '审核并接受' }))
    let dialog = await screen.findByRole('dialog', { name: '编辑并接受变更项' })
    fireEvent.change(within(dialog).getByLabelText('变更内容 JSON'), {
      target: { value: '[]' },
    })
    await browser.click(within(dialog).getByRole('button', { name: 'OK' }))
    await waitFor(() => expect(within(dialog).getByText('内容必须是 JSON 对象')).toBeVisible())
    await browser.click(within(dialog).getByRole('button', { name: 'Cancel' }))

    await browser.click(screen.getByRole('button', { name: '拒绝' }))
    dialog = await screen.findByRole('dialog', { name: '拒绝变更项' })
    await browser.type(within(dialog).getByLabelText('审核备注'), '不适合当前版本')
    await browser.click(within(dialog).getByRole('button', { name: 'OK' }))
    await waitFor(() => expect(rejected).toEqual({ note: '不适合当前版本' }))
  })

  it('binds risk and impact evidence before generating a change set', async () => {
    let created: Record<string, unknown> | null = null
    handlers({ ...detail, status: 'generating', items: [] })
    server.use(
      http.post('/api/v1/ai/change-sets', async ({ request }) => {
        created = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...detail, status: 'generating' }, { status: 202 })
      }),
    )
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByText('AI 正在生成结构化变更项，请稍候…')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: /生成 Draft Change Set/ }))
    const dialog = await screen.findByRole('dialog', { name: '生成 Draft Change Set' })
    await browser.type(within(dialog).getByLabelText('变更集名称'), '支付变更集')
    await browser.click(within(dialog).getByLabelText('发布风险证据'))
    await browser.click(await screen.findByText('候选风险 · 风险 42'))
    expect(within(dialog).getByText('风险与影响证据已绑定，提交后不可替换。')).toBeVisible()
    await browser.click(within(dialog).getByRole('button', { name: 'OK' }))
    await waitFor(() =>
      expect(created).toEqual({
        project_id: project.id,
        impact_run_id: impactId,
        release_risk_id: riskId,
        title: '支付变更集',
      }),
    )
  })

  it('renders failed and reviewed states without offering another review', async () => {
    handlers({ ...detail, status: 'failed', items: [] })
    const rendered = renderPage()
    expect(await screen.findByText('AI Change Set 生成失败，请查看 AI 任务审计。')).toBeVisible()
    rendered.unmount()

    handlers({
      ...detail,
      status: 'accepted',
      items: [{ ...item, review_status: 'accepted' }],
    })
    renderPage()
    expect(await screen.findByText('已接受')).toBeVisible()
    expect(screen.queryByRole('button', { name: '审核并接受' })).not.toBeInTheDocument()
  })
})

function handlers(value: AIChangeSetDetail) {
  server.use(
    http.get('/api/v1/ai/change-sets', () =>
      HttpResponse.json({ items: [value], total: 1, page: 1, page_size: 100 }),
    ),
    http.get(`/api/v1/ai/change-sets/${changeSetId}`, () => HttpResponse.json(value)),
    http.get(`/api/v1/projects/${project.id}/impact/runs`, () =>
      HttpResponse.json({
        items: [
          {
            id: impactId,
            project_id: project.id,
            title: '开票影响',
            source_ref: 'feature/invoice',
            status: 'completed',
            source_fingerprint: 'b'.repeat(64),
            source_summary: {},
            change_count: 2,
            summary: {},
            created_by_id: user.id,
            created_at: '2026-08-13T01:00:00Z',
          },
        ],
        total: 1,
        page: 1,
        page_size: 20,
      }),
    ),
    http.get(`/api/v1/projects/${project.id}/release-risks`, () =>
      HttpResponse.json({
        items: [
          {
            id: riskId,
            project_id: project.id,
            impact_run_id: impactId,
            title: '候选风险',
            algorithm_version: 'release_risk_v1',
            window_days: 30,
            score: 42,
            quality_score: 58,
            risk_level: 'medium',
            fingerprint: 'c'.repeat(64),
            created_by_id: user.id,
            created_at: '2026-08-13T01:00:00Z',
          },
        ],
        total: 1,
        page: 1,
        page_size: 100,
      }),
    ),
  )
}

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
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <ProjectTestProvider section="ai-changes">
            <AIChangeSetsPage />
          </ProjectTestProvider>
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>,
  )
}
