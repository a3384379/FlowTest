import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import WorkflowsPage from './WorkflowsPage'
import {
  apiDefinition,
  environment,
  project,
  workflow,
  workflowExecutionDetail,
  workflowVersion,
} from '../test/fixtures'
import { server } from '../test/server'

describe('WorkflowsPage', () => {
  it('publishes and runs an immutable workflow version', async () => {
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/environments`, () =>
        HttpResponse.json([environment]),
      ),
      http.get(`/api/v1/projects/${project.id}/apis`, () =>
        HttpResponse.json({ items: [apiDefinition], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/workflows`, () =>
        HttpResponse.json({ items: [workflow], total: 1, page: 1, page_size: 100 }),
      ),
      http.get(`/api/v1/projects/${project.id}/workflow-executions`, () =>
        HttpResponse.json({
          items: [workflowExecutionDetail.execution],
          total: 1,
          page: 1,
          page_size: 20,
        }),
      ),
      http.post(`/api/v1/projects/${project.id}/workflows/${workflow.id}/versions`, () =>
        HttpResponse.json(workflowVersion),
      ),
      http.patch(`/api/v1/projects/${project.id}/workflows/${workflow.id}`, async ({ request }) => {
        const payload = (await request.json()) as { expected_revision: number }
        expect(payload.expected_revision).toBe(1)
        return HttpResponse.json({ ...workflow, draft_revision: 2 })
      }),
      http.post(
        `/api/v1/projects/${project.id}/workflows/${workflow.id}/executions`,
        async ({ request }) => {
          expect(await request.json()).toEqual({ environment_id: environment.id })
          return HttpResponse.json(workflowExecutionDetail)
        },
      ),
    )
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByText(workflow.name)).toBeVisible()
    expect(screen.getByText('已发布 v1')).toBeVisible()
    const editor = screen.getByLabelText('工作流 JSON')
    fireEvent.change(editor, { target: { value: JSON.stringify(workflow.draft_definition) } })
    await browser.click(screen.getByRole('button', { name: /保存草稿/ }))
    expect(await screen.findByText('草稿已保存')).toBeInTheDocument()

    await browser.click(screen.getByRole('button', { name: /发布版本/ }))
    expect(await screen.findByText('工作流 v2 已发布')).toBeInTheDocument()

    await browser.click(screen.getByRole('button', { name: /运\s*行/ }))
    expect(await screen.findByText('工作流执行通过')).toBeInTheDocument()
    expect(screen.getByText('查询用户')).toBeVisible()
    expect(screen.getByText('2')).toBeVisible()
  })
})

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <WorkflowsPage />
      </QueryClientProvider>
    </AntdApp>,
  )
}
