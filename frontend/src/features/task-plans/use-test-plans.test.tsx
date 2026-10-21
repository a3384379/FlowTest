import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, screen, waitFor } from '@testing-library/react'
import { App } from 'antd'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { TestPlanRun } from '../../lib/api'
import { server } from '../../test/server'
import * as services from './task-plan-service'
import { useTestPlans } from './use-test-plans'

const scope = vi.hoisted(() => ({ projectId: 'first-project' }))
vi.mock('../projects/use-project-context', () => ({
  useProjectContext: () => ({
    projectId: scope.projectId,
    projects: { data: { items: [] } },
    selectProject: vi.fn(),
  }),
}))

const run: TestPlanRun = {
  id: 'original-run',
  project_id: 'first-project',
  test_plan_id: 'original-plan',
  requested_by_id: 'owned-user',
  status: 'queued',
  trigger_type: 'manual',
  queue_priority: 5,
  queue_name: 'general',
  baseline_run_id: null,
  quality_summary: {},
  cancel_requested_at: null,
  started_at: null,
  completed_at: null,
  error_message: null,
  created_at: '2026-10-21T00:00:00Z',
}

function workspace() {
  scope.projectId = 'first-project'
  server.use(
    http.get('/api/v1/projects/:projectId/permissions', () =>
      HttpResponse.json({
        effective_role: 'owner',
        capabilities: ['read', 'edit', 'manage_members'],
        matrix: {},
      }),
    ),
    http.get('/api/v1/projects/:projectId/:resource', ({ params }) =>
      HttpResponse.json(
        ['environments', 'service-tokens'].includes(String(params.resource))
          ? []
          : { items: [], total: 0, page: 1, page_size: 20 },
      ),
    ),
  )
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return renderHook(() => useTestPlans(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <App>
        <QueryClientProvider client={client}>
          <MemoryRouter initialEntries={['/projects/first-project/tasks']}>{children}</MemoryRouter>
        </QueryClientProvider>
      </App>
    ),
  })
}

describe('task completion ownership', () => {
  afterEach(() => vi.restoreAllMocks())

  it.each(['success', 'error'] as const)(
    'ignores a delayed queue %s after switching projects',
    async (mode) => {
      let complete!: (value: TestPlanRun) => void
      let fail!: (reason: Error) => void
      const response = new Promise<TestPlanRun>((resolve, reject) => {
        complete = resolve
        fail = reject
      })
      const queued = vi.spyOn(services, 'runTestPlan').mockReturnValue(response)
      const { result, rerender } = workspace()
      await waitFor(() => expect(result.current.canEdit).toBe(true))
      let pending!: Promise<void>
      act(() => {
        pending = result.current.execute('original-plan')
      })
      await waitFor(() => expect(queued).toHaveBeenCalledWith('first-project', 'original-plan'))
      scope.projectId = 'second-project'
      rerender()
      await act(async () => {
        if (mode === 'success') complete(run)
        else fail(new Error('obsolete-queue-error'))
        await pending
      })
      expect(result.current.projectId).toBe('second-project')
      expect(result.current.selectedRunId).toBeNull()
      expect(result.current.focusedId).toBeNull()
      expect(screen.queryByText('obsolete-queue-error')).not.toBeInTheDocument()
      expect(screen.queryByText('测试计划已进入队列')).not.toBeInTheDocument()
    },
  )

  it('ignores a successful queue result after the task workspace unmounts', async () => {
    let complete!: (value: TestPlanRun) => void
    const response = new Promise<TestPlanRun>((resolve) => {
      complete = resolve
    })
    const queued = vi.spyOn(services, 'runTestPlan').mockReturnValue(response)
    const { result, unmount } = workspace()
    await waitFor(() => expect(result.current.canEdit).toBe(true))
    let pending!: Promise<void>
    act(() => {
      pending = result.current.execute('original-plan')
    })
    await waitFor(() => expect(queued).toHaveBeenCalledOnce())
    unmount()
    await act(async () => {
      complete(run)
      await pending
    })
    expect(screen.queryByText('测试计划已进入队列')).not.toBeInTheDocument()
  })

  it('keeps the run selected while an earlier queue command is still pending', async () => {
    let complete!: (value: TestPlanRun) => void
    const response = new Promise<TestPlanRun>((resolve) => {
      complete = resolve
    })
    const queued = vi.spyOn(services, 'runTestPlan').mockReturnValue(response)
    const { result } = workspace()
    await waitFor(() => expect(result.current.canEdit).toBe(true))
    let pending!: Promise<void>
    act(() => {
      pending = result.current.execute('original-plan')
    })
    await waitFor(() => expect(queued).toHaveBeenCalledOnce())
    act(() => result.current.setSelectedRunId('already-selected-run'))
    expect(result.current.selectedRunId).toBe('already-selected-run')
    await act(async () => {
      complete(run)
      await pending
    })
    expect(result.current.selectedRunId).toBe('already-selected-run')
    expect(result.current.focusedId).toBeNull()
    expect(screen.queryByText('测试计划已进入队列')).not.toBeInTheDocument()
  })
})
