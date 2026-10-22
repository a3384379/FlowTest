import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { useLocation, useNavigate } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { CreatedNotificationWebhook, ReportTrend } from '../lib/api'
import { project, user } from '../test/fixtures'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { server } from '../test/server'
import ReportsPage from './ReportsPage'

const secondProject = { ...project, id: '00000000-0000-4000-8000-000000000998', name: '报告项目B' }
const created: CreatedNotificationWebhook = {
  id: '00000000-0000-4000-8000-000000000997',
  project_id: project.id,
  name: '合成通知A',
  url: 'https://notify.example.test/a',
  events: ['workflow.completed', 'test_plan.completed'],
  enabled: true,
  created_by_id: user.id,
  created_at: '2026-10-22T00:00:00Z',
  updated_at: '2026-10-22T00:00:00Z',
  secret: 'synthetic-project-A-notification-secret',
}
const trend: ReportTrend = {
  summary: {
    started_from: '2026-10-20T00:00:00Z',
    started_until: '2026-10-23T00:00:00Z',
    total: 0,
    passed: 0,
    failed: 0,
    cancelled: 0,
    pending: 0,
    completed: 0,
    pass_rate: null,
  },
  points: [],
  failures: [],
}

function installReads() {
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project, secondProject], total: 2, page: 1, page_size: 100 }),
    ),
    http.get('/api/v1/projects/:projectId', ({ params }) =>
      HttpResponse.json(params.projectId === secondProject.id ? secondProject : project),
    ),
    http.get('/api/v1/projects/:projectId/permissions', ({ params }) =>
      HttpResponse.json({
        effective_role: params.projectId === secondProject.id ? 'viewer' : 'owner',
        capabilities: params.projectId === secondProject.id ? ['read'] : ['read', 'manage_members'],
        matrix: {},
      }),
    ),
    http.get('/api/v1/projects/:projectId/reports/executions', () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 50 }),
    ),
    http.get('/api/v1/projects/:projectId/reports/trends', () => HttpResponse.json(trend)),
    http.get('/api/v1/projects/:projectId/notification-webhooks', () => HttpResponse.json([])),
    http.get('/api/v1/projects/:projectId/notification-deliveries', () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
    ),
  )
}

function renderReports() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  let navigate!: ReturnType<typeof useNavigate>
  function Navigation() {
    navigate = useNavigate()
    return <output aria-label="报告地址">{useLocation().pathname}</output>
  }
  const view = render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App>
        <QueryClientProvider client={client}>
          <ProjectTestProvider section="reports">
            <ReportsPage />
            <Navigation />
          </ProjectTestProvider>
        </QueryClientProvider>
      </App>
    </ConfigProvider>,
  )
  return {
    ...view,
    client,
    navigate: async (projectId: string) => {
      await act(async () => navigate(`/projects/${projectId}/reports`))
    },
  }
}

async function createFromForm(browser: ReturnType<typeof userEvent.setup>) {
  const open = await screen.findByRole('button', { name: /配置通知/ })
  await waitFor(() => expect(open).toBeEnabled())
  await browser.click(open)
  const dialog = screen.getByText('配置签名通知 Webhook').closest<HTMLElement>('[role="dialog"]')!
  expect(dialog).toHaveRole('dialog')
  await waitFor(() => expect(dialog).toBeVisible())
  await browser.click(within(dialog).getByLabelText('名称'))
  await browser.paste(created.name)
  await browser.click(within(dialog).getByLabelText('HTTPS 地址'))
  await browser.paste(created.url)
  await browser.click(within(dialog).getByRole('button', { name: 'OK' }))
  return dialog
}

function pendingResponse() {
  let release!: () => void
  let notify!: () => void
  const pending = new Promise<void>((resolve) => {
    release = resolve
  })
  const started = new Promise<void>((resolve) => {
    notify = resolve
  })
  return { pending, started, release: () => release(), notify: () => notify() }
}

describe('report notification project identity', () => {
  it.each(['success', 'failure'] as const)(
    'ignores an earlier project notification %s after entering a viewer project',
    async (result) => {
      installReads()
      const response = pendingResponse()
      const payloads: unknown[] = []
      server.use(
        http.post(`/api/v1/projects/${project.id}/notification-webhooks`, async ({ request }) => {
          payloads.push(await request.json())
          response.notify()
          await response.pending
          return result === 'success'
            ? HttpResponse.json(created, { status: 201 })
            : HttpResponse.json(
                {
                  error: {
                    code: 'NOTIFY_UNAVAILABLE',
                    message: '原项目通知暂不可用',
                    trace_id: 'synthetic-notify-A',
                  },
                },
                { status: 503 },
              )
        }),
      )
      const view = renderReports()
      try {
        await createFromForm(userEvent.setup())
        await response.started
        await view.navigate(secondProject.id)
        await waitFor(() =>
          expect(screen.getByLabelText('报告地址')).toHaveTextContent(
            `/projects/${secondProject.id}/reports`,
          ),
        )
        await waitFor(() => expect(screen.getByRole('button', { name: /配置通知/ })).toBeDisabled())
        await act(async () => response.release())
        // Wait for the old mutation to settle, rather than only checking the immediate route render.
        await waitFor(() => expect(view.client.isMutating()).toBe(0))
        expect(payloads).toEqual([{ name: created.name, url: created.url, events: created.events }])
        expect(screen.queryByText(created.secret)).not.toBeInTheDocument()
        expect(screen.queryByText('通知 Webhook 已创建')).not.toBeInTheDocument()
        expect(screen.queryByText(/原项目通知暂不可用/)).not.toBeInTheDocument()
        if (result === 'success') {
          expect(
            view.client.getQueryState(['notification-webhooks', project.id])?.isInvalidated,
          ).toBe(true)
        }
        expect(
          view.client.getQueryState(['notification-webhooks', secondProject.id])?.isInvalidated,
        ).toBe(false)
      } finally {
        response.release()
      }
    },
  )

  it('clears an already revealed secret when the report project changes and does not restore it on return', async () => {
    installReads()
    let writes = 0
    server.use(
      http.post(`/api/v1/projects/${project.id}/notification-webhooks`, () => {
        writes += 1
        return HttpResponse.json(created, { status: 201 })
      }),
    )
    const view = renderReports()
    await createFromForm(userEvent.setup())
    await waitFor(() => expect(screen.getByText(created.secret)).toBeVisible())
    await view.navigate(secondProject.id)
    await waitFor(() => expect(screen.getByRole('button', { name: /配置通知/ })).toBeDisabled())
    expect(screen.queryByText(created.secret)).not.toBeInTheDocument()
    await view.navigate(project.id)
    await waitFor(() => expect(screen.getByRole('button', { name: /配置通知/ })).toBeEnabled())
    expect(screen.queryByText(created.secret)).not.toBeInTheDocument()
    expect(writes).toBe(1)
  })

  it('locks the submitted form, retains a failed submission, and issues only an explicit retry', async () => {
    installReads()
    const response = pendingResponse()
    const payloads: unknown[] = []
    server.use(
      http.post(`/api/v1/projects/${project.id}/notification-webhooks`, async ({ request }) => {
        payloads.push(await request.json())
        if (payloads.length === 1) {
          response.notify()
          await response.pending
          return HttpResponse.json(
            {
              error: {
                code: 'NOTIFY_UNAVAILABLE',
                message: '通知暂不可用',
                trace_id: 'synthetic-notify-retry',
              },
            },
            { status: 503 },
          )
        }
        return HttpResponse.json(created, { status: 201 })
      }),
    )
    renderReports()
    const browser = userEvent.setup()
    try {
      const dialog = await createFromForm(browser)
      await response.started
      const name = within(dialog).getByLabelText('名称')
      expect(name).toBeDisabled()
      expect(within(dialog).getByLabelText('HTTPS 地址')).toBeDisabled()
      await browser.type(name, '-unsent')
      expect(name).toHaveValue(created.name)
      await act(async () => response.release())
      expect(await screen.findByText(/通知暂不可用/)).toBeVisible()
      await waitFor(() => expect(name).toBeEnabled())
      expect(name).toHaveValue(created.name)
      expect(within(dialog).getByLabelText('HTTPS 地址')).toHaveValue(created.url)
      expect(payloads).toHaveLength(1)
      await browser.click(within(dialog).getByRole('button', { name: 'OK' }))
      await waitFor(() => expect(screen.getByText(created.secret)).toBeVisible())
      expect(payloads).toEqual(
        Array.from({ length: 2 }, () => ({
          name: created.name,
          url: created.url,
          events: created.events,
        })),
      )
    } finally {
      response.release()
    }
  })
})
