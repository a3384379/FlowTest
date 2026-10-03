import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { App } from 'antd'
import { useState, type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { authenticateTestUser } from '../../test/auth'
import { apiDefinition, environment, executionDetail, project, user } from '../../test/fixtures'
import type { ExecutionDetail } from '../../lib/api'
import { useAuthStore } from '../auth/auth-store'
import { executeApi, getApiExecution, listExecutions } from './api-service'
import { useApiExecutions } from './use-api-executions'

vi.mock('./api-service', () => ({
  listExecutions: vi.fn(),
  getApiExecution: vi.fn(),
  executeApi: vi.fn(),
}))

beforeEach(() => {
  authenticateTestUser(user)
  vi.resetAllMocks()
  vi.mocked(listExecutions).mockResolvedValue({
    items: [executionDetail.execution],
    page: 1,
    page_size: 20,
    total: 43,
  })
})

const base = {
  projectId: project.id,
  apiId: apiDefinition.id,
  environmentId: environment.id,
  expectedStatus: 200,
}

function Wrapper({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
      }),
  )
  return (
    <App>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </App>
  )
}

function deferred() {
  let resolve!: (value: ExecutionDetail) => void
  const promise = new Promise<ExecutionDetail>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('API asset execution workspace', () => {
  it('scopes complete history and page state to the selected API asset', async () => {
    const { result, rerender } = renderHook((apiId) => useApiExecutions({ ...base, apiId }), {
      initialProps: base.apiId,
      wrapper: Wrapper,
    })
    await waitFor(() => expect(result.current.history.data?.total).toBe(43))
    expect(listExecutions).toHaveBeenCalledWith(project.id, { apiId: base.apiId, page: 1 })
    act(() => result.current.setHistoryPage(3))
    await waitFor(() =>
      expect(listExecutions).toHaveBeenCalledWith(project.id, { apiId: base.apiId, page: 3 }),
    )
    rerender('other-api')
    expect(result.current.historyPage).toBe(1)
    await waitFor(() =>
      expect(listExecutions).toHaveBeenCalledWith(project.id, { apiId: 'other-api', page: 1 }),
    )
  })

  it('rejects a history link owned by another API even when the request URL matches', async () => {
    vi.mocked(getApiExecution).mockResolvedValue({
      ...executionDetail,
      execution: { ...executionDetail.execution, api_definition_id: 'other-api' },
    })
    const { result } = renderHook(
      () => useApiExecutions({ ...base, executionId: 'foreign-history' }),
      { wrapper: Wrapper },
    )
    await waitFor(() => expect(result.current.selectedExecution.isError).toBe(true))
    expect(result.current.result).toBeNull()
    expect(result.current.selectedExecution.error?.message).toContain('不属于当前接口资产')
  })

  it('keeps the later history selection when the first response arrives last', async () => {
    const slow = deferred()
    const fast = {
      ...executionDetail,
      execution: {
        ...executionDetail.execution,
        id: 'fast-record',
        response_body: { frozen: 'B' },
      },
    }
    vi.mocked(getApiExecution).mockImplementation((_projectId, id) =>
      id === 'slow-record' ? slow.promise : Promise.resolve(fast),
    )
    const { result, rerender } = renderHook(
      (executionId) => useApiExecutions({ ...base, executionId }),
      { initialProps: 'slow-record', wrapper: Wrapper },
    )
    await waitFor(() => expect(getApiExecution).toHaveBeenCalled())
    rerender('fast-record')
    await waitFor(() => expect(result.current.result?.execution.id).toBe('fast-record'))
    await act(async () =>
      slow.resolve({
        ...executionDetail,
        execution: { ...executionDetail.execution, id: 'slow-record' },
      }),
    )
    expect(result.current.result?.execution.response_body).toEqual({ frozen: 'B' })
  })

  it('keeps each API result separate when a slow request completes after switching assets', async () => {
    const slow = deferred()
    const fast = {
      ...executionDetail,
      execution: { ...executionDetail.execution, id: 'B-result', api_definition_id: 'api-B' },
    }
    vi.mocked(executeApi).mockImplementation((_projectId, apiId) =>
      apiId === base.apiId ? slow.promise : Promise.resolve(fast),
    )
    const { result, rerender } = renderHook((apiId) => useApiExecutions({ ...base, apiId }), {
      initialProps: base.apiId,
      wrapper: Wrapper,
    })
    act(() => result.current.execute())
    await waitFor(() => expect(executeApi).toHaveBeenCalledTimes(1))
    rerender('api-B')
    act(() => result.current.execute())
    await waitFor(() => expect(result.current.result?.execution.id).toBe('B-result'))
    await act(async () => slow.resolve(executionDetail))
    expect(result.current.result?.execution.id).toBe('B-result')
    rerender(base.apiId)
    expect(result.current.result?.execution.id).toBe(executionDetail.execution.id)
  })

  it('does not replace a newer request or expose results after the login identity changes', async () => {
    const slow = deferred()
    const latest = {
      ...executionDetail,
      execution: { ...executionDetail.execution, id: 'latest-result' },
    }
    vi.mocked(executeApi).mockReturnValueOnce(slow.promise).mockResolvedValueOnce(latest)
    const { result } = renderHook(() => useApiExecutions(base), { wrapper: Wrapper })
    act(() => result.current.execute())
    await waitFor(() => expect(executeApi).toHaveBeenCalledTimes(1))
    act(() => result.current.execute())
    await waitFor(() => expect(result.current.result?.execution.id).toBe('latest-result'))
    await act(async () => slow.resolve(executionDetail))
    expect(result.current.result?.execution.id).toBe('latest-result')
    act(() =>
      useAuthStore.setState({
        user: { ...user, id: 'another-user' },
        epoch: useAuthStore.getState().epoch + 1,
      }),
    )
    expect(result.current.result).toBeNull()
  })
})
