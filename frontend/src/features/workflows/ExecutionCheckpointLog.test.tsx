import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { project, workflowExecutionDetail } from '../../test/fixtures'
import { server } from '../../test/server'
import ExecutionCheckpointLog from './ExecutionCheckpointLog'

describe('ExecutionCheckpointLog', () => {
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
    expect(await within(dialog).findByText('实例输出')).toBeInTheDocument()
    expect(within(dialog).getByLabelText('实例输出')).toHaveTextContent(/"id": 7/)
    expect(detailReads).toBe(1)
  })
})
