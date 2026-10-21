import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { beforeEach, expect, it } from 'vitest'

import type { AIChangeItem, AIChangeSetDetail } from '../features/ai/ai-change-set-service'
import ProjectProvider from '../features/projects/ProjectProvider'
import { project, user } from '../test/fixtures'
import { server } from '../test/server'
import AIChangeSetsPage from './AIChangeSetsPage'

const first = changeSet('a', '00000000-0000-4000-8000-000000000281')
const second = changeSet('b', '00000000-0000-4000-8000-000000000282')
const path = `/projects/${project.id}/ai-changes`

beforeEach(() => {
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
    ),
    http.get('/api/v1/ai/status', () => HttpResponse.json({ enabled: true })),
    http.get('/api/v1/v3/features', () =>
      HttpResponse.json({ impact_engine: true, quality_intelligence: true }),
    ),
    http.get('/api/v1/ai/change-sets', () =>
      HttpResponse.json({ items: [first, second], total: 2, page: 1, page_size: 20 }),
    ),
    http.get('/api/v1/ai/change-sets/:id', ({ params }) =>
      HttpResponse.json(params.id === first.id ? first : second),
    ),
    http.get(`/api/v1/projects/${project.id}/impact/runs`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
    ),
    http.get(`/api/v1/projects/${project.id}/release-risks`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
    ),
  )
})

it('keeps a cancelled focus navigation and destroys the old review after discard is confirmed', async () => {
  let acceptedPath = ''
  server.use(
    http.post('/api/v1/ai/change-sets/:id/items/:itemId/accept', ({ params }) => {
      acceptedPath = `${params.id}/${params.itemId}`
      return HttpResponse.json({ ...first.items[0], review_status: 'accepted' })
    }),
  )
  const { router } = renderNavigationPage()
  await openSecondReview()
  fireEvent.change(screen.getByLabelText('审核备注'), { target: { value: 'B 的未保存审核' } })
  await act(async () => {
    await router.navigate(-1)
  })
  let guard = await navigationGuard()
  await userEvent.click(within(guard).getByRole('button', { name: '继续编辑' }))
  expect(router.state.location.search).toBe(`?focus=${second.id}`)
  expect(screen.getByLabelText('审核备注')).toHaveValue('B 的未保存审核')
  await act(async () => {
    await router.navigate(-1)
  })
  guard = await navigationGuard()
  await userEvent.click(within(guard).getByRole('button', { name: '放弃修改并离开' }))
  await waitFor(() => expect(router.state.location.search).toBe(`?focus=${first.id}`))
  await screen.findByText(first.items[0].title)
  expect(screen.queryByLabelText('审核备注')).not.toBeInTheDocument()
  expect(screen.queryByText('B 的未保存审核')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '审核并接受' }))
  const dialog = await screen.findByRole('dialog', { name: '编辑并接受变更项' })
  expect(within(dialog).getByLabelText('变更内容 JSON')).toHaveValue(
    JSON.stringify(first.items[0].proposed_content, null, 2),
  )
  expect(dialog).toHaveTextContent(first.impact_run_id)
  fireEvent.change(within(dialog).getByLabelText('审核备注'), { target: { value: 'A 的新审核' } })
  await act(async () => {
    await router.navigate(1)
  })
  guard = await navigationGuard()
  await userEvent.click(within(guard).getByRole('button', { name: '继续编辑' }))
  expect(router.state.location.search).toBe(`?focus=${first.id}`)
  expect(within(dialog).getByLabelText('审核备注')).toHaveValue('A 的新审核')
  await userEvent.click(within(dialog).getByRole('button', { name: 'OK' }))
  await waitFor(() => expect(acceptedPath).toBe(`${first.id}/${first.items[0].id}`))
})

it('keeps edits during a refresh failure of the same change set and after its retry succeeds', async () => {
  const { queryClient } = renderNavigationPage()
  await openSecondReview()
  fireEvent.change(screen.getByLabelText('审核备注'), { target: { value: '保留本项审核输入' } })
  let failed = true
  server.use(
    http.get(`/api/v1/ai/change-sets/${second.id}`, () =>
      failed
        ? HttpResponse.json(
            {
              error: {
                code: 'UNAVAILABLE',
                message: '本项详情读取失败',
                trace_id: 'same-focus-trace',
              },
            },
            { status: 503 },
          )
        : HttpResponse.json(second),
    ),
  )
  await act(async () => {
    await queryClient.invalidateQueries({ queryKey: ['ai-change-set', project.id, second.id] })
  })
  expect(await screen.findByText(/本项详情读取失败.*same-focus-trace/)).toBeInTheDocument()
  expect(screen.getByLabelText('审核备注')).toHaveValue('保留本项审核输入')
  failed = false
  await act(async () => {
    await queryClient.refetchQueries({ queryKey: ['ai-change-set', project.id, second.id] })
  })
  await waitFor(() =>
    expect(screen.queryByText(/本项详情读取失败.*same-focus-trace/)).not.toBeInTheDocument(),
  )
  expect(screen.getByLabelText('审核备注')).toHaveValue('保留本项审核输入')
  expect(screen.getByLabelText('变更内容 JSON')).toHaveValue(
    JSON.stringify(second.items[0].proposed_content, null, 2),
  )
})

it('does not reopen a previous review or announce its late receipt after focus changes', async () => {
  let finish: (() => void) | undefined
  let writes = 0
  server.use(
    http.post(
      `/api/v1/ai/change-sets/${second.id}/items/${second.items[0].id}/accept`,
      async () => {
        writes += 1
        await new Promise<void>((resolve) => {
          finish = resolve
        })
        return HttpResponse.json({
          ...second.items[0],
          review_status: 'accepted',
          materialized_resource_type: 'workflow',
          materialized_resource_id: 'old-result',
        })
      },
    ),
  )
  const { router } = renderNavigationPage()
  await openSecondReview()
  const oldDialog = screen.getByRole('dialog', { name: '编辑并接受变更项' })
  await userEvent.click(within(oldDialog).getByRole('button', { name: 'OK' }))
  await waitFor(() => expect(writes).toBe(1))
  await act(async () => {
    await router.navigate(-1)
  })
  const guard = await navigationGuard()
  await userEvent.click(within(guard).getByRole('button', { name: '放弃修改并离开' }))
  await screen.findByText(first.items[0].title)
  expect(screen.queryByLabelText('审核备注')).not.toBeInTheDocument()
  await act(async () => {
    finish?.()
  })
  await waitFor(() => expect(screen.getByRole('button', { name: '审核并接受' })).toBeEnabled())
  expect(screen.queryByText('变更项已接受并生成草稿')).not.toBeInTheDocument()
  expect(screen.queryByText('old-result')).not.toBeInTheDocument()
  expect(router.state.location.search).toBe(`?focus=${first.id}`)
  await userEvent.click(screen.getByRole('button', { name: '审核并接受' }))
  expect(screen.getByLabelText('审核备注')).toHaveValue('')
  expect(writes).toBe(1)
})

async function openSecondReview() {
  await screen.findByText(second.items[0].title)
  await userEvent.click(screen.getByRole('button', { name: '审核并接受' }))
  await screen.findByRole('dialog', { name: '编辑并接受变更项' })
}

async function navigationGuard(): Promise<HTMLElement> {
  const title = await screen.findByText('审核修改尚未保存', { selector: '.ant-modal-title' })
  return title.closest('.ant-modal') as HTMLElement
}

function renderNavigationPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const router = createMemoryRouter(
    [
      {
        path: '/projects/:projectId/ai-changes',
        element: (
          <ProjectProvider>
            <AIChangeSetsPage />
          </ProjectProvider>
        ),
      },
    ],
    {
      initialEntries: [`${path}?focus=${first.id}`, `${path}?focus=${second.id}`],
      initialIndex: 1,
    },
  )
  return {
    router,
    queryClient,
    ...render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <App>
          <QueryClientProvider client={queryClient}>
            <RouterProvider router={router} />
          </QueryClientProvider>
        </App>
      </ConfigProvider>,
    ),
  }
}

function changeSet(suffix: string, id: string): AIChangeSetDetail {
  const item: AIChangeItem = {
    id: `${id.slice(0, -1)}${suffix === 'a' ? '3' : '4'}`,
    position: 0,
    item_type: 'workflow',
    action: 'create',
    title: `建议 ${suffix}`,
    target_resource_id: null,
    target_snapshot_sha256: null,
    proposed_content: {
      name: `草稿 ${suffix}`,
      description: '',
      definition: { schema_version: '1.0' },
    },
    review_status: 'pending',
    review_note: '',
    reviewed_by_id: null,
    reviewed_at: null,
    materialized_resource_type: null,
    materialized_resource_id: null,
    created_at: '2026-10-22T00:00:00Z',
    updated_at: '2026-10-22T00:00:00Z',
  }
  return {
    id,
    project_id: project.id,
    impact_run_id: `impact-${suffix}`,
    release_risk_id: `risk-${suffix}`,
    ai_job_id: `job-${suffix}`,
    title: `变更集 ${suffix}`,
    status: 'draft',
    source_fingerprint: suffix.repeat(64),
    created_by_id: user.id,
    created_at: item.created_at,
    updated_at: item.updated_at,
    source_snapshot: {},
    review_baselines: [],
    items: [item],
  }
}
