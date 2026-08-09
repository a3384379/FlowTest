import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import DashboardPage from './DashboardPage'
import { project } from '../test/fixtures'
import ProjectTestProvider from '../test/ProjectTestProvider'
import { server } from '../test/server'

describe('DashboardPage', () => {
  it('renders API and workflow activity with known and fallback statuses', async () => {
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get('/api/v1/dashboard/summary', () =>
        HttpResponse.json({
          project_count: 1,
          api_count: 3,
          workflow_count: 2,
          today_total: 2,
          today_passed: 1,
          today_failed: 1,
          pass_rate: 50,
          trend: [],
        }),
      ),
      http.get('/api/v1/dashboard/recent-executions', () =>
        HttpResponse.json({
          items: [
            recentExecution('api-run', 'api', 'passed', '查询用户'),
            recentExecution('workflow-run', 'workflow', 'waiting', '订单流程'),
          ],
          total: 2,
          page: 1,
          page_size: 10,
        }),
      ),
    )
    renderDashboard()

    expect(await screen.findByText('查询用户')).toBeVisible()
    expect(screen.getByText('接口')).toBeVisible()
    expect(screen.getAllByText('工作流').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('通过')).toBeVisible()
    expect(screen.getByText('waiting')).toBeVisible()
    expect(screen.getByText(`当前查看：${project.name}`)).toBeVisible()
  })

  it('reports a recent-execution loading failure without hiding the empty state', async () => {
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get('/api/v1/dashboard/summary', () =>
        HttpResponse.json({
          project_count: 1,
          api_count: 0,
          workflow_count: 0,
          today_total: 0,
          today_passed: 0,
          today_failed: 0,
          pass_rate: 0,
          trend: [],
        }),
      ),
      http.get('/api/v1/dashboard/recent-executions', () =>
        HttpResponse.json({ error: { message: '最近执行暂不可用' } }, { status: 503 }),
      ),
    )
    renderDashboard()

    expect(await screen.findByText('工作台加载失败')).toBeVisible()
    expect(screen.getByText('最近执行暂不可用')).toBeVisible()
    expect(screen.getByText('暂无执行记录')).toBeVisible()
  })

  it('reports a summary loading failure while recent executions stay available', async () => {
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
      ),
      http.get('/api/v1/dashboard/summary', () =>
        HttpResponse.json({ error: { message: '统计暂不可用' } }, { status: 503 }),
      ),
      http.get('/api/v1/dashboard/recent-executions', () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 10 }),
      ),
    )
    renderDashboard()

    expect(await screen.findByText('统计暂不可用')).toBeVisible()
    expect(screen.getByText('暂无执行记录')).toBeVisible()
  })
})

function recentExecution(id: string, kind: 'api' | 'workflow', status: string, name: string) {
  return {
    id,
    project_id: project.id,
    project_name: project.name,
    kind,
    target_id: `${id}-target`,
    target_name: name,
    status,
    started_at: '2026-08-09T08:00:00Z',
    completed_at: null,
    duration_ms: null,
  }
}

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>
        <ProjectTestProvider section="dashboard">
          <DashboardPage />
        </ProjectTestProvider>
      </QueryClientProvider>
    </AntdApp>,
  )
}
