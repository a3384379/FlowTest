import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider, useParams } from 'react-router-dom'
import type { ReactNode } from 'react'
import { http, HttpResponse } from 'msw'
import { expect, it, vi } from 'vitest'
import { server } from '../../test/server'
import { useContextInspector } from './use-context-inspector'

vi.mock('../projects/use-project-context', () => ({
  useProjectContext: () => ({ projectId: useParams().projectId ?? null }),
}))
it('ignores the earlier context response after navigation and pins only the requested context revision', async () => {
  let release!: () => void,
    started = false
  const barrier = new Promise<void>((resolve) => {
    release = resolve
  })
  const first = { id: 'first', project_id: 'project', revision_id: 'r1' },
    second = { id: 'second', project_id: 'project', revision_id: 'r2' }
  server.use(
    http.get('/api/v1/projects/project/contexts', () =>
      HttpResponse.json({ items: [first, second], total: 2, page: 1, page_size: 20 }),
    ),
    http.get('/api/v1/projects/project/contexts/:id', async ({ params }) => {
      if (params.id === 'first') {
        started = true
        await barrier
        return HttpResponse.json(first)
      }
      return HttpResponse.json(second)
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  let router!: ReturnType<typeof createMemoryRouter>
  function Wrapper({ children }: { children: ReactNode }) {
    router ??= createMemoryRouter(
      [
        {
          path: '/projects/:projectId/*',
          element: <QueryClientProvider client={client}>{children}</QueryClientProvider>,
        },
      ],
      { initialEntries: ['/projects/project/contexts'] },
    )
    return <RouterProvider router={router} />
  }
  const { result } = renderHook(() => useContextInspector(), { wrapper: Wrapper })
  await waitFor(() => expect(started).toBe(true))
  await act(async () => {
    await router.navigate('/projects/project/contexts?focus=second&revision=r2')
    release()
  })
  await waitFor(() => expect(result.current.detail.data?.id).toBe('second'))
  expect(result.current.activeId).toBe('second')
  expect(new URLSearchParams(router.state.location.search).get('focus')).toBe('second')
  expect(new URLSearchParams(router.state.location.search).get('revision')).toBe('r2')
})
