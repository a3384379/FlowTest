import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, screen, waitFor } from '@testing-library/react'
import { App } from 'antd'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { server } from '../../test/server'
import * as services from './environment-service'
import { useEnvironmentLab } from './use-environment-lab'

const scope = vi.hoisted(() => ({ projectId: 'first-project' }))
vi.mock('../projects/use-project-context', () => ({
  useProjectContext: () => ({ projectId: scope.projectId }),
}))
function workspace() {
  scope.projectId = 'first-project'
  server.use(
    http.get('/api/v1/v3/features', () => HttpResponse.json({ environment_lab: true })),
    http.get('/api/v1/projects/:projectId/permissions', () =>
      HttpResponse.json({ effective_role: 'owner', capabilities: ['read', 'edit'] }),
    ),
    http.get('/api/v1/environment-templates', () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
    ),
    http.get('/api/v1/projects/:projectId/environment-instances', () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
    ),
  )
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return renderHook(() => useEnvironmentLab(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <App>
        <QueryClientProvider client={client}>
          <MemoryRouter>{children}</MemoryRouter>
        </QueryClientProvider>
      </App>
    ),
  })
}
describe('environment command ownership', () => {
  afterEach(() => vi.restoreAllMocks())
  it.each(['success', 'error'] as const)(
    'ignores delayed cleanup %s after switching projects',
    async (mode) => {
      let complete!: (value: services.EnvironmentInstance) => void
      let reject!: (error: Error) => void
      const response = new Promise<services.EnvironmentInstance>((resolve, fail) => {
        complete = resolve
        reject = fail
      })
      const command = vi.spyOn(services, 'cleanupEnvironment').mockReturnValue(response)
      const { result, rerender } = workspace()
      await waitFor(() => expect(result.current.canEdit).toBe(true))
      let pending!: Promise<void>
      act(() => {
        pending = result.current.startCleanup('original-instance')
      })
      await waitFor(() =>
        expect(command).toHaveBeenCalledWith('first-project', 'original-instance'),
      )
      scope.projectId = 'second-project'
      rerender()
      await act(async () => {
        if (mode === 'success') complete({} as services.EnvironmentInstance)
        else reject(new Error('obsolete-environment-error'))
        await pending
      })
      expect(result.current.projectId).toBe('second-project')
      expect(screen.queryByText('obsolete-environment-error')).not.toBeInTheDocument()
      expect(screen.queryByText('环境清理任务已提交')).not.toBeInTheDocument()
    },
  )
  it('ignores a completed cleanup after leaving the workspace', async () => {
    let complete!: (value: services.EnvironmentInstance) => void
    const command = vi.spyOn(services, 'cleanupEnvironment').mockReturnValue(
      new Promise((resolve) => {
        complete = resolve
      }),
    )
    const { result, unmount } = workspace()
    await waitFor(() => expect(result.current.canEdit).toBe(true))
    let pending!: Promise<void>
    act(() => {
      pending = result.current.startCleanup('original-instance')
    })
    await waitFor(() => expect(command).toHaveBeenCalledOnce())
    unmount()
    await act(async () => {
      complete({} as services.EnvironmentInstance)
      await pending
    })
    expect(screen.queryByText('环境清理任务已提交')).not.toBeInTheDocument()
  })
})
