import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { App as AntdApp } from 'antd'
import { http, HttpResponse } from 'msw'
import { expect, it } from 'vitest'
import type { ReactNode } from 'react'
import { useAIReview } from '../../features/ai/use-ai-review'
import ProjectTestProvider from '../../test/ProjectTestProvider'
import { authenticateTestUser } from '../../test/auth'
import { project, user } from '../../test/fixtures'
import { server } from '../../test/server'

function harness(section: 'ai' | 'apis' | 'performance') {
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

it.each(['create', 'select'] as const)(
  'updates suggestions for an off-page running job (%s)',
  async (selection) => {
    let completed = false
    let suggestionsReads = 0
    const old = { id: 'old-job', project_id: project.id, status: 'completed' }
    const fresh = { id: 'fresh-job', project_id: project.id, status: 'running' }
    server.use(
      http.get('/api/v1/ai/status', () => HttpResponse.json({ enabled: true })),
      http.get('/api/v1/ai/jobs', ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get('page') ?? '1')
        return HttpResponse.json({
          items: page === 2 ? [old] : [{ ...fresh, status: completed ? 'completed' : 'running' }],
          total: 21,
          page,
          page_size: 20,
        })
      }),
      http.post('/api/v1/ai/jobs', () => HttpResponse.json(fresh)),
      http.get('/api/v1/ai/jobs/:id', ({ params }) =>
        HttpResponse.json(
          params.id === fresh.id ? { ...fresh, status: completed ? 'completed' : 'running' } : old,
        ),
      ),
      http.get('/api/v1/ai/jobs/:id/suggestions', ({ params }) => {
        if (params.id === fresh.id) suggestionsReads += 1
        return HttpResponse.json(
          params.id === fresh.id && completed
            ? [{ id: 'fresh-suggestion', title: 'Finished suggestion' }]
            : [],
        )
      }),
    )
    const { wrapper } = harness('ai')
    const { result } = renderHook(() => useAIReview(), { wrapper })
    await waitFor(() => expect(result.current.canEdit).toBe(true))
    if (selection === 'select') {
      act(() => result.current.selectJob(fresh.id))
      await waitFor(() => expect(result.current.selectedJob.data?.status).toBe('running'))
    }
    act(() => result.current.jobs.setPage(2))
    await waitFor(() => expect(result.current.jobs.data?.items[0].id).toBe('old-job'))
    if (selection === 'create')
      await act(async () =>
        result.current.createJob({ job_type: 'assertion_suggestions', metadata: {} }),
      )
    await waitFor(() => expect(result.current.selectedJobId).toBe('fresh-job'))
    await waitFor(() => expect(suggestionsReads).toBeGreaterThan(0))
    completed = true
    await waitFor(() => expect(result.current.suggestions.data?.[0]?.id).toBe('fresh-suggestion'), {
      timeout: 3000,
    })
  },
)
