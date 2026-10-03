import { useEffect, useRef } from 'react'

import type { ExecutionEvent } from '../../lib/api'

const EVENTS_PROTOCOL = 'flowtest.events.v1'
const TOKEN_PROTOCOL_PREFIX = 'flowtest.token.'

export function useExecutionEvents(
  executionId: string | null,
  token: string | null,
  onEvent: (event: ExecutionEvent) => void,
  onReconcile?: (executionId: string) => Promise<void>,
  onHistoryGap?: (executionId: string) => void,
) {
  const handler = useRef(onEvent)
  const reconcile = useRef(onReconcile)
  const historyGap = useRef(onHistoryGap)

  useEffect(() => {
    handler.current = onEvent
    reconcile.current = onReconcile
    historyGap.current = onHistoryGap
  }, [onEvent, onReconcile, onHistoryGap])

  useEffect(() => {
    if (!executionId || !token) return
    let active = true
    let socket: WebSocket | null = null
    let retryTimer: ReturnType<typeof setTimeout> | null = null
    let latestSequence = 0
    let retryAttempt = 0
    let reconciledGap = false

    function scheduleReconnect() {
      const delay = Math.min(500 * 2 ** retryAttempt, 10_000)
      retryAttempt += 1
      retryTimer = setTimeout(() => void connect(), delay)
    }

    function handleMessage(message: MessageEvent<string>, current: WebSocket) {
      if (!active || current !== socket) return
      const event = parseExecutionEvent(message.data)
      if (!event || event.execution_id !== executionId || event.sequence <= latestSequence) return
      if (event.sequence > latestSequence + 1) {
        if (!reconciledGap) {
          reconciledGap = true
          current.close(4000, 'event-gap')
          return
        }
        historyGap.current?.(executionId)
        latestSequence = event.sequence - 1
      }
      reconciledGap = false
      latestSequence = event.sequence
      handler.current(event)
    }

    async function connect() {
      if (!active) return
      try {
        await reconcile.current?.(executionId!)
      } catch {
        if (active) scheduleReconnect()
        return
      }
      if (!active) return
      const current = new WebSocket(executionEventsUrl(executionId!, latestSequence), [
        EVENTS_PROTOCOL,
        `${TOKEN_PROTOCOL_PREFIX}${token}`,
      ])
      socket = current
      current.onopen = () => {
        if (!active || current !== socket) return
        retryAttempt = 0
      }
      current.onmessage = (message) => handleMessage(message, current)
      current.onclose = (event) => {
        if (!active || current !== socket) return
        if (!shouldRetryClose(event.code)) {
          void reconcile.current?.(executionId!)?.catch(() => {
            if (active && event.code === 1000) scheduleReconnect()
          })
          return
        }
        scheduleReconnect()
      }
    }

    void connect()
    return () => {
      active = false
      if (retryTimer) clearTimeout(retryTimer)
      socket?.close()
    }
  }, [executionId, token])
}

function shouldRetryClose(code: number): boolean {
  return ![1000, 4400, 4401, 4403, 4404].includes(code)
}

export function executionEventsUrl(executionId: string, afterSequence = 0): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const endpoint = `${protocol}//${window.location.host}/api/v1/executions/${executionId}/events`
  return afterSequence > 0 ? `${endpoint}?after_sequence=${afterSequence}` : endpoint
}

export function parseExecutionEvent(value: unknown): ExecutionEvent | null {
  if (typeof value !== 'string') return null
  try {
    const parsed: unknown = JSON.parse(value)
    if (
      !isRecord(parsed) ||
      typeof parsed.sequence !== 'number' ||
      !Number.isSafeInteger(parsed.sequence) ||
      parsed.sequence < 0
    )
      return null
    if (!isEventType(parsed.type) || typeof parsed.execution_id !== 'string') return null
    return parsed as ExecutionEvent
  } catch {
    return null
  }
}

function isEventType(value: unknown): boolean {
  return ['execution.started', 'node.status', 'node.result', 'execution.completed'].includes(
    String(value),
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
