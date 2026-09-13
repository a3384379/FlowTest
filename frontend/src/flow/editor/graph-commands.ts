import type { WorkflowDefinition, WorkflowNode } from '../../lib/api'
import {
  adjacency,
  diagnostic,
  edgeIssues,
  effectiveConfig,
  reachable,
  resolveEffectiveNodeType,
} from './graph-analysis'
import type {
  EditDiagnostic,
  EditorSelection,
  GraphConnectionInput,
  GraphEditResult,
  NodePositionUpdate,
} from './editor-types'

export type DeletionPlan = {
  deleteNodeIds: readonly string[]
  deleteEdgeIds: readonly string[]
  protectedNodeIds: readonly string[]
  mappingCount: number
  references: readonly EditDiagnostic[]
  requiresConfirmation: boolean
}
function retainedReferences(node: WorkflowNode, deleted: Set<string>): EditDiagnostic[] {
  const config = effectiveConfig(node)
  const ids = [config.source_node_id, config.expected_source_node_id, ...(node.cleanup_for ?? [])]
  const references = ids.filter((id): id is string => typeof id === 'string' && deleted.has(id))
  const issues = references.map((id) =>
    diagnostic('NODE_REFERENCE', `“${node.name}”仍引用节点 ${id}，请先修改来源或清理范围`, node.id),
  )
  if (deleted.size && node.bindings?.length)
    issues.push(
      diagnostic('BINDING_REVIEW', `“${node.name}”含表达式绑定，删除前请先明确处理其引用`, node.id),
    )
  if (deleted.size && resolveEffectiveNodeType(node) === 'capability')
    issues.push(
      diagnostic(
        'CAPABILITY_REVIEW',
        `“${node.name}”的引用无法完整静态分析，请先处理该能力节点`,
        node.id,
      ),
    )
  return issues
}
export function planDeletion(
  definition: WorkflowDefinition,
  selection: EditorSelection,
): DeletionPlan {
  const selected = new Set(selection.nodeIds)
  const mainEnds = definition.nodes.filter(
    (node) => node.phase !== 'cleanup' && resolveEffectiveNodeType(node) === 'end',
  )
  const protectedNodeIds = definition.nodes
    .filter(
      (node) =>
        selected.has(node.id) &&
        (resolveEffectiveNodeType(node) === 'start' ||
          (mainEnds.length === 1 && mainEnds[0].id === node.id)),
    )
    .map((node) => node.id)
  const protectedIds = new Set(protectedNodeIds)
  const deleteNodeIds = definition.nodes
    .filter((node) => selected.has(node.id) && !protectedIds.has(node.id))
    .map((node) => node.id)
  const deleted = new Set(deleteNodeIds)
  const edges = definition.edges.filter(
    (edge) =>
      selection.edgeIds.includes(edge.id) || deleted.has(edge.source) || deleted.has(edge.target),
  )
  const mappingCount = edges.reduce((count, edge) => count + edge.mappings.length, 0)
  return {
    deleteNodeIds,
    deleteEdgeIds: edges.map((edge) => edge.id),
    protectedNodeIds,
    mappingCount,
    references: definition.nodes
      .filter((node) => !deleted.has(node.id))
      .flatMap((node) => retainedReferences(node, deleted)),
    requiresConfirmation:
      mappingCount > 0 ||
      edges.some((edge) => edge.condition != null) ||
      deleteNodeIds.length > 1 ||
      selection.edgeIds.length > 1,
  }
}
export function applyDeletion(definition: WorkflowDefinition, plan: DeletionPlan): GraphEditResult {
  if (plan.references.length) return { kind: 'blocked', diagnostics: plan.references }
  if (!plan.deleteNodeIds.length && !plan.deleteEdgeIds.length) return { kind: 'unchanged' }
  return {
    kind: 'changed',
    diagnostics: [],
    definition: {
      ...definition,
      nodes: definition.nodes.filter((node) => !plan.deleteNodeIds.includes(node.id)),
      edges: definition.edges.filter((edge) => !plan.deleteEdgeIds.includes(edge.id)),
    },
  }
}
export function connectGraphNodes(
  definition: WorkflowDefinition,
  input: GraphConnectionInput,
): GraphEditResult {
  const edge = {
    id: input.edgeId,
    source: input.sourceId,
    target: input.targetId,
    condition: input.branch,
    mappings: [],
  }
  const issues = edgeIssues(edge, new Map(definition.nodes.map((node) => [node.id, node])))
  const source = definition.nodes.find((node) => node.id === input.sourceId)
  if (source && resolveEffectiveNodeType(source) === 'condition' && !input.branch)
    issues.push(diagnostic('BRANCH_REQUIRED', '请从条件节点的真或假出口连接', source.id))
  const duplicate = definition.edges.some(
    (item) =>
      item.source === input.sourceId &&
      item.condition === input.branch &&
      (item.target === input.targetId || input.branch !== null),
  )
  if (duplicate || definition.edges.some((item) => item.id === input.edgeId))
    issues.push(diagnostic('DUPLICATE_EDGE', '连线或条件分支已经存在'))
  if (reachable([input.targetId], adjacency(definition)).has(input.sourceId))
    issues.push(diagnostic('CYCLE', '这条连线会形成有向环'))
  if (input.edgeId.length > 128 || !input.edgeId)
    issues.push(diagnostic('INVALID_EDGE_ID', '连线标识长度不合法'))
  if (issues.length) return { kind: 'blocked', diagnostics: issues }
  return {
    kind: 'changed',
    definition: { ...definition, edges: [...definition.edges, edge] },
    diagnostics: [],
  }
}
export function reconnectGraphEdge(
  definition: WorkflowDefinition,
  edgeId: string,
  input: GraphConnectionInput,
): GraphEditResult {
  const original = definition.edges.find((edge) => edge.id === edgeId)
  if (!original) return { kind: 'unchanged' }
  if (
    original.source === input.sourceId &&
    original.target === input.targetId &&
    original.condition === input.branch
  )
    return { kind: 'unchanged' }
  const result = connectGraphNodes(
    { ...definition, edges: definition.edges.filter((edge) => edge.id !== edgeId) },
    { ...input, edgeId },
  )
  if (result.kind !== 'changed') return result
  const replacement = {
    ...original,
    source: input.sourceId,
    target: input.targetId,
    condition: input.branch,
    mappings: original.mappings.map((mapping) => ({
      ...mapping,
      source: { ...mapping.source, node_id: input.sourceId },
      target: { ...mapping.target, node_id: input.targetId },
    })),
  }
  return {
    kind: 'changed',
    diagnostics: [],
    definition: {
      ...definition,
      edges: definition.edges.map((edge) => (edge.id === edgeId ? replacement : edge)),
    },
  }
}
export function applyNodePositions(
  definition: WorkflowDefinition,
  updates: readonly NodePositionUpdate[],
): GraphEditResult {
  if (
    updates.some(
      (update) => !Number.isFinite(update.position.x) || !Number.isFinite(update.position.y),
    )
  )
    return {
      kind: 'blocked',
      diagnostics: [diagnostic('INVALID_POSITION', '节点坐标必须为有限数值')],
    }
  const positions = new Map(updates.map((update) => [update.id, update.position]))
  let changed = false
  const nodes = definition.nodes.map((node) => {
    const position = positions.get(node.id)
    if (!position || (position.x === node.position.x && position.y === node.position.y)) return node
    changed = true
    return { ...node, position: { ...position } }
  })
  return changed
    ? { kind: 'changed', definition: { ...definition, nodes }, diagnostics: [] }
    : { kind: 'unchanged' }
}
export function swapBranches(definition: WorkflowDefinition, sourceId: string): GraphEditResult {
  const branches = definition.edges.filter((edge) => edge.source === sourceId)
  if (
    branches.length !== 2 ||
    !branches.some((edge) => edge.condition === 'true') ||
    !branches.some((edge) => edge.condition === 'false')
  )
    return { kind: 'unchanged' }
  return {
    kind: 'changed',
    diagnostics: [],
    definition: {
      ...definition,
      edges: definition.edges.map((edge) =>
        edge.source === sourceId
          ? { ...edge, condition: edge.condition === 'true' ? 'false' : 'true' }
          : edge,
      ),
    },
  }
}
