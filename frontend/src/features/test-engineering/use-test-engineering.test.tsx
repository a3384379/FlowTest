import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { App } from 'antd'
import type { ReactNode } from 'react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import { server } from '../../test/server'
import { useTestEngineering } from './use-test-engineering'

const scope = vi.hoisted(() => ({ projectId: 'first-project' }))
vi.mock('../projects/use-project-context', () => ({ useProjectContext: () => scope }))

describe('test engineering project isolation', () => {
  it('discards a delayed preview from the previous project and never creates a proposal automatically', async () => {
    let releasePreview: (() => void) | undefined
    const ready = new Promise<void>((resolve) => {
      releasePreview = resolve
    })
    let started = false
    let proposals = 0
    server.use(
      http.get('/api/v1/projects/:projectId/apis', () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
      http.get('/api/v1/projects/:projectId/environments', () => HttpResponse.json([])),
      http.post('/api/v1/projects/first-project/test-engineering/generate', async () => {
        started = true
        await ready
        return HttpResponse.json({
          fingerprint: 'old-preview',
          persisted: false,
          design: {},
          contract_completeness: 'complete',
          contract_fingerprint: 'old-contract',
        })
      }),
      http.post('/api/v1/projects/:projectId/test-engineering/proposals', () => {
        proposals += 1
        return HttpResponse.json({})
      }),
    )
    scope.projectId = 'first-project'
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    const { result, rerender } = renderHook(() => useTestEngineering(), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <App>
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        </App>
      ),
    })
    let pending: Promise<boolean> | undefined
    act(() => {
      pending = result.current.generateDesign('old-api')
    })
    await waitFor(() => expect(started).toBe(true))
    scope.projectId = 'second-project'
    rerender()
    await act(async () => {
      releasePreview!()
      await pending
    })
    expect(result.current.projectId).toBe('second-project')
    expect(result.current.generation).toBeNull()
    expect(result.current.proposal).toBeNull()
    expect(proposals).toBe(0)
  })
})
