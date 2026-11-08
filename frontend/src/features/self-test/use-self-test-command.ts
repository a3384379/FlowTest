import { SessionBoundaryError } from '../../lib/auth-client'
import { useMutation, useMutationState, useQueryClient, type Mutation } from '@tanstack/react-query'
import { useLayoutEffect, useMemo, useRef } from 'react'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'
import {
  selfTestIdentityIsCurrent,
  selfTestScope,
  type SelfTestIdentity,
} from './self-test-query-keys'

type CommandRequest<Input> = { input: Input; signature: string; key: string }

function commandSignature(input: unknown): string {
  return (
    JSON.stringify(input, (_key, value: unknown) =>
      value !== null && typeof value === 'object' && !Array.isArray(value)
        ? Object.fromEntries(
            Object.entries(value).sort(([left], [right]) => left.localeCompare(right)),
          )
        : value,
    ) ?? 'undefined'
  )
}

function commandRequest<Input>(mutation: Mutation): CommandRequest<Input> | undefined {
  const value: unknown = mutation.state.variables
  if (!value || typeof value !== 'object' || !('key' in value) || !('signature' in value))
    return undefined
  if (typeof value.key !== 'string' || typeof value.signature !== 'string') return undefined
  return value as CommandRequest<Input>
}

/** Unconsumed commands belong to the authenticated query scope, including drawer reopen. */
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
  const mutationKey = [...selfTestScope(identity), 'command', selectionKey]
  const pending =
    useMutationState({
      filters: { mutationKey, exact: true, status: 'pending' },
      select: () => true,
    }).length > 0
  const context = useMemo(() => ({ identity, selectionKey }), [identity, selectionKey])
  const current = useRef<typeof context | null>(context)
  const inFlight = useRef<typeof context | null>(null)
  const permitted = useRef(allowed)
  useLayoutEffect(() => {
    permitted.current = allowed
  }, [allowed])
  const routeKey = `${identity.userId}:${identity.organizationId}:${identity.epoch}:${selectionKey}`
  const [busy, setBusy] = useRouteScopedState(identity.projectId, routeKey, false)
  const [error, setError] = useRouteScopedState<unknown>(identity.projectId, routeKey, null)
  const mutation = useMutation({
    mutationKey,
    gcTime: Infinity,
    mutationFn: (request: CommandRequest<Input>) => {
      if (!isCurrent() || !permitted.current) throw new SessionBoundaryError('操作范围或权限已变化')
      return send(request.input, request.key)
    },
  })
  useLayoutEffect(() => {
    current.current = context
    return () => {
      current.current = null
    }
  }, [context])
  const isCurrent = () => current.current === context && selfTestIdentityIsCurrent(identity)
  const attempts = () => client.getMutationCache().findAll({ mutationKey, exact: true })
  function consume(key: string) {
    for (const attempt of attempts()) {
      if (commandRequest<Input>(attempt)?.key === key) client.getMutationCache().remove(attempt)
    }
  }
  function finish() {
    if (inFlight.current === context) inFlight.current = null
    if (isCurrent()) setBusy(false)
  }
  async function dispatch(input: Input): Promise<{ key: string; result: Result } | undefined> {
    const signature = commandSignature(input)
    const cached = attempts()
    if (cached.some((attempt) => attempt.state.status === 'pending')) return undefined
    const previous = cached.findLast(
      (attempt) => commandRequest<Input>(attempt)?.signature === signature,
    )
    const key = previous ? commandRequest<Input>(previous)!.key : crypto.randomUUID()
    const result =
      previous?.state.status === 'success'
        ? (previous.state.data as Result)
        : await mutation.mutateAsync({ input, signature, key })
    return { key, result }
  }
  async function execute(input: Input): Promise<Result | undefined> {
    if ([!permitted.current, inFlight.current === context, !isCurrent()].some(Boolean))
      return undefined
    inFlight.current = context
    setBusy(true)
    setError(null)
    try {
      await client.cancelQueries({ queryKey: selfTestScope(identity) })
      if (![isCurrent(), permitted.current].every(Boolean)) return undefined
      const receipt = await dispatch(input)
      if (!receipt) return undefined
      await client.invalidateQueries({ queryKey: selfTestScope(identity) })
      if (!isCurrent()) return undefined
      consume(receipt.key)
      return receipt.result
    } catch (failure) {
      if (isCurrent()) setError(failure)
      return undefined
    } finally {
      finish()
    }
  }
  return { execute, error, pending: busy || pending, clearError: () => setError(null) }
}
