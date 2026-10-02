import type { AssertionEvidenceItem } from './AssertionEvidence'

export function reportAssertionEvidence(value: unknown, name: string): AssertionEvidenceItem[] {
  if (Array.isArray(value)) return value.flatMap((item) => reportAssertionEvidence(item, name))
  if (!value || typeof value !== 'object') return []
  const item = value as Record<string, unknown>
  if (!('expected' in item) && !('actual' in item)) return []
  return [
    {
      name: typeof item.name === 'string' ? item.name : name,
      passed: typeof item.passed === 'boolean' ? item.passed : null,
      expected: item.expected,
      actual: item.actual,
      message: typeof item.message === 'string' ? item.message : undefined,
    },
  ]
}
