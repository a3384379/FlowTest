import type { SelfTestBatch, SelfTestScenario } from './self-test-contract'

export function nativeCancellationPending(
  batch: SelfTestBatch | undefined,
  scenarios: readonly SelfTestScenario[] | undefined,
): boolean {
  if (!batch || batch.sealed_at || !['cancelled', 'expired'].includes(batch.phase)) return false
  if (!batch.plan_run_ids.length) return false
  return (
    scenarios === undefined ||
    scenarios.some(
      (scenario) =>
        scenario.observed_status === null ||
        ['queued', 'running'].includes(scenario.observed_status),
    )
  )
}

/** Cancellation acknowledgement is separate from observed native termination. */
export function selfTestPollingInterval(
  batch: SelfTestBatch | undefined,
  scenarios: readonly SelfTestScenario[] | undefined,
  updates: number,
  error: unknown,
): number | false {
  if (!batch || batch.sealed_at || error || updates >= 300) return false
  const active = !['completed', 'cancelled', 'expired'].includes(batch.phase)
  return active || nativeCancellationPending(batch, scenarios) ? 2000 : false
}
