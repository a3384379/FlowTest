import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { expect, it } from 'vitest'
import type { ReactNode } from 'react'
import { usePerformanceLab } from '../../features/performance/use-performance-lab'
import ProjectTestProvider from '../../test/ProjectTestProvider'
import { authenticateTestUser } from '../../test/auth'
import { project, user } from '../../test/fixtures'
import { server } from '../../test/server'

function harness(section: 'ai' | 'apis' | 'performance') {
  server.use(
    http.get('/api/v1/projects', () =>
      HttpResponse.json({ items: [project], total: 1, page: 1, page_size: 100 }),
    ),
  )
  authenticateTestUser(user)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  function wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <AntdApp>
          <ProjectTestProvider section={section}>{children}</ProjectTestProvider>
        </AntdApp>
      </QueryClientProvider>
    )
  }
  return { client, wrapper }
}

it.each(['passed', 'failed', 'cancelled'] as const)(
  'refreshes latest performance evidence on an older page until %s',
  async (terminalStatus) => {
    let completed = false
    const record = { id: 'latest-performance-run', status: 'queued', summary: {} }
    server.use(
      http.get(`/api/v1/projects/${project.id}/performance-scenarios`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
      ),
      http.get(`/api/v1/projects/${project.id}/performance-runs`, ({ request }) =>
        HttpResponse.json({
          items:
            Number(new URL(request.url).searchParams.get('page') ?? 1) === 2
              ? []
              : [
                  {
                    ...record,
                    status: completed ? terminalStatus : 'queued',
                    summary: completed ? { http_req_duration_p95_ms: 128 } : {},
                  },
                ],
          total: 1,
          page: 1,
          page_size: Number(new URL(request.url).searchParams.get('page_size') ?? 20),
        }),
      ),
    )
    const { wrapper } = harness('performance')
    const { result } = renderHook(() => usePerformanceLab(), { wrapper })
    await waitFor(() => expect(result.current.latestRun.data?.items[0].status).toBe('queued'))
    await waitFor(() => expect(result.current.runs.data?.items[0].status).toBe('queued'))
    act(() => result.current.setRunPage(2))
    await waitFor(() => expect(result.current.runPage).toBe(2))
    completed = true
    await waitFor(
      () => expect(result.current.latestRun.data?.items[0].status).toBe(terminalStatus),
      {
        timeout: 3500,
      },
    )
    expect(result.current.latestRun.data?.items[0].summary.http_req_duration_p95_ms).toBe(128)
    expect(result.current.runs.data?.items).toEqual([])
  },
)
