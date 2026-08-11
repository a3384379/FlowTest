import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import type { AIJob, AISuggestion } from '../features/ai/ai-service'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { project, user } from '../test/fixtures'
import { server } from '../test/server'
import AIAssistantPage from './AIAssistantPage'

const job: AIJob = {
  id: '00000000-0000-4000-8000-000000000201',
  project_id: project.id,
  job_type: 'assertion_suggestions',
  status: 'completed',
  input_sha256: 'abc1234567890def',
  prompt_template_version: 's21-v1',
  model_name: 'flowtest-eval-model',
  sample_included: false,
  token_usage: { total_tokens: 30 },
  error_code: null,
  error_message: null,
  created_by_id: user.id,
  created_at: '2026-08-12T01:00:00Z',
  updated_at: '2026-08-12T01:00:02Z',
}

const suggestion: AISuggestion = {
  id: '00000000-0000-4000-8000-000000000202',
  job_id: job.id,
  position: 0,
  suggestion_type: 'assertion',
  title: '校验成功状态码',
  content: { expression: 'status_code', operator: 'equals', expected: 200 },
  review_status: 'pending',
  review_note: '',
  accepted_resource_type: null,
  accepted_resource_id: null,
  created_at: '2026-08-12T01:00:01Z',
  updated_at: '2026-08-12T01:00:01Z',
}

describe('AIAssistantPage', () => {
  it('shows a safe disabled state without blocking other product areas', async () => {
    server.use(
      http.get('/api/v1/ai/status', () =>
        HttpResponse.json({ enabled: false, model: null, sample_sharing_enabled: false }),
      ),
      http.get('/api/v1/ai/jobs', () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 50 }),
      ),
    )
    renderPage()

    expect(await screen.findByText('AI 助手当前关闭')).toBeVisible()
    expect(screen.getByText(/不会影响接口、Workflow 或计划运行/)).toBeVisible()
    expect(screen.getByRole('button', { name: /新建 AI 任务/ })).toBeDisabled()
    expect(screen.getByRole('switch', { name: '允许提交脱敏样本' })).toBeDisabled()
  })

  it('requires explicit human review and sends edited content only after acceptance', async () => {
    let reviewed: unknown
    let sharingEnabled = false
    server.use(
      http.get('/api/v1/ai/status', () =>
        HttpResponse.json({
          enabled: true,
          model: 'flowtest-eval-model',
          sample_sharing_enabled: sharingEnabled,
        }),
      ),
      http.put(`/api/v1/ai/projects/${project.id}/settings`, async ({ request }) => {
        const input = (await request.json()) as { sample_sharing_enabled: boolean }
        sharingEnabled = input.sample_sharing_enabled
        return HttpResponse.json({
          enabled: true,
          model: 'flowtest-eval-model',
          sample_sharing_enabled: sharingEnabled,
        })
      }),
      http.get('/api/v1/ai/jobs', () =>
        HttpResponse.json({ items: [job], total: 1, page: 1, page_size: 50 }),
      ),
      http.get(`/api/v1/ai/jobs/${job.id}/suggestions`, () => HttpResponse.json([suggestion])),
      http.post(`/api/v1/ai/suggestions/${suggestion.id}/accept`, async ({ request }) => {
        reviewed = await request.json()
        return HttpResponse.json({
          ...suggestion,
          review_status: 'accepted',
          review_note: '人工确认',
        })
      }),
    )
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByText('校验成功状态码')).toBeVisible()
    expect(screen.getByText('模型：flowtest-eval-model')).toBeVisible()
    await browser.click(screen.getByRole('switch', { name: '允许提交脱敏样本' }))
    await waitFor(() => expect(sharingEnabled).toBe(true))

    await browser.click(screen.getByRole('button', { name: /接受/ }))
    expect(screen.getByRole('dialog', { name: '接受并生成草稿' })).toBeInTheDocument()
    const content = screen.getByLabelText('建议内容')
    fireEvent.change(content, {
      target: {
        value: JSON.stringify({ expression: 'status_code', operator: 'equals', expected: 201 }),
      },
    })
    await browser.type(screen.getByLabelText('审核备注'), '人工确认')
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    await waitFor(() =>
      expect(reviewed).toEqual({
        content: { expression: 'status_code', operator: 'equals', expected: 201 },
        note: '人工确认',
      }),
    )
  })

  it('supports explicit rejection and blocks malformed acceptance edits', async () => {
    let rejected: unknown
    let acceptRequests = 0
    const failedJob = { ...job, id: `${job.id.slice(0, -1)}3`, status: 'failed' as const }
    server.use(
      http.get('/api/v1/ai/status', () =>
        HttpResponse.json({
          enabled: true,
          model: 'flowtest-eval-model',
          sample_sharing_enabled: false,
        }),
      ),
      http.get('/api/v1/ai/jobs', () =>
        HttpResponse.json({ items: [failedJob], total: 1, page: 1, page_size: 50 }),
      ),
      http.get(`/api/v1/ai/jobs/${failedJob.id}/suggestions`, () =>
        HttpResponse.json([{ ...suggestion, job_id: failedJob.id }]),
      ),
      http.post(`/api/v1/ai/suggestions/${suggestion.id}/reject`, async ({ request }) => {
        rejected = await request.json()
        return HttpResponse.json({ ...suggestion, review_status: 'rejected' })
      }),
      http.post(`/api/v1/ai/suggestions/${suggestion.id}/accept`, () => {
        acceptRequests += 1
        return HttpResponse.json({ ...suggestion, review_status: 'accepted' })
      }),
    )
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByText('校验成功状态码')).toBeVisible()
    expect(screen.getByText('failed')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: /拒绝/ }))
    expect(screen.getByRole('dialog', { name: '拒绝建议' })).toBeInTheDocument()
    await browser.type(screen.getByLabelText('审核备注'), '人工拒绝')
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    await waitFor(() => expect(rejected).toEqual({ note: '人工拒绝' }))

    await browser.click(screen.getByRole('button', { name: /接受/ }))
    fireEvent.change(screen.getByLabelText('建议内容'), { target: { value: '[]' } })
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    expect(await screen.findByText('建议内容必须是 JSON 对象')).toBeInTheDocument()
    expect(acceptRequests).toBe(0)
  })

  it('creates a queued AI job with an explicitly enabled sample', async () => {
    let created: unknown
    const queuedJob = { ...job, status: 'pending' as const, job_type: 'schema_cases' as const }
    server.use(
      http.get('/api/v1/ai/status', () =>
        HttpResponse.json({
          enabled: true,
          model: 'flowtest-eval-model',
          sample_sharing_enabled: true,
        }),
      ),
      http.get('/api/v1/ai/jobs', () =>
        HttpResponse.json({ items: [queuedJob], total: 1, page: 1, page_size: 50 }),
      ),
      http.get(`/api/v1/ai/jobs/${queuedJob.id}/suggestions`, () => HttpResponse.json([])),
      http.post('/api/v1/ai/jobs', async ({ request }) => {
        created = await request.json()
        return HttpResponse.json(queuedJob, { status: 202 })
      }),
    )
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByText('Schema 用例')).toBeVisible()
    expect(screen.getByText('pending')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: /新建 AI 任务/ }))
    expect(screen.getByRole('dialog', { name: '新建 AI 建议任务' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('脱敏样本（Owner 显式开启）'), {
      target: { value: '{"status":500}' },
    })
    await browser.click(screen.getByRole('button', { name: 'OK' }))
    await waitFor(() =>
      expect(created).toEqual({
        project_id: project.id,
        job_type: 'schema_cases',
        schema_document: { openapi: '3.1.0', paths: {} },
        metadata: {},
        sample: { status: 500 },
      }),
    )
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
        <ProjectTestProvider section="ai">
          <AIAssistantPage />
        </ProjectTestProvider>
      </QueryClientProvider>
    </AntdApp>,
  )
}
