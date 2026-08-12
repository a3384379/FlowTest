import { addEdge, type Connection, type Edge } from '@xyflow/react'

import type { Credential, WorkflowDefinition, WorkflowNode } from '../lib/api'
import type { SchemaArtifact } from '../features/protocols/protocol-service'

export type PaletteNodeType = Exclude<WorkflowNode['type'], 'start' | 'api' | 'capability'>

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

export function addProtocolNode(
  definition: WorkflowDefinition,
  protocol: 'graphql' | 'grpc',
  asset: SchemaArtifact,
): WorkflowDefinition {
  const id = uniqueNodeId(definition, protocol)
  const capabilityId = protocol === 'graphql' ? 'graphql.request' : 'grpc.call'
  return {
    ...definition,
    nodes: [
      ...definition.nodes,
      {
        id,
        type: 'capability',
        name: protocol === 'graphql' ? 'GraphQL 请求' : 'gRPC 调用',
        position: nextPosition(definition),
        config: {},
        capability_id: capabilityId,
        capability_version: '3.0.0',
        configuration: protocolConfiguration(protocol, asset),
        bindings: [],
      },
    ],
  }
}

export function addTypedNode(
  definition: WorkflowDefinition,
  type: PaletteNodeType,
  artifactId: string | null,
  subflow: { workflowId: string; workflowVersion: number } | null = null,
  credentials: Credential[] = [],
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
        config: defaultNodeConfig(definition, type, artifactId, subflow, credentials),
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

function defaultNodeName(type: PaletteNodeType): string {
  return {
    extract: '提取变量',
    assert: '断言校验',
    condition: '条件判断',
    delay: '等待',
    dataset: '数据集',
    subflow: '子流程',
    for_each: '循环子流程',
    sql: '只读 SQL',
    redis: 'Redis 读取',
    end: '结束',
  }[type]
}

function defaultNodeConfig(
  definition: WorkflowDefinition,
  type: PaletteNodeType,
  artifactId: string | null,
  subflow: { workflowId: string; workflowVersion: number } | null,
  credentials: Credential[],
): Record<string, unknown> {
  const sourceNodeId = definition.nodes.at(-1)?.id ?? 'start'
  if (isSourceNodeType(type)) {
    return sourceNodeConfig(type, sourceNodeId)
  }
  if (isNestedNodeType(type)) {
    return nestedNodeConfig(type, sourceNodeId, subflow)
  }
  return leafNodeConfig(type, artifactId, credentials)
}

function leafNodeConfig(
  type: Exclude<
    WorkflowNode['type'],
    'start' | 'api' | 'capability' | 'extract' | 'assert' | 'condition' | 'subflow' | 'for_each'
  >,
  artifactId: string | null,
  credentials: Credential[],
): Record<string, unknown> {
  if (type === 'delay') return { seconds: 1 }
  if (type === 'dataset') return { artifact_id: artifactId ?? '', format: 'auto' }
  if (type === 'sql') {
    return {
      credential_id:
        credentials.find((item) => item.kind === 'postgresql' || item.kind === 'mysql')?.id ?? '',
      query: 'SELECT 1 AS healthy',
      parameters: {},
      timeout_seconds: 30,
    }
  }
  if (type === 'redis') {
    return {
      credential_id: credentials.find((item) => item.kind === 'redis')?.id ?? '',
      command: 'GET',
      arguments: ['key'],
      timeout_seconds: 30,
    }
  }
  return {}
}

function isSourceNodeType(type: PaletteNodeType): type is 'extract' | 'assert' | 'condition' {
  return type === 'extract' || type === 'assert' || type === 'condition'
}

function isNestedNodeType(type: PaletteNodeType): type is 'subflow' | 'for_each' {
  return type === 'subflow' || type === 'for_each'
}

function sourceNodeConfig(
  type: 'extract' | 'assert' | 'condition',
  sourceNodeId: string,
): Record<string, unknown> {
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
  return {}
}

function nestedNodeConfig(
  type: 'subflow' | 'for_each',
  sourceNodeId: string,
  subflow: { workflowId: string; workflowVersion: number } | null,
): Record<string, unknown> {
  const reference = {
    workflow_id: subflow?.workflowId ?? '',
    workflow_version: subflow?.workflowVersion ?? 1,
  }
  if (type === 'subflow') {
    return reference
  }
  return {
    ...reference,
    source_node_id: sourceNodeId,
    expression: 'body.items',
    item_variable: 'item',
    index_variable: 'index',
    concurrency: 5,
    fail_fast: true,
  }
}

export function pasteNode(
  definition: WorkflowDefinition,
  copied: WorkflowNode,
): WorkflowDefinition {
  const id = uniqueNodeId(definition, `${copied.type}-copy`)
  return {
    ...definition,
    nodes: [
      ...definition.nodes,
      {
        ...copied,
        id,
        name: `${copied.name} 副本`,
        position: { x: copied.position.x + 40, y: copied.position.y + 40 },
        config: structuredClone(copied.config),
        configuration: copied.configuration ? structuredClone(copied.configuration) : undefined,
        bindings: copied.bindings ? structuredClone(copied.bindings) : undefined,
      },
    ],
  }
}

function protocolConfiguration(
  protocol: 'graphql' | 'grpc',
  asset: SchemaArtifact,
): Record<string, unknown> {
  if (protocol === 'graphql') {
    return {
      schema_id: asset.id,
      endpoint: 'https://api.example.com/graphql',
      operation: 'query FlowTest { __typename }',
      variables: {},
      headers: {},
      timeout_seconds: 30,
    }
  }
  const method = firstGrpcMethod(asset)
  return {
    descriptor_id: asset.id,
    endpoint: 'grpc.example.com:443',
    service: method.service,
    method: method.method,
    request: {},
    metadata: {},
    call_type: method.callType,
    tls_mode: 'tls',
    timeout_seconds: 30,
  }
}

function firstGrpcMethod(asset: SchemaArtifact) {
  const services = Array.isArray(asset.summary.services) ? asset.summary.services : []
  const service = services.find(isRecord)
  const methods = service && Array.isArray(service.methods) ? service.methods : []
  const method = methods.find(isRecord)
  return {
    service: typeof service?.name === 'string' ? service.name : '',
    method: typeof method?.name === 'string' ? method.name : '',
    callType: method?.call_type === 'server_streaming' ? 'server_streaming' : 'unary',
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function autoLayoutWorkflow(definition: WorkflowDefinition): WorkflowDefinition {
  const levels = workflowLevels(definition)
  const rows = new Map<number, number>()
  return {
    ...definition,
    nodes: definition.nodes.map((node) => {
      const level = levels.get(node.id) ?? 0
      const row = rows.get(level) ?? 0
      rows.set(level, row + 1)
      return { ...node, position: { x: level * 240, y: row * 120 } }
    }),
  }
}

function workflowLevels(definition: WorkflowDefinition): Map<string, number> {
  const { incoming, outgoing } = workflowAdjacency(definition)
  const levels = new Map<string, number>()
  const pending = definition.nodes
    .filter((node) => incoming.get(node.id) === 0)
    .map((node) => node.id)
  while (pending.length) {
    const current = pending.shift() as string
    assignTargetLevels(current, levels, incoming, outgoing, pending)
  }
  return levels
}

function workflowAdjacency(definition: WorkflowDefinition) {
  const incoming = new Map(definition.nodes.map((node) => [node.id, 0]))
  const outgoing = new Map(definition.nodes.map((node) => [node.id, [] as string[]]))
  for (const edge of definition.edges) {
    incoming.set(edge.target, mapValue(incoming, edge.target) + 1)
    outgoing.get(edge.source)?.push(edge.target)
  }
  return { incoming, outgoing }
}

function assignTargetLevels(
  current: string,
  levels: Map<string, number>,
  incoming: Map<string, number>,
  outgoing: Map<string, string[]>,
  pending: string[],
) {
  const currentLevel = mapValue(levels, current)
  for (const target of outgoing.get(current) ?? []) {
    levels.set(target, Math.max(mapValue(levels, target), currentLevel + 1))
    const remaining = mapValue(incoming, target) - 1
    incoming.set(target, remaining)
    if (remaining === 0) pending.push(target)
  }
}

function mapValue(values: Map<string, number>, key: string): number {
  return values.get(key) ?? 0
}
