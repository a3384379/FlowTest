import type { SelfTestState } from './use-self-tests'

export function canReviseBatch(state: SelfTestState) {
  const batch = state.selectedBatch
  return Boolean(
    batch?.generation_mode === 'host_llm_mcp' &&
    batch.sealed_at &&
    batch.resource_digest &&
    batch.evidence_integrity === 'complete' &&
    batch.cleanup_status === 'completed' &&
    state.generation.data?.sources.length === batch.expected_count,
  )
}
