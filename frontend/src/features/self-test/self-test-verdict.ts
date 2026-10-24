import type { SelfTestBatch, SelfTestScenario } from './self-test-contract'
export function scenarioHasCompleteEvidence(batch: SelfTestBatch, scenario: SelfTestScenario) {
  return [
    batch.phase === 'completed',
    batch.evidence_integrity === 'complete',
    batch.sealed_at !== null,
    batch.cleanup_status === 'completed',
    batch.expected_count > 0,
    batch.required_scenario_set.length > 0,
    batch.verdict !== 'pending',
    scenario.attempts_complete,
    scenario.observed_status !== null,
    scenario.executions.some((item) => item.execution_id !== null),
  ].every(Boolean)
}
export function batchHasCompleteVerdict(batch: SelfTestBatch) {
  return (
    batch.verdict === 'passed' &&
    batch.phase === 'completed' &&
    batch.sealed_at !== null &&
    batch.evidence_integrity === 'complete' &&
    batch.cleanup_status === 'completed' &&
    batch.expected_count > 0 &&
    batch.required_scenario_set.length > 0
  )
}
