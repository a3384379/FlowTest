import type { SelfTestBatch } from './self-test-contract'

export function isDispatchRecovery(batch: SelfTestBatch | undefined): boolean {
  return Boolean(
    batch &&
    batch.phase === 'running' &&
    !batch.sealed_at &&
    batch.reason_codes.includes('SELFTEST_DISPATCH_UNCONFIRMED') &&
    batch.plan_run_ids.length === 1 &&
    batch.resource_digest &&
    batch.resource_snapshot,
  )
}
