import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, screen, waitFor } from '@testing-library/react'
import { App } from 'antd'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { server } from '../../test/server'
import * as services from './performance-service'
import { usePerformanceLab } from './use-performance-lab'
const scope = vi.hoisted(() => ({ projectId: 'first-project' }))
vi.mock('../projects/use-project-context', () => ({
  useProjectContext: () => ({ projectId: scope.projectId }),
}))
const queued: services.PerformanceRun = {
  id: 'new-run',
  project_id: 'first-project',
  scenario_id: 'scenario',
  scenario_version: 1,
  status: 'queued',
  definition_snapshot: {
    executor: 'constant_vus',
    steps: [],
    thresholds: [],
    vus: 5,
    duration_seconds: 30,
    start_vus: null,
    stages: [],
    graceful_stop_seconds: 30,
  },
  compiled_sha256: 'hash',
  summary: {},
  threshold_results: [],
  baseline_run_id: null,
  raw_metrics_artifact_id: null,
  error_code: null,
  error_message: null,
  started_at: null,
  completed_at: null,
  created_by_id: 'actor',
  created_at: '2026-10-21T00:00:00Z',
  updated_at: '2026-10-21T00:00:00Z',
  gate_evaluations: [],
}
function workspace() {
  scope.projectId = 'first-project'
  server.use(
    http.get('/api/v1/v3/features', () => HttpResponse.json({ performance_lab: true })),
    http.get('/api/v1/projects/:projectId/permissions', () =>
      HttpResponse.json({ effective_role: 'owner', capabilities: ['read', 'edit'] }),
    ),
    http.get('/api/v1/projects/:projectId/performance-scenarios', () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
    ),
    http.get('/api/v1/projects/:projectId/performance-runs', () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 }),
    ),
    http.get('/api/v1/projects/:projectId/performance-runs/:runId', ({ params }) =>
      HttpResponse.json({ ...queued, id: params.runId, project_id: params.projectId }),
    ),
  )
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const hook = renderHook(() => usePerformanceLab(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <App>
        <QueryClientProvider client={client}>
          <MemoryRouter initialEntries={['/projects/first-project/performance?run=old-run']}>
            {children}
          </MemoryRouter>
        </QueryClientProvider>
      </App>
    ),
  })
  return { ...hook, client }
}
describe('performance command ownership', () => {
  afterEach(() => vi.restoreAllMocks())
  it('opens the returned run from an old run context and stores its exact queued evidence', async () => {
    vi.spyOn(services, 'runPerformanceScenario').mockResolvedValue(queued)
    const { result, client } = workspace()
    await waitFor(() => expect(result.current.canEdit).toBe(true))
    await act(async () => {
      await result.current.startRun('scenario')
    })
    await waitFor(() => expect(result.current.runId).toBe('new-run'))
    expect(result.current.scenarioId).toBeNull()
    expect(client.getQueryData(['performance-run', 'first-project', 'new-run'])).toEqual(queued)
  })
  it.each(['project-success', 'project-error', 'selection', 'unmount'] as const)(
    'ignores a delayed run after %s',
    async (mode) => {
      let resolve!: (value: services.PerformanceRun) => void, reject!: (error: Error) => void
      const command = vi.spyOn(services, 'runPerformanceScenario').mockReturnValue(
        new Promise((done, fail) => {
          resolve = done
          reject = fail
        }),
      )
      const { result, rerender, unmount } = workspace()
      await waitFor(() => expect(result.current.canEdit).toBe(true))
      let pending!: Promise<void>
      act(() => {
        pending = result.current.startRun('scenario')
      })
      await waitFor(() => expect(command).toHaveBeenCalledOnce())
      if (mode.startsWith('project')) {
        scope.projectId = 'second-project'
        rerender()
      }
      if (mode === 'selection') act(() => result.current.selectObject('run', 'later-run'))
      if (mode === 'unmount') unmount()
      await act(async () => {
        if (mode === 'project-error') reject(new Error('obsolete-performance-error'))
        else resolve(queued)
        await pending
      })
      if (mode !== 'unmount')
        expect(result.current.runId).toBe(mode === 'selection' ? 'later-run' : 'old-run')
      expect(screen.queryByText('obsolete-performance-error')).not.toBeInTheDocument()
      expect(screen.queryByText('性能任务已进入独立队列')).not.toBeInTheDocument()
    },
  )
})
