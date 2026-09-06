import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { PropsWithChildren } from 'react'
import { expect, it } from 'vitest'

import { server } from '../../test/server'
import { useContextPage } from './use-context-page'

it('shares bounded pages across consumers and resets pagination when changing project', async () => {
  const requests: string[] = []
  server.use(
    http.get('/api/v1/projects/:projectId/contexts', ({ request, params }) => {
      const page = Number(new URL(request.url).searchParams.get('page'))
      requests.push(`${params.projectId}:${page}`)
      return HttpResponse.json({ items: [], total: 101, page, page_size: 20 })
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  const { result, rerender } = renderHook(
    ({ projectId, enabled }) => useContextPage(projectId, enabled),
    { wrapper, initialProps: { projectId: 'first', enabled: false } },
  )
  expect(requests).toEqual([])
  rerender({ projectId: 'first', enabled: true })
  await waitFor(() => expect(result.current.contexts.isSuccess).toBe(true))
  act(() => result.current.setPage(6))
  await waitFor(() => expect(result.current.contexts.data?.page).toBe(6))
  rerender({ projectId: 'second', enabled: true })
  await waitFor(() => expect(result.current.contexts.data?.page).toBe(1))
  expect(requests).toEqual(['first:1', 'first:6', 'second:1'])
})
