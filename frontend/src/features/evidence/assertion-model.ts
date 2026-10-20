import type { AssertionEvidenceItem } from './AssertionEvidence'
import { frozenAssertionProvenance } from './assertion-source'

type AssertionNodeEvidence = {
  node_type: string
  name: string
  output?: unknown
  result?: { assertions?: unknown; output?: unknown } | null
}

export function reportNodeAssertionEvidence(
  node: AssertionNodeEvidence & { assertion?: unknown },
): AssertionEvidenceItem[] {
  const normalized = workflowAssertionEvidence({
    ...node,
    output: node.output ?? node.result?.output,
  })
  return normalized.length ? normalized : reportAssertionEvidence(node.assertion, node.name)
}

export function workflowAssertionEvidence(
  node: AssertionNodeEvidence | undefined,
): AssertionEvidenceItem[] {
  if (!node) return []
  const standard = reportAssertionEvidence(node.result?.assertions, node.name)
  if (standard.length) {
    const provenance = frozenAssertionProvenance(node.output)
    return standard.length === 1 && provenance && matchesFrozenOutput(standard[0], node.output)
      ? [{ ...standard[0], provenance }]
      : standard
  }
  return node.node_type === 'assert' ? reportAssertionEvidence(node.output, node.name) : []
}

function matchesFrozenOutput(item: AssertionEvidenceItem, value: unknown): boolean {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const output = value as Record<string, unknown>
  return (
    output.passed === item.passed &&
    JSON.stringify(output.actual) === JSON.stringify(item.actual) &&
    JSON.stringify(output.expected) === JSON.stringify(item.expected)
  )
}

export function reportAssertionEvidence(value: unknown, name: string): AssertionEvidenceItem[] {
  if (Array.isArray(value)) return value.flatMap((item) => reportAssertionEvidence(item, name))
  if (!value || typeof value !== 'object') return []
  const item = value as Record<string, unknown>
  if (!('expected' in item) && !('actual' in item)) return []
  const provenance = frozenAssertionProvenance(item)
  return [
    {
      name: typeof item.name === 'string' ? item.name : name,
      passed: typeof item.passed === 'boolean' ? item.passed : null,
      expected: item.expected,
      actual: item.actual,
      message: typeof item.message === 'string' ? item.message : undefined,
      ...(provenance ? { provenance } : {}),
    },
  ]
}
