import type { WorkflowDefinition, WorkflowNode } from '../../lib/api'
import { effectiveConfig, resolveEffectiveNodeType } from '../../flow/editor/graph-analysis'
import { reportExecutionPath } from '../workflows/execution-navigation'

export type AssertionSourceReference = { nodeId: string; expression: string | null }
export type AssertionProvenance = {
  actual: AssertionSourceReference
  expected?: AssertionSourceReference
  operator?: string
  expectedKind: 'literal' | 'node' | 'unresolved' | 'recorded'
}
export type AssertionSourceNode = {
  node_id: string
  node_type?: string
  name: string
  status: string
  attempts: number
  observations?: ReadonlyArray<{ attempt: number }>
  result?: { observations?: ReadonlyArray<{ attempt: number }> } | null
}
export type AssertionSourceContext = {
  projectId: string
  executionId: string
  assertionNodeId: string
  nodes: ReadonlyArray<AssertionSourceNode>
  frozenDefinition?: WorkflowDefinition | null
  instanceId?: string
}
export type LocatedAssertionSource = AssertionSourceReference & {
  name?: string
  href?: string
  reason?: string
  attempt?: number
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}
export function frozenAssertionProvenance(value: unknown): AssertionProvenance | undefined {
  const item = record(value)
  if (!item || typeof item.source_node_id !== 'string' || typeof item.expression !== 'string')
    return undefined
  const expected =
    typeof item.expected_source_node_id === 'string' && typeof item.expected_expression === 'string'
      ? { nodeId: item.expected_source_node_id, expression: item.expected_expression }
      : undefined
  return {
    actual: { nodeId: item.source_node_id, expression: item.expression },
    ...(expected ? { expected } : {}),
    expectedKind: expectedSourceKind(item, expected),
    ...(typeof item.operator === 'string' ? { operator: item.operator } : {}),
  }
}

function expectedSourceKind(
  item: Record<string, unknown>,
  reference: AssertionSourceReference | undefined,
): AssertionProvenance['expectedKind'] {
  if (reference) return 'node'
  return item.expected_source_node_id != null || item.expected_expression != null
    ? 'unresolved'
    : 'literal'
}
export function definitionAssertionProvenance(
  context: AssertionSourceContext,
  singleAssertion = true,
): AssertionProvenance | undefined {
  const nodes = frozenDefinitionNodes(context.frozenDefinition)
  const node = nodes.find((item) => item.id === context.assertionNodeId)
  const type = node
    ? resolveEffectiveNodeType(node)
    : context.nodes.find((item) => item.node_id === context.assertionNodeId)?.node_type
  if (type === 'api')
    return {
      actual: { nodeId: context.assertionNodeId, expression: null },
      expectedKind: 'recorded',
    }
  if (node && type === 'assert' && singleAssertion)
    return frozenAssertionProvenance(effectiveConfig(node))
  return undefined
}

function frozenDefinitionNodes(definition: WorkflowDefinition | null | undefined): WorkflowNode[] {
  if (!definition) return []
  return [...definition.nodes, ...(definition.regions ?? []).flatMap((region) => region.nodes)]
}
export function locateAssertionSource(
  reference: AssertionSourceReference,
  context: AssertionSourceContext,
): LocatedAssertionSource {
  if (context.instanceId)
    return { ...reference, reason: '区域实例的来源轮次未解析，不跳转到其他实例' }
  const node = context.nodes.find((item) => item.node_id === reference.nodeId)
  if (!node) return { ...reference, reason: '同次运行未提供来源节点证据' }
  const observations = node.observations ?? node.result?.observations ?? []
  if (node.status !== 'passed' && observations.length === 0)
    return { ...reference, name: node.name, reason: '来源节点未成功完成，无法确认对应尝试' }
  const attempt = sourceAttempt(node, observations)
  return {
    ...reference,
    name: node.name,
    attempt,
    href: reportExecutionPath(context.projectId, {
      executionId: context.executionId,
      nodeId: node.node_id,
      attempt,
    }),
  }
}

function sourceAttempt(
  node: AssertionSourceNode,
  observations: ReadonlyArray<{ attempt: number }>,
): number | undefined {
  return observations.at(-1)?.attempt ?? (node.attempts > 0 ? node.attempts : undefined)
}
