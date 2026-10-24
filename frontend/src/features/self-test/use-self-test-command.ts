import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useLayoutEffect, useMemo, useRef } from 'react'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'
import {
  selfTestIdentityIsCurrent,
  selfTestScope,
  type SelfTestIdentity,
} from './self-test-query-keys'

/** Every explicit command owns one key. Lost responses retain it for an explicit retry. */
export function useSelfTestCommand<Input, Result>({
  identity,
  selectionKey,
  allowed,
  send,
}: {
  identity: SelfTestIdentity
  selectionKey: string
  allowed: boolean
  send: (input: Input, idempotencyKey: string) => Promise<Result>
}) {
  const client = useQueryClient()
  const context = useMemo(() => ({ identity, selectionKey }), [identity, selectionKey])
  const current = useRef<typeof context | null>(context)
  const inFlight = useRef<typeof context | null>(null)
  const permitted = useRef(allowed)
  useLayoutEffect(() => {
    permitted.current = allowed
  }, [allowed])
  const routeKey = `${identity.userId}:${identity.organizationId}:${identity.epoch}:${selectionKey}`
  const [busy, setBusy] = useRouteScopedState(identity.projectId, routeKey, false)
  const intent = useRef<{ context: typeof context; input: string; key: string } | null>(null)
  const [error, setError] = useRouteScopedState<unknown>(identity.projectId, routeKey, null)
  const mutation = useMutation({
    mutationFn: (request: { input: Input; key: string }) => send(request.input, request.key),
  })
  useLayoutEffect(() => {
    current.current = context
    return () => {
      current.current = null
    }
  }, [context])
  const isCurrent = () => current.current === context && selfTestIdentityIsCurrent(identity)
  function finish() {
    if (inFlight.current === context) inFlight.current = null
    if (isCurrent()) setBusy(false)
  }
  async function execute(input: Input): Promise<Result | undefined> {
    if ([!permitted.current, inFlight.current === context, !isCurrent()].some(Boolean))
      return undefined
    inFlight.current = context
    setBusy(true)
    setError(null)
    const encoded = JSON.stringify(input)
    if (
      [
        !intent.current,
        intent.current?.context !== context,
        intent.current?.input !== encoded,
      ].some(Boolean)
    )
      intent.current = { context, input: encoded, key: crypto.randomUUID() }
    const idempotencyKey = intent.current!.key
    try {
      await client.cancelQueries({ queryKey: selfTestScope(identity) })
      if (![isCurrent(), permitted.current].every(Boolean)) return undefined
      const result = await mutation.mutateAsync({ input, key: idempotencyKey })
      await client.invalidateQueries({ queryKey: selfTestScope(identity) })
      if (!isCurrent()) return undefined
      intent.current = null
      return result
    } catch (failure) {
      if (isCurrent()) setError(failure)
      return undefined
    } finally {
      finish()
    }
  }
  return { execute, error, pending: busy, clearError: () => setError(null) }
}
