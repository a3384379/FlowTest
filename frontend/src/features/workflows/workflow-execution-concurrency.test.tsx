import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { App, ConfigProvider } from 'antd'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { DraftSessionProvider } from '../drafts/DraftSessionProvider'
import { authenticateTestUser } from '../../test/auth'
import { environment, project, user, workflow, workflowRunningExecution } from '../../test/fixtures'
import type { ExecutionEvent, WorkflowExecution, WorkflowExecutionDetail } from '../../lib/api'
import { useWorkflows } from './use-workflows'
import { useAuthStore } from '../auth/auth-store'

const context = vi.hoisted(() => ({ projectId: '' }))
vi.mock('../projects/use-project-context', () => ({
  useProjectContext: () => ({
    projects: { data: { items: [] } },
    projectId: context.projectId,
    selectProject: vi.fn(),
  }),
}))
vi.mock('./workflow-service', () => ({
  listWorkflows: async () => ({
    items: [workflow, { ...workflow, id: 'workflow-b' }],
    total: 2,
    page: 1,
    page_size: 100,
  }),
  listEnvironments: async () => [environment],
  listApis: async () => ({ items: [] }),
  listArtifacts: async () => ({ items: [] }),
  listWorkflowExecutions: async () => ({ items: [] }),
  executeWorkflow: vi.fn(),
  getWorkflowExecution: vi.fn(),
  rerunFailedWorkflowItems: vi.fn(),
}))
vi.mock('../data-sources/data-source-service', () => ({ listCredentials: async () => [] }))
vi.mock('../protocols/protocol-service', () => ({
  listGraphQLSchemas: async () => ({ items: [] }),
  listGrpcDescriptors: async () => ({ items: [] }),
  listEventSources: async () => ({ items: [] }),
}))
vi.mock('./use-execution-events', () => ({ useExecutionEvents: vi.fn() }))
import { executeWorkflow, getWorkflowExecution, rerunFailedWorkflowItems } from './workflow-service'
import { useExecutionEvents } from './use-execution-events'

function pending<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: Error) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}
function execution(id: string, workflowId = workflow.id): WorkflowExecution {
  return { ...workflowRunningExecution, id, workflow_id: workflowId }
}
function detail(
  value: WorkflowExecution,
  status: WorkflowExecution['status'] = 'passed',
): WorkflowExecutionDetail {
  return { execution: { ...value, status }, nodes: [], children: [] }
}
async function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <ConfigProvider theme={{ token: { motion: false } }}>
        <App>
          <QueryClientProvider client={client}>
            <MemoryRouter>
              <DraftSessionProvider>{children}</DraftSessionProvider>
            </MemoryRouter>
          </QueryClientProvider>
        </App>
      </ConfigProvider>
    )
  }
  const hook = renderHook(() => useWorkflows(workflow.id), { wrapper: Wrapper })
  await waitFor(() => expect(hook.result.current.canEdit).toBe(true))
  await waitFor(() => expect(hook.result.current.selectedWorkflow?.id).toBe(workflow.id))
  act(() => hook.result.current.setEnvironmentSelection(environment.id))
  return hook
}
function callbacks(id: string) {
  const call = vi.mocked(useExecutionEvents).mock.calls.findLast(([active]) => active === id)
  if (!call) throw new Error(`No subscription for ${id}`)
  return { event: call[2], reconcile: call[3]! }
}
beforeEach(() => {
  context.projectId = project.id
  authenticateTestUser(user)
  vi.clearAllMocks()
  vi.mocked(getWorkflowExecution).mockImplementation(async (_project, id) =>
    detail(execution(id), 'running'),
  )
})
afterEach(() => {
  vi.useRealTimers()
  localStorage.clear()
  useAuthStore.setState({ user: null })
})

it('does not let a completed request from workflow A replace the active run of workflow B', async () => {
  const oldResult = pending<WorkflowExecutionDetail>()
  const runA = execution('run-a')
  const runB = execution('run-b', 'workflow-b')
  vi.mocked(executeWorkflow).mockResolvedValueOnce(runA).mockResolvedValueOnce(runB)
  const hook = await setup()
  vi.useFakeTimers()
  await act(async () => hook.result.current.execute())
  vi.mocked(getWorkflowExecution).mockReturnValueOnce(oldResult.promise)
  await act(async () => vi.advanceTimersByTime(500))
  act(() => hook.result.current.setWorkflowSelection('workflow-b'))
  await act(async () => hook.result.current.execute())
  await act(async () => oldResult.resolve(detail(runA)))
  expect(hook.result.current.workflowId).toBe('workflow-b')
  expect(hook.result.current.activeExecutionId).toBe('run-b')
  expect(hook.result.current.runtimeExecution?.id).toBe('run-b')
  expect(hook.result.current.lastResult).toBeNull()
})

it('ignores a delayed start response after selecting another workflow', async () => {
  const start = pending<WorkflowExecution>()
  vi.mocked(executeWorkflow).mockReturnValueOnce(start.promise)
  const hook = await setup()
  let operation!: Promise<void>
  act(() => {
    operation = hook.result.current.execute()
  })
  act(() => hook.result.current.setWorkflowSelection('workflow-b'))
  await act(async () => {
    start.resolve(execution('run-a'))
    await operation
  })
  expect(hook.result.current.workflowId).toBe('workflow-b')
  expect(hook.result.current.workspaceMode).toBe('draft')
  expect(hook.result.current.activeExecutionId).toBeNull()
})

it('keeps the newest start when two runs of the same workflow return out of order', async () => {
  const first = pending<WorkflowExecution>()
  const second = pending<WorkflowExecution>()
  vi.mocked(executeWorkflow).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
  const hook = await setup()
  let older!: Promise<void>, newer!: Promise<void>
  act(() => {
    older = hook.result.current.execute()
  })
  act(() => {
    newer = hook.result.current.execute()
  })
  await act(async () => {
    second.resolve(execution('run-new'))
    await newer
  })
  await act(async () => {
    first.resolve(execution('run-old'))
    await older
  })
  expect(hook.result.current.activeExecutionId).toBe('run-new')
  expect(hook.result.current.runtimeExecution?.id).toBe('run-new')
})

it('ignores delayed events and reconciliation from a superseded run', async () => {
  vi.mocked(executeWorkflow)
    .mockResolvedValueOnce(execution('run-old'))
    .mockResolvedValueOnce(execution('run-new'))
  const hook = await setup()
  await act(async () => hook.result.current.execute())
  const previous = callbacks('run-old')
  const reconciliation = pending<WorkflowExecutionDetail>()
  vi.mocked(getWorkflowExecution).mockReturnValueOnce(reconciliation.promise)
  let operation!: Promise<void>
  act(() => {
    operation = previous.reconcile('run-old')
  })
  await act(async () => hook.result.current.execute())
  act(() =>
    previous.event({
      type: 'node.status',
      execution_id: 'run-old',
      node_id: 'api',
      node_status: 'failed',
      attempts: 1,
    } as ExecutionEvent),
  )
  await act(async () => {
    reconciliation.resolve(detail(execution('run-old')))
    await operation
  })
  expect(hook.result.current.activeExecutionId).toBe('run-new')
  expect(hook.result.current.nodeStatuses).toMatchObject({ api: 'pending' })
  expect(hook.result.current.lastResult).toBeNull()
})

it('keeps terminal server evidence when a node event arrives after completion', async () => {
  const run = execution('run-complete')
  vi.mocked(executeWorkflow).mockResolvedValueOnce(run)
  const hook = await setup()
  await act(async () => hook.result.current.execute())
  const previous = callbacks(run.id)
  const finished = detail(run)
  vi.mocked(getWorkflowExecution).mockResolvedValueOnce(finished)
  await act(async () => previous.reconcile(run.id))
  act(() =>
    previous.event({
      type: 'node.status',
      execution_id: run.id,
      node_id: 'api',
      node_status: 'running',
      attempts: 1,
    } as ExecutionEvent),
  )
  expect(hook.result.current.lastResult).toEqual(finished)
  expect(hook.result.current.nodeStatuses).toEqual({})
  expect(hook.result.current.activeExecutionId).toBeNull()
})

it.each(['execute', 'rerun'] as const)(
  'preserves the terminal evidence while a replacement %s request is pending or rejected',
  async (kind) => {
    const run = execution('run-finished')
    vi.mocked(executeWorkflow).mockResolvedValueOnce(run)
    const hook = await setup()
    await act(async () => hook.result.current.execute())
    const finished = detail(run, 'failed')
    vi.mocked(getWorkflowExecution).mockResolvedValueOnce(finished)
    await act(async () => callbacks(run.id).reconcile(run.id))
    const request = pending<WorkflowExecution>()
    if (kind === 'execute') vi.mocked(executeWorkflow).mockReturnValueOnce(request.promise)
    else vi.mocked(rerunFailedWorkflowItems).mockReturnValueOnce(request.promise)
    let operation!: Promise<void>
    act(() => {
      operation = (
        kind === 'execute'
          ? hook.result.current.execute()
          : hook.result.current.rerunFailedItems(run.id, {
              loop_node_id: 'loop',
              input_indices: [0],
              upstream_resource_status: 'unverified',
              write_retry_strategy: 'reject',
            })
      ).catch(() => undefined)
    })
    expect(hook.result.current.lastResult).toEqual(finished)
    expect(hook.result.current.runtimeExecution?.id).toBe(run.id)
    await act(async () => {
      request.reject(new Error('replacement request rejected'))
      await operation
    })
    expect(hook.result.current.lastResult).toEqual(finished)
    expect(hook.result.current.runtimeExecution?.id).toBe(run.id)
  },
)

it.each(['project', 'user', 'unmount'] as const)(
  'invalidates an in-flight completion on %s changes',
  async (change) => {
    vi.mocked(executeWorkflow).mockResolvedValueOnce(execution('run-a'))
    const hook = await setup()
    await act(async () => hook.result.current.execute())
    const old = callbacks('run-a')
    const completion = pending<WorkflowExecutionDetail>()
    vi.mocked(getWorkflowExecution).mockReturnValueOnce(completion.promise)
    let operation!: Promise<void>
    act(() => {
      operation = old.reconcile('run-a')
    })
    if (change === 'unmount') hook.unmount()
    else
      act(() => {
        if (change === 'project') context.projectId = 'project-b'
        else authenticateTestUser({ ...user, id: 'user-b' })
        hook.rerender()
      })
    const requests = vi.mocked(getWorkflowExecution).mock.calls.length
    await act(async () => {
      completion.resolve(detail(execution('run-a')))
      await operation
    })
    expect(getWorkflowExecution).toHaveBeenCalledTimes(requests)
    if (change !== 'unmount') {
      expect(hook.result.current.lastResult).toBeNull()
      expect(hook.result.current.activeExecutionId).toBeNull()
    }
  },
)

it('does not adopt a delayed failed-item rerun after switching workflows', async () => {
  const response = pending<WorkflowExecution>()
  vi.mocked(rerunFailedWorkflowItems).mockReturnValueOnce(response.promise)
  const hook = await setup()
  let operation!: Promise<void>
  act(() => {
    operation = hook.result.current.rerunFailedItems('run-a', {
      loop_node_id: 'loop',
      input_indices: [0],
      upstream_resource_status: 'unverified',
      write_retry_strategy: 'reject',
    })
  })
  act(() => hook.result.current.setWorkflowSelection('workflow-b'))
  await act(async () => {
    response.resolve(execution('derived-a'))
    await operation
  })
  expect(hook.result.current.workspaceMode).toBe('draft')
  expect(hook.result.current.activeExecutionId).toBeNull()
})
