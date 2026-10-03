import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { executionEventsUrl, parseExecutionEvent, useExecutionEvents } from './use-execution-events'

describe('workflow execution events', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('parses valid events and rejects malformed messages', () => {
    const event = parseExecutionEvent(
      JSON.stringify({
        sequence: 4,
        type: 'node.status',
        execution_id: 'execution-id',
        emitted_at: '2026-08-09T08:00:00Z',
        node_id: 'api',
        node_name: '查询用户',
        node_type: 'api',
        node_status: 'running',
        attempts: 0,
        error_code: null,
        error_message: null,
        execution_status: null,
      }),
    )

    expect(event).toMatchObject({ sequence: 4, node_id: 'api', node_status: 'running' })
    expect(
      parseExecutionEvent(
        JSON.stringify({
          sequence: 5,
          type: 'node.result',
          execution_id: 'execution-id',
          node_id: 'api',
          node_status: 'passed',
          result: { status: 'passed', output: { ok: true } },
        }),
      ),
    ).toMatchObject({ type: 'node.result', node_status: 'passed' })
    expect(parseExecutionEvent('not-json')).toBeNull()
    expect(parseExecutionEvent('{}')).toBeNull()
    expect(
      parseExecutionEvent('{"sequence":1,"type":"unknown","execution_id":"execution-id"}'),
    ).toBeNull()
    expect(parseExecutionEvent('{"sequence":1,"type":"node.status"}')).toBeNull()
    expect(parseExecutionEvent(new Blob())).toBeNull()
  })

  it('builds the same-origin websocket endpoint', () => {
    expect(executionEventsUrl('execution-id')).toBe(
      `ws://${window.location.host}/api/v1/executions/execution-id/events`,
    )
    expect(executionEventsUrl('execution-id', 12)).toBe(
      `ws://${window.location.host}/api/v1/executions/execution-id/events?after_sequence=12`,
    )
  })

  it('reconciles before connecting, replays from the last sequence, and de-duplicates', async () => {
    vi.useFakeTimers()
    const sockets: FakeWebSocket[] = []
    class TestSocket extends FakeWebSocket {
      constructor(url: string, protocols: string[]) {
        super(url, protocols)
        sockets.push(this)
      }
    }
    vi.stubGlobal('WebSocket', TestSocket)
    const firstHandler = vi.fn()
    const secondHandler = vi.fn()
    const reconcile = vi.fn().mockResolvedValue(undefined)
    const { rerender, unmount } = renderHook(
      ({ handler }) => useExecutionEvents('execution-id', 'access-token', handler, reconcile),
      { initialProps: { handler: firstHandler } },
    )
    await act(async () => {})
    expect(reconcile).toHaveBeenCalledOnce()
    expect(sockets[0].protocols).toEqual(['flowtest.events.v1', 'flowtest.token.access-token'])

    rerender({ handler: secondHandler })
    act(() => {
      sockets[0].open()
      sockets[0].emit(eventMessage(1))
      sockets[0].emit(eventMessage(1))
      sockets[0].emit('invalid')
      sockets[0].disconnect(1006)
    })
    expect(firstHandler).not.toHaveBeenCalled()
    expect(secondHandler).toHaveBeenCalledTimes(1)
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    expect(reconcile).toHaveBeenCalledTimes(2)
    expect(sockets[1].url).toContain('after_sequence=1')
    act(() => {
      sockets[1].open()
      sockets[1].emit(eventMessage(1))
      sockets[1].emit(eventMessage(2))
    })
    expect(secondHandler).toHaveBeenCalledTimes(2)
    unmount()
    expect(sockets[1].closed).toBe(true)
  })

  it('does not connect without an execution and token', () => {
    const constructor = vi.fn()
    vi.stubGlobal('WebSocket', constructor)
    const { rerender } = renderHook(
      ({ executionId }) => useExecutionEvents(executionId, null, vi.fn()),
      { initialProps: { executionId: null as string | null } },
    )
    rerender({ executionId: 'execution-id' })
    expect(constructor).not.toHaveBeenCalled()
  })

  it('ignores socket messages after cleanup or after a reconnect replaced the socket', async () => {
    vi.useFakeTimers()
    const sockets: FakeWebSocket[] = []
    vi.stubGlobal(
      'WebSocket',
      class extends FakeWebSocket {
        constructor(url: string, protocols: string[]) {
          super(url, protocols)
          sockets.push(this)
        }
      },
    )
    const handler = vi.fn()
    const gap = vi.fn()
    const { unmount } = renderHook(() =>
      useExecutionEvents('execution-id', 'token', handler, async () => {}, gap),
    )
    await act(async () => {})
    act(() => sockets[0].disconnect(1006))
    await act(async () => vi.advanceTimersByTime(500))
    act(() => sockets[0].emit(eventMessage(900)))
    expect(handler).not.toHaveBeenCalled()
    expect(gap).not.toHaveBeenCalled()
    act(() => sockets[1].emit(eventMessage(1)))
    expect(handler).toHaveBeenCalledOnce()
    unmount()
    act(() => sockets[1].emit(eventMessage(2)))
    expect(handler).toHaveBeenCalledOnce()
  })

  it('reconciles a sequence gap before accepting a replay beyond retained history', async () => {
    vi.useFakeTimers()
    const sockets: FakeWebSocket[] = []
    vi.stubGlobal(
      'WebSocket',
      class extends FakeWebSocket {
        constructor(url: string, protocols: string[]) {
          super(url, protocols)
          sockets.push(this)
        }
      },
    )
    const handler = vi.fn()
    const reconcile = vi.fn().mockResolvedValue(undefined)
    const onHistoryGap = vi.fn()
    const { unmount } = renderHook(() =>
      useExecutionEvents('execution-id', 'access-token', handler, reconcile, onHistoryGap),
    )
    await act(async () => {})
    act(() => {
      sockets[0].open()
      sockets[0].emit(eventMessage(1))
      sockets[0].emit(eventMessage(3))
    })
    expect(handler).toHaveBeenCalledTimes(1)
    expect(sockets[0].closed).toBe(true)
    await act(async () => vi.advanceTimersByTime(500))
    expect(reconcile).toHaveBeenCalledTimes(2)
    expect(sockets[1].url).toContain('after_sequence=1')
    act(() => sockets[1].emit(eventMessage(3)))
    expect(handler).toHaveBeenCalledTimes(2)
    expect(onHistoryGap).toHaveBeenCalledOnce()
    expect(onHistoryGap).toHaveBeenCalledWith('execution-id')
    unmount()
  })

  it('marks an initial retained-history gap after reconciling', async () => {
    vi.useFakeTimers()
    const sockets: FakeWebSocket[] = []
    vi.stubGlobal(
      'WebSocket',
      class extends FakeWebSocket {
        constructor(url: string, protocols: string[]) {
          super(url, protocols)
          sockets.push(this)
        }
      },
    )
    const handler = vi.fn()
    const reconcile = vi.fn().mockResolvedValue(undefined)
    const onHistoryGap = vi.fn()
    const { unmount } = renderHook(() =>
      useExecutionEvents('execution-id', 'access-token', handler, reconcile, onHistoryGap),
    )
    await act(async () => {})
    act(() => sockets[0].emit(eventMessage(502)))
    expect(handler).not.toHaveBeenCalled()
    await act(async () => vi.advanceTimersByTime(500))
    expect(reconcile).toHaveBeenCalledTimes(2)
    act(() => sockets[1].emit(eventMessage(502)))
    expect(handler).toHaveBeenCalledOnce()
    expect(onHistoryGap).toHaveBeenCalledWith('execution-id')
    unmount()
  })
})

class FakeWebSocket {
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  onopen: (() => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  closed = false

  constructor(
    readonly url: string,
    readonly protocols: string[],
  ) {}

  emit(data: string) {
    this.onmessage?.(new MessageEvent('message', { data }))
  }

  open() {
    this.onopen?.()
  }

  disconnect(code: number) {
    this.closed = true
    this.onclose?.({ code } as CloseEvent)
  }

  close(code = 1000) {
    this.disconnect(code)
  }
}

function eventMessage(sequence: number): string {
  return JSON.stringify({
    sequence,
    type: 'node.status',
    execution_id: 'execution-id',
    node_id: 'api',
    node_status: 'running',
  })
}
