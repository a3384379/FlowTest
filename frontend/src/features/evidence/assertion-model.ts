import type { AssertionEvidenceItem } from './AssertionEvidence'

type AssertionNodeEvidence = {
  node_type: string
  name: string
  output: unknown
  result?: { assertions?: unknown } | null
}

export function workflowAssertionEvidence(
  node: AssertionNodeEvidence | undefined,
): AssertionEvidenceItem[] {
  if (!node) return []
  const standard = reportAssertionEvidence(node.result?.assertions, node.name)
  if (standard.length) return standard
  return node.node_type === 'assert' ? reportAssertionEvidence(node.output, node.name) : []
}

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
