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
  workflowRunningExecution,
  workflowVersion,
} from '../test/fixtures'
import { server } from '../test/server'
import ProjectTestProvider from '../test/ProjectTestProvider'

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
      http.get(`/api/v1/projects/${project.id}/files`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
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
        const payload = (await request.json()) as {
          expected_revision: number
          definition: { nodes: Array<{ id: string; name: string }> }
        }
        expect(payload.expected_revision).toBe(1)
        expect(payload.definition.nodes.find((node) => node.id === 'api')?.name).toBe('用户查询')
        return HttpResponse.json({ ...workflow, draft_revision: 2 })
      }),
      http.post(
        `/api/v1/projects/${project.id}/workflows/${workflow.id}/executions`,
        async ({ request }) => {
          expect(await request.json()).toEqual({ environment_id: environment.id })
          return HttpResponse.json(workflowRunningExecution, { status: 202 })
        },
      ),
      http.get(
        `/api/v1/projects/${project.id}/workflow-executions/${workflowRunningExecution.id}`,
        () => HttpResponse.json(workflowExecutionDetail),
      ),
    )
    renderPage()
    const browser = userEvent.setup()

    expect(await screen.findByText(workflow.name)).toBeVisible()
    expect(screen.getByText('已发布 v1')).toBeVisible()
    expect(screen.getByLabelText('工作流画布')).toBeVisible()
    fireEvent.click(screen.getAllByText('开始')[0])
    expect(screen.getByRole('button', { name: /删除节点/ })).toBeDisabled()
    await browser.click(screen.getByRole('button', { name: /添加接口节点/ }))
    fireEvent.click(await screen.findByText('接口请求 2'))
    await browser.click(screen.getByRole('button', { name: /删除节点/ }))
    fireEvent.click(screen.getByText('查询用户'))
    const nameInput = screen.getByDisplayValue('查询用户')
    await browser.clear(nameInput)
    await browser.type(nameInput, '用户查询')
    await browser.click(screen.getByRole('button', { name: /保存草稿/ }))
    expect(await screen.findByText('草稿已保存')).toBeInTheDocument()

    await browser.click(screen.getByRole('button', { name: /发布版本/ }))
    expect(await screen.findByText('工作流 v2 已发布')).toBeInTheDocument()

    await browser.click(screen.getByRole('button', { name: /运\s*行/ }))
    expect(await screen.findByText('工作流已开始运行')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /保存草稿/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /发布版本/ })).toBeDisabled()
    expect(await screen.findByText('工作流执行通过')).toBeInTheDocument()
    expect(screen.getAllByText('查询用户').length).toBeGreaterThan(0)
    expect(screen.getByText('2')).toBeVisible()
  }, 15_000)
})

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <ProjectTestProvider section="workflows">
          <WorkflowsPage />
        </ProjectTestProvider>
      </QueryClientProvider>
    </AntdApp>,
  )
}
