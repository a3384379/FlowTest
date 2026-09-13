import type { WorkflowDefinition, WorkflowEdge, WorkflowNode } from '../../lib/api'
import type { EditDiagnostic } from './editor-types'

const legacyCapabilities: Readonly<Record<string, WorkflowNode['type']>> = {
  'flow.start': 'start',
  'http.request': 'api',
  'data.extract': 'extract',
  'assertion.evaluate': 'assert',
  'flow.condition': 'condition',
  'flow.delay': 'delay',
  'data.dataset': 'dataset',
  'flow.subflow': 'subflow',
  'flow.foreach': 'for_each',
  'sql.query': 'sql',
  'redis.read': 'redis',
  'flow.end': 'end',
}
export function resolveEffectiveNodeType(node: WorkflowNode): WorkflowNode['type'] {
  if (node.type !== 'capability' || node.capability_version !== '2.0.0') return node.type
  return legacyCapabilities[node.capability_id ?? ''] ?? 'capability'
}
export function effectiveConfig(node: WorkflowNode): Record<string, unknown> {
  return node.type === 'capability' ? (node.configuration ?? {}) : node.config
}
export function diagnostic(
  code: string,
  message: string,
  nodeId?: string,
  edgeId?: string,
): EditDiagnostic {
  return { code, message, severity: 'error', nodeId, edgeId }
}
export function adjacency(definition: WorkflowDefinition, reverse = false): Map<string, string[]> {
  const result = new Map(definition.nodes.map((node) => [node.id, [] as string[]]))
  for (const edge of definition.edges) {
    const [source, target] = reverse ? [edge.target, edge.source] : [edge.source, edge.target]
    result.get(source)?.push(target)
  }
  return result
}
export function reachable(origins: string[], graph: Map<string, string[]>): Set<string> {
  const visited = new Set<string>()
  const pending = [...origins]
  while (pending.length) {
    const id = pending.pop()!
    if (visited.has(id)) continue
    visited.add(id)
    pending.push(...(graph.get(id) ?? []))
  }
  return visited
}
export function hasCycle(definition: WorkflowDefinition): boolean {
  const outgoing = adjacency(definition)
  const incoming = new Map(definition.nodes.map((node) => [node.id, 0]))
  for (const edge of definition.edges)
    incoming.set(edge.target, (incoming.get(edge.target) ?? 0) + 1)
  const pending = [...incoming].filter(([, count]) => count === 0).map(([id]) => id)
  let count = 0
  while (pending.length) {
    const id = pending.pop()!
    count++
    for (const target of outgoing.get(id) ?? []) {
      const remaining = (incoming.get(target) ?? 0) - 1
      incoming.set(target, remaining)
      if (remaining === 0) pending.push(target)
    }
  }
  return count !== definition.nodes.length
}
export function edgeIssues(edge: WorkflowEdge, nodes: Map<string, WorkflowNode>): EditDiagnostic[] {
  const source = nodes.get(edge.source)
  const target = nodes.get(edge.target)
  if (!source || !target)
    return [diagnostic('UNKNOWN_ENDPOINT', '连线引用的节点不存在', undefined, edge.id)]
  const issues: EditDiagnostic[] = []
  if (source.id === target.id)
    issues.push(diagnostic('SELF_LOOP', '节点不能连接自身', source.id, edge.id))
  if (nodePhase(source) !== nodePhase(target))
    issues.push(diagnostic('CROSS_PHASE', '主流程与清理阶段不能直接连线', undefined, edge.id))
  if (resolveEffectiveNodeType(source) === 'end' || resolveEffectiveNodeType(target) === 'start')
    issues.push(
      diagnostic('BOUNDARY_EDGE', '不能连接到开始节点或从结束节点连出', undefined, edge.id),
    )
  if (edge.condition != null && resolveEffectiveNodeType(source) !== 'condition')
    issues.push(diagnostic('INVALID_BRANCH', '普通连线不能包含条件分支', undefined, edge.id))
  if (
    edge.mappings.some(
      (mapping) => mapping.source.node_id !== edge.source || mapping.target.node_id !== edge.target,
    )
  )
    issues.push(diagnostic('MAPPING_ENDPOINT', '映射端点与连线不一致', undefined, edge.id))
  return issues
}
function boundaryIssues(main: WorkflowNode[]): EditDiagnostic[] {
  const issues: EditDiagnostic[] = []
  const count = (type: WorkflowNode['type']) =>
    main.filter((node) => resolveEffectiveNodeType(node) === type).length
  if (count('start') !== 1) issues.push(diagnostic('START_COUNT', '主流程必须有且只有一个开始节点'))
  if (count('end') === 0) issues.push(diagnostic('END_COUNT', '主流程至少需要一个结束节点'))
  if (count('dataset') > 1) issues.push(diagnostic('DATASET_COUNT', '主流程只能有一个数据集节点'))
  return issues
}
function nodeIssues(definition: WorkflowDefinition, mainIds: Set<string>): EditDiagnostic[] {
  return definition.nodes.flatMap((node) => {
    const issues: EditDiagnostic[] = []
    if (resolveEffectiveNodeType(node) === 'condition') {
      const branches = definition.edges
        .filter((edge) => edge.source === node.id)
        .map((edge) => edge.condition)
        .sort()
      if (branches.join(',') !== 'false,true')
        issues.push(
          diagnostic('CONDITION_BRANCHES', '条件节点需要恰好一条真分支和一条假分支', node.id),
        )
    }
    if (node.cleanup_for?.some((id) => !mainIds.has(id)))
      issues.push(diagnostic('CLEANUP_REFERENCE', '清理范围引用了不存在的主流程节点', node.id))
    if (
      node.phase === 'cleanup' &&
      ['subflow', 'for_each'].includes(resolveEffectiveNodeType(node)) &&
      !definition.run_policy?.cleanup_request_budget
    )
      issues.push(diagnostic('CLEANUP_BUDGET', '清理子流程必须配置请求预算', node.id))
    return issues
  })
}
export function analyzeGraph(definition: WorkflowDefinition): EditDiagnostic[] {
  const main = definition.nodes.filter((node) => node.phase !== 'cleanup')
  const nodes = new Map(definition.nodes.map((node) => [node.id, node]))
  const issues = [
    ...boundaryIssues(main),
    ...definition.edges.flatMap((edge) => edgeIssues(edge, nodes)),
    ...nodeIssues(definition, new Set(main.map((node) => node.id))),
  ]
  if (hasCycle(definition)) issues.push(diagnostic('CYCLE', '流程存在有向环，请检查连线'))
  const fromStart = reachable(
    main.filter((node) => resolveEffectiveNodeType(node) === 'start').map((node) => node.id),
    adjacency(definition),
  )
  const toEnd = reachable(
    main.filter((node) => resolveEffectiveNodeType(node) === 'end').map((node) => node.id),
    adjacency(definition, true),
  )
  for (const node of main) {
    if (!fromStart.has(node.id))
      issues.push(diagnostic('UNREACHABLE_START', '节点未从开始节点连接', node.id))
    if (!toEnd.has(node.id))
      issues.push(diagnostic('UNREACHABLE_END', '节点没有通向结束节点的路径', node.id))
  }
  return issues
}

function nodePhase(node: WorkflowNode): string {
  return node.phase ?? 'main'
}

export function editorNode(node: WorkflowNode): WorkflowNode {
  const type = resolveEffectiveNodeType(node)
  return node.type === 'capability' && type !== 'capability'
    ? { ...node, type, config: node.configuration ?? {} }
    : node
}
export function restoreEditedNode(original: WorkflowNode, edited: WorkflowNode): WorkflowNode {
  if (original.type !== 'capability' || edited.type === 'capability') return edited
  return { ...edited, type: 'capability', config: original.config, configuration: edited.config }
}
