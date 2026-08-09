import { addEdge, type Connection, type Edge } from '@xyflow/react'

import type { WorkflowDefinition, WorkflowNode } from '../lib/api'

export function connectNodes(
  definition: WorkflowDefinition,
  edges: Edge[],
  connection: Connection,
): WorkflowDefinition {
  if (!connection.source || !connection.target || connection.source === connection.target) {
    return definition
  }
  const id = `${connection.source}-${connection.target}-${Date.now()}`
  const changed = addEdge({ ...connection, id }, edges)
  if (!changed.some((edge) => edge.id === id)) return definition
  const condition = nextCondition(definition, connection.source)
  if (condition === undefined) return definition
  return {
    ...definition,
    edges: [
      ...definition.edges,
      { id, source: connection.source, target: connection.target, condition, mappings: [] },
    ],
  }
}

export function addApiNode(definition: WorkflowDefinition, apiId: string): WorkflowDefinition {
  const id = uniqueNodeId(definition, 'api')
  return {
    ...definition,
    nodes: [
      ...definition.nodes,
      {
        id,
        type: 'api',
        name: `接口请求 ${definition.nodes.filter((node) => node.type === 'api').length + 1}`,
        position: nextPosition(definition),
        config: { api_definition_id: apiId, max_retries: 0, retry_on: ['network_error', '5xx'] },
      },
    ],
  }
}

export function addTypedNode(
  definition: WorkflowDefinition,
  type: Exclude<WorkflowNode['type'], 'start' | 'api'>,
  artifactId: string | null,
): WorkflowDefinition {
  const id = uniqueNodeId(definition, type)
  return {
    ...definition,
    nodes: [
      ...definition.nodes,
      {
        id,
        type,
        name: defaultNodeName(type),
        position: nextPosition(definition),
        config: defaultNodeConfig(definition, type, artifactId),
      },
    ],
  }
}

function uniqueNodeId(definition: WorkflowDefinition, prefix: string): string {
  const existing = new Set(definition.nodes.map((node) => node.id))
  let index = existing.size + 1
  while (existing.has(`${prefix}-${index}`)) index += 1
  return `${prefix}-${index}`
}

function nextPosition(definition: WorkflowDefinition) {
  const maxX = Math.max(0, ...definition.nodes.map((node) => node.position.x))
  return { x: maxX + 220, y: 120 + (definition.nodes.length % 3) * 100 }
}

function nextCondition(
  definition: WorkflowDefinition,
  sourceId: string,
): 'true' | 'false' | null | undefined {
  const source = definition.nodes.find((node) => node.id === sourceId)
  if (source?.type !== 'condition') return null
  const used = new Set(
    definition.edges.filter((edge) => edge.source === sourceId).map((edge) => edge.condition),
  )
  if (!used.has('true')) return 'true'
  if (!used.has('false')) return 'false'
  return undefined
}

function defaultNodeName(type: Exclude<WorkflowNode['type'], 'start' | 'api'>): string {
  return {
    extract: '提取变量',
    assert: '断言校验',
    condition: '条件判断',
    delay: '等待',
    dataset: '数据集',
    end: '结束',
  }[type]
}

function defaultNodeConfig(
  definition: WorkflowDefinition,
  type: Exclude<WorkflowNode['type'], 'start' | 'api'>,
  artifactId: string | null,
): Record<string, unknown> {
  const sourceNodeId = definition.nodes.at(-1)?.id ?? 'start'
  if (type === 'extract') {
    return { source_node_id: sourceNodeId, expression: 'body', variable: 'extracted_value' }
  }
  if (type === 'assert') {
    return {
      source_node_id: sourceNodeId,
      expression: 'status_code',
      operator: 'equals',
      expected: 200,
    }
  }
  if (type === 'condition') {
    return {
      source_node_id: sourceNodeId,
      expression: 'body.enabled',
      operator: 'equals',
      expected: true,
    }
  }
  if (type === 'delay') return { seconds: 1 }
  if (type === 'dataset') return { artifact_id: artifactId ?? '', format: 'auto' }
  return {}
}
