import { useState } from 'react'
import { MutationCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { authenticateTestUser } from '../../test/auth'
import { project, user } from '../../test/fixtures'
import { server } from '../../test/server'
import { selfTestBatch, selfTestIds } from './self-test-test-fixtures'
import { useSelfTestIdentity } from './self-test-query-keys'
import { createSelfTestRun } from './self-test-service'
import { useSelfTestCommand } from './use-self-test-command'
import type { BatchInput } from './self-test-contract'

const path = `/api/v1/projects/${project.id}/self-tests/installations/${selfTestIds.installation}/runs`
const input: BatchInput = {
  scenario_ids: [],
  verification_scope: 'full_pack',
  budget: { timeout_seconds: 600, max_requests: 500, max_tool_calls: 100 },
}
const batch = { ...selfTestBatch, batch_kind: 'fixed_baseline', generation_mode: null }
function Command() {
  const identity = useSelfTestIdentity(project.id)
  const [result, setResult] = useState<string>()
  const command = useSelfTestCommand({
    identity,
    selectionKey: `native:${selfTestIds.installation}`,
    allowed: true,
    send: (body: BatchInput, key: string) =>
      createSelfTestRun(project.id, selfTestIds.installation, body, key),
  })
  return (
    <>
      <button
        disabled={command.pending}
        onClick={async () => {
          const value = await command.execute(input)
          if (value) setResult(value.id)
        }}
      >
        确认运行
      </button>
      {command.error ? <p role="alert">请求结果未知</p> : null}
      <output>{result}</output>
    </>
  )
}
function Harness() {
  const [open, setOpen] = useState(true)
  return (
    <>
      <button onClick={() => setOpen((value) => !value)}>{open ? '关闭操作' : '打开操作'}</button>
      {open && <Command />}
    </>
  )
}
function mount(mutationCache?: MutationCache) {
  const client = new QueryClient({
    mutationCache,
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  )
  return client
}
beforeEach(() => authenticateTestUser(user))
describe('self-test command intent across drawer lifecycle', () => {
  it('never sends an old identity command released from the mutation queue', async () => {
    let release!: () => void
    let entered = false
    const barrier = new Promise<void>((resolve) => {
      release = resolve
    })
    let writes = 0
    server.use(
      http.post(path, () => {
        writes += 1
        return HttpResponse.json(batch)
      }),
    )
    const client = mount(
      new MutationCache({
        onMutate: async () => {
          entered = true
          await barrier
        },
      }),
    )
    await userEvent.click(screen.getByRole('button', { name: '确认运行' }))
    await waitFor(() => expect(entered).toBe(true))
    act(() => authenticateTestUser({ ...user, id: selfTestIds.task }))
    await act(async () => {
      release()
      await barrier
    })
    await waitFor(() =>
      expect(
        client
          .getMutationCache()
          .getAll()
          .some((item) => item.state.status !== 'pending'),
      ).toBe(true),
    )
    expect(writes).toBe(0)
  })
  it('reuses a committed request key after a lost response and drawer reopen', async () => {
    const keys: string[] = []
    const commits = new Set<string>()
    server.use(
      http.post(path, ({ request }) => {
        const key = request.headers.get('Idempotency-Key')!
        keys.push(key)
        commits.add(key)
        return keys.length === 1
          ? HttpResponse.json(
              { error: { code: 'UNAVAILABLE', message: '响应丢失', trace_id: 'lost-response' } },
              { status: 503 },
            )
          : HttpResponse.json(batch)
      }),
    )
    mount()
    await userEvent.click(screen.getByRole('button', { name: '确认运行' }))
    await screen.findByRole('alert')
    await userEvent.click(screen.getByRole('button', { name: '关闭操作' }))
    await userEvent.click(screen.getByRole('button', { name: '打开操作' }))
    await userEvent.click(screen.getByRole('button', { name: '确认运行' }))
    await screen.findByText(selfTestIds.batch)
    expect(keys).toHaveLength(2)
    expect(keys[1]).toBe(keys[0])
    expect(commits.size).toBe(1)
  })
  it('recovers a success received after unmount without issuing a second create', async () => {
    let release!: () => void
    const response = new Promise<void>((resolve) => {
      release = resolve
    })
    let writes = 0
    server.use(
      http.post(path, async () => {
        writes += 1
        await response
        return HttpResponse.json(batch)
      }),
    )
    const client = mount()
    await userEvent.click(screen.getByRole('button', { name: '确认运行' }))
    await waitFor(() => expect(writes).toBe(1))
    await userEvent.click(screen.getByRole('button', { name: '关闭操作' }))
    await act(async () => {
      release()
      await response
    })
    await waitFor(() =>
      expect(
        client
          .getMutationCache()
          .getAll()
          .some((item) => item.state.status === 'success'),
      ).toBe(true),
    )
    await userEvent.click(screen.getByRole('button', { name: '打开操作' }))
    await userEvent.click(screen.getByRole('button', { name: '确认运行' }))
    await screen.findByText(selfTestIds.batch)
    expect(writes).toBe(1)
  })
  it('keeps a reopened controller disabled while the original request is pending', async () => {
    let release!: () => void
    const response = new Promise<void>((resolve) => {
      release = resolve
    })
    let writes = 0
    server.use(
      http.post(path, async () => {
        writes += 1
        await response
        return HttpResponse.json(batch)
      }),
    )
    mount()
    await userEvent.click(screen.getByRole('button', { name: '确认运行' }))
    await waitFor(() => expect(writes).toBe(1))
    await userEvent.click(screen.getByRole('button', { name: '关闭操作' }))
    await userEvent.click(screen.getByRole('button', { name: '打开操作' }))
    expect(screen.getByRole('button', { name: '确认运行' })).toBeDisabled()
    await act(async () => {
      release()
      await response
    })
    await waitFor(() => expect(screen.getByRole('button', { name: '确认运行' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: '确认运行' }))
    await screen.findByText(selfTestIds.batch)
    expect(writes).toBe(1)
  })
  it('starts a fresh intent after the preceding successful receipt was consumed', async () => {
    const keys: string[] = []
    server.use(
      http.post(path, ({ request }) => {
        keys.push(request.headers.get('Idempotency-Key')!)
        return HttpResponse.json(batch)
      }),
    )
    mount()
    await userEvent.click(screen.getByRole('button', { name: '确认运行' }))
    await screen.findByText(selfTestIds.batch)
    await userEvent.click(screen.getByRole('button', { name: '确认运行' }))
    await waitFor(() => expect(keys).toHaveLength(2))
    expect(keys[1]).not.toBe(keys[0])
  })
  it("does not adopt another authenticated user's unresolved intent", async () => {
    const keys: string[] = []
    server.use(
      http.post(path, ({ request }) => {
        keys.push(request.headers.get('Idempotency-Key')!)
        return keys.length === 1
          ? HttpResponse.json(
              { error: { code: 'UNAVAILABLE', message: '响应丢失', trace_id: 'lost-response' } },
              { status: 503 },
            )
          : HttpResponse.json(batch)
      }),
    )
    mount()
    await userEvent.click(screen.getByRole('button', { name: '确认运行' }))
    await screen.findByRole('alert')
    await userEvent.click(screen.getByRole('button', { name: '关闭操作' }))
    act(() => authenticateTestUser({ ...user, id: selfTestIds.task }))
    await userEvent.click(screen.getByRole('button', { name: '打开操作' }))
    await userEvent.click(screen.getByRole('button', { name: '确认运行' }))
    await screen.findByText(selfTestIds.batch)
    expect(keys[1]).not.toBe(keys[0])
  })
})
