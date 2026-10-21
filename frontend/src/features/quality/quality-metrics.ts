import type { QualityGate } from './quality-service'

export function qualityGateCounts(
  gates?: QualityGate[],
): { enabled: number; total: number } | undefined {
  if (!gates) return undefined
  return { enabled: gates.filter((gate) => gate.enabled).length, total: gates.length }
}
