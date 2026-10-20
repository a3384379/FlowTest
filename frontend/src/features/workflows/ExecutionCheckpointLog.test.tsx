import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { App as AntdApp, ConfigProvider } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

import { project, workflowExecutionDetail } from '../../test/fixtures'
import { server } from '../../test/server'
import ExecutionCheckpointLog from './ExecutionCheckpointLog'

describe('ExecutionCheckpointLog', () => {
  it('loads same-run sources for a root checkpoint and exposes a retry when the source read fails', async () => {
    const executionId = workflowExecutionDetail.execution.id
    const root = `/api/v1/projects/${project.id}/workflow-executions/${executionId}`
    const entry = {
      id: 'root-assert-checkpoint',
      execution_id: executionId,
      node_id: 'assert',
      node_type: 'assert',
      node_name: '顶层断言',
      status: 'failed',
      phase: 'main',
      attempt: 1,
      started_at: '2026-09-27T00:00:00Z',
      finished_at: '2026-09-27T00:00:01Z',
    }
    let reads = 0
    server.use(
      http.get(root + '/checkpoint-log', () =>
        HttpResponse.json({ items: [entry], total: 1, page: 1, page_size: 20 }),
      ),
      http.get(root + '/checkpoint-log/' + entry.id, () =>
        HttpResponse.json({
          ...entry,
          output: {
            passed: false,
            actual: 200,
            expected: 201,
            operator: 'equals',
            source_node_id: 'api',
            expression: 'status_code',
          },
          result: {},
        }),
      ),
      http.get(root, () => {
        reads++
        return reads === 1
          ? HttpResponse.json(
              {
                error: {
                  code: 'TEMPORARY_ERROR',
                  message: '来源读取暂时失败',
                  trace_id: 'checkpoint-source-trace',
                },
              },
              { status: 503 },
            )
          : HttpResponse.json(workflowExecutionDetail)
      }),
    )
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <ConfigProvider theme={{ token: { motion: false } }}>
            <AntdApp>
              <ExecutionCheckpointLog
                projectId={project.id}
                executionId={executionId}
                running={false}
              />
            </AntdApp>
          </ConfigProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    fireEvent.click(await screen.findByRole('button', { name: '查看记录' }))
    const dialog = await screen.findByRole('dialog', { name: '执行记录详情' })
    await waitFor(() => expect(within(dialog).getByText('来源节点证据读取失败')).toBeVisible())
    expect(within(dialog).getByText(/checkpoint-source-trace/)).toBeVisible()
    expect(within(dialog).queryByText(/区域实例的来源轮次未解析/)).not.toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: '重试来源证据' }))
    const source = await within(dialog).findByRole('link', { name: /查询用户/ })
    expect(source).toHaveAttribute(
      'href',
      `/projects/${project.id}/reports?execution=${executionId}&node=api&attempt=2`,
    )
    expect(within(dialog).getByRole('region', { name: '检查点执行证据' })).toBeVisible()
    expect(reads).toBe(2)
  })
  it('requests the current node and checkpoint attempt from the server and can return to all execution records', async () => {
    const queries: URLSearchParams[] = []
    server.use(
      http.get(
        `/api/v1/projects/${project.id}/workflow-executions/${workflowExecutionDetail.execution.id}/checkpoint-log`,
        ({ request }) => {
          queries.push(new URL(request.url).searchParams)
          return HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 })
        },
      ),
    )
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <AntdApp>
          <ExecutionCheckpointLog
            projectId={project.id}
            executionId={workflowExecutionDetail.execution.id}
            nodeId="api"
            running={false}
          />
        </AntdApp>
      </QueryClientProvider>,
    )
    await waitFor(() => expect(queries.at(-1)?.get('node_id')).toBe('api'))
    fireEvent.change(screen.getByLabelText('检查点尝试筛选'), { target: { value: '2' } })
    await waitFor(() => expect(queries.at(-1)?.get('attempt')).toBe('2'))
    fireEvent.click(screen.getByText('全部执行'))
    await waitFor(() => expect(queries.at(-1)?.has('node_id')).toBe(false))
    expect(queries.at(-1)?.get('attempt')).toBe('2')
    expect(queries.at(-1)?.get('page')).toBe('1')
  })
  it('pages lightweight summaries and loads one full checkpoint on demand', async () => {
    const executionId = workflowExecutionDetail.execution.id
    const checkpointId = '00000000-0000-4000-8000-000000000090'
    const pages: number[] = []
    let detailReads = 0
    const entry = {
      id: checkpointId,
      execution_id: executionId,
      node_id: 'api',
      node_type: 'api',
      node_name: '查询用户',
      phase: 'main',
      attempt: 2,
      status: 'passed',
      started_at: '2026-09-27T00:00:00Z',
      finished_at: '2026-09-27T00:00:01Z',
    }
    server.use(
      http.get(
        `/api/v1/projects/${project.id}/workflow-executions/${executionId}/checkpoint-log`,
        ({ request }) => {
          const url = new URL(request.url)
          expect(url.searchParams.get('page_size')).toBe('20')
          const page = Number(url.searchParams.get('page'))
          pages.push(page)
          return HttpResponse.json({
            items: page === 2 ? [entry] : [{ ...entry, id: 'first-checkpoint', attempt: 1 }],
            total: 21,
            page,
            page_size: 20,
          })
        },
      ),
      http.get(
        `/api/v1/projects/${project.id}/workflow-executions/${executionId}/checkpoint-log/${checkpointId}`,
        () => {
          detailReads += 1
          return HttpResponse.json({ ...entry, output: { body: { id: 7 } }, result: {} })
        },
      ),
    )
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <AntdApp>
          <ExecutionCheckpointLog
            projectId={project.id}
            executionId={executionId}
            running={false}
          />
        </AntdApp>
      </QueryClientProvider>,
    )
    expect(await screen.findByText('查询用户')).toBeVisible()
    expect(detailReads).toBe(0)
    fireEvent.click(screen.getByTitle('2'))
    await waitFor(() => expect(pages).toEqual([1, 2]))
    fireEvent.click(screen.getByRole('button', { name: '查看记录' }))
    const dialog = await screen.findByRole('dialog', { name: '执行记录详情' })
    expect(await within(dialog).findByText('检查点输出')).toBeInTheDocument()
    expect(within(dialog).getByLabelText('检查点输出')).toHaveTextContent(/"id": 7/)
    expect(detailReads).toBe(1)
  })
})
