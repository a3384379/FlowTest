import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { executionEventsUrl, parseExecutionEvent, useExecutionEvents } from './use-execution-events'

describe('workflow execution events', () => {
  afterEach(() => vi.unstubAllGlobals())

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
  })

  it('subscribes with a token, de-duplicates messages, and closes cleanly', () => {
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
    const { rerender, unmount } = renderHook(
      ({ handler }) => useExecutionEvents('execution-id', 'access-token', handler),
      { initialProps: { handler: firstHandler } },
    )
    expect(sockets[0].protocols).toEqual(['flowtest.events.v1', 'flowtest.token.access-token'])

    rerender({ handler: secondHandler })
    act(() => {
      sockets[0].emit(eventMessage(2))
      sockets[0].emit(eventMessage(2))
      sockets[0].emit('invalid')
    })

    expect(firstHandler).not.toHaveBeenCalled()
    expect(secondHandler).toHaveBeenCalledTimes(1)
    unmount()
    expect(sockets[0].closed).toBe(true)
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
})

class FakeWebSocket {
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  closed = false

  constructor(
    readonly url: string,
    readonly protocols: string[],
  ) {}

  emit(data: string) {
    this.onmessage?.(new MessageEvent('message', { data }))
  }

  close() {
    this.closed = true
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
