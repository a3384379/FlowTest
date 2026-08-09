import { useEffect, useRef } from 'react'

import type { ExecutionEvent } from '../../lib/api'

const EVENTS_PROTOCOL = 'flowtest.events.v1'
const TOKEN_PROTOCOL_PREFIX = 'flowtest.token.'

export function useExecutionEvents(
  executionId: string | null,
  token: string | null,
  onEvent: (event: ExecutionEvent) => void,
) {
  const handler = useRef(onEvent)

  useEffect(() => {
    handler.current = onEvent
  }, [onEvent])

  useEffect(() => {
    if (!executionId || !token) return
    const socket = new WebSocket(executionEventsUrl(executionId), [
      EVENTS_PROTOCOL,
      `${TOKEN_PROTOCOL_PREFIX}${token}`,
    ])
    let latestSequence = 0
    socket.onmessage = (message) => {
      const event = parseExecutionEvent(message.data)
      if (!event || event.sequence <= latestSequence) return
      latestSequence = event.sequence
      handler.current(event)
    }
    return () => socket.close()
  }, [executionId, token])
}

export function executionEventsUrl(executionId: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/api/v1/executions/${executionId}/events`
}

export function parseExecutionEvent(value: unknown): ExecutionEvent | null {
  if (typeof value !== 'string') return null
  try {
    const parsed: unknown = JSON.parse(value)
    if (!isRecord(parsed) || typeof parsed.sequence !== 'number') return null
    if (!isEventType(parsed.type) || typeof parsed.execution_id !== 'string') return null
    return parsed as ExecutionEvent
  } catch {
    return null
  }
}

function isEventType(value: unknown): boolean {
  return ['execution.started', 'node.status', 'execution.completed'].includes(String(value))
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
