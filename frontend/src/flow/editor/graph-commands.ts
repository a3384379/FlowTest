import type { WorkflowDefinition, WorkflowNode, WorkflowRegion } from '../../lib/api'
import { addControlBlock, descendantRegions } from './control-blocks'
import {
  adjacency,
  analyzeGraph,
  diagnostic,
  edgeIssues,
  effectiveConfig,
  reachable,
  resolveEffectiveNodeType,
} from './graph-analysis'
import type {
  EditDiagnostic,
  WorkflowSelection,
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
  issues.push(...controlReferenceIssues(node, deleted))
  if (deleted.size && node.bindings?.length)
    issues.push(
      diagnostic('BINDING_REVIEW', `“${node.name}”含表达式绑定，删除前请先明确处理其引用`, node.id),
    )
  if (
    deleted.size &&
    resolveEffectiveNodeType(node) === 'capability' &&
    !node.capability_id?.startsWith('flow.control.')
  )
    issues.push(
      diagnostic(
        'CAPABILITY_REVIEW',
        `“${node.name}”的引用无法完整静态分析，请先处理该能力节点`,
        node.id,
      ),
    )
  return issues
}

function controlReferenceIssues(node: WorkflowNode, deleted: Set<string>): EditDiagnostic[] {
  if (!node.capability_id?.startsWith('flow.control.')) return []
  if (!referencedNodeIds(node.configuration).some((id) => deleted.has(id))) return []
  return [diagnostic('NODE_REFERENCE', `“${node.name}”的控制配置仍引用待删除节点`, node.id)]
}

function referencedNodeIds(value: unknown): string[] {
  if (Array.isArray(value)) return value.flatMap(referencedNodeIds)
  if (!value || typeof value !== 'object') return []
  return Object.entries(value).flatMap(([key, item]) =>
    (key === 'node_id' || key === 'source_node_id' || key === 'target_node_id') &&
    typeof item === 'string'
      ? [item]
      : referencedNodeIds(item),
  )
}
export function planDeletion(
  definition: WorkflowDefinition,
  selection: WorkflowSelection,
): DeletionPlan {
  const selectedNodeId = selection?.kind === 'node' ? selection.id : null
  const mainEnds = definition.nodes.filter(
    (node) => node.phase !== 'cleanup' && resolveEffectiveNodeType(node) === 'end',
  )
  const protectedNodeIds = definition.nodes
    .filter(
      (node) =>
        selectedNodeId === node.id &&
        (resolveEffectiveNodeType(node) === 'start' ||
          (mainEnds.length === 1 && mainEnds[0].id === node.id)),
    )
    .map((node) => node.id)
  const protectedIds = new Set(protectedNodeIds)
  const deleteNodeIds = definition.nodes
    .filter((node) => selectedNodeId === node.id && !protectedIds.has(node.id))
    .map((node) => node.id)
  const deleted = new Set(deleteNodeIds)
  const edges = definition.edges.filter(
    (edge) =>
      (selection?.kind === 'edge' && selection.id === edge.id) ||
      deleted.has(edge.source) ||
      deleted.has(edge.target),
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
      mappingCount > 0 || edges.some((edge) => edge.condition != null) || deleteNodeIds.length > 1,
  }
}
export function applyDeletion(definition: WorkflowDefinition, plan: DeletionPlan): GraphEditResult {
  if (plan.references.length) return { kind: 'blocked', diagnostics: plan.references }
  if (!plan.deleteNodeIds.length && !plan.deleteEdgeIds.length) return { kind: 'unchanged' }
  const removedRegions = new Set(
    descendantRegions(definition, [...plan.deleteNodeIds]).map((region) => region.id),
  )
  return {
    kind: 'changed',
    diagnostics: [],
    definition: {
      ...definition,
      nodes: definition.nodes.filter((node) => !plan.deleteNodeIds.includes(node.id)),
      edges: definition.edges.filter((edge) => !plan.deleteEdgeIds.includes(edge.id)),
      regions: (definition.regions ?? []).filter((region) => !removedRegions.has(region.id)),
    },
  }
}

export function wrapMainNode(
  definition: WorkflowDefinition,
  nodeId: string,
  kind: 'group' | 'foreach',
): GraphEditResult {
  const node = definition.nodes.find((item) => item.id === nodeId)
  if (!node) return { kind: 'unchanged' }
  const incoming = definition.edges.filter((edge) => edge.target === nodeId)
  const outgoing = definition.edges.filter((edge) => edge.source === nodeId)
  const issues = wrapIssues(definition, node, incoming, outgoing)
  if (issues.length) return { kind: 'blocked', diagnostics: issues }

  const expanded = addControlBlock(definition, kind)
  const owner = expanded.nodes.at(-1)!
  const region = expanded.regions!.find((item) => item.owner_node_id === owner.id)!
  const wrapped = { ...node, position: { x: 0, y: 0 } }
  return {
    kind: 'changed',
    diagnostics: [],
    definition: {
      ...expanded,
      nodes: expanded.nodes
        .filter((item) => item.id !== nodeId)
        .map((item) => (item.id === owner.id ? { ...item, position: node.position } : item)),
      edges: expanded.edges.map((edge) => ({
        ...edge,
        source: edge.source === nodeId ? owner.id : edge.source,
        target: edge.target === nodeId ? owner.id : edge.target,
      })),
      regions: expanded.regions!.map((item) =>
        item.id === region.id
          ? { ...item, nodes: [wrapped], entry_node_id: nodeId, exit_node_ids: [nodeId] }
          : item,
      ),
    },
  }
}

export function wrapMainPath(
  definition: WorkflowDefinition,
  nodeIds: string[],
  kind: 'group' | 'foreach',
): GraphEditResult {
  const selected = new Set(nodeIds)
  if (nodeIds.length < 2 || selected.size !== nodeIds.length)
    return {
      kind: 'blocked',
      diagnostics: [diagnostic('WRAP_SELECTION', '请选取至少两个连续步骤')],
    }
  const nodes = nodeIds.map((id) => definition.nodes.find((node) => node.id === id))
  if (nodes.some((node) => !node))
    return { kind: 'blocked', diagnostics: [diagnostic('WRAP_SELECTION', '所选步骤已不存在')] }
  const issues = wrapPathIssues(definition, nodeIds, nodes as WorkflowNode[])
  if (issues.length) return { kind: 'blocked', diagnostics: issues }

  const expanded = addControlBlock(definition, kind)
  const owner = expanded.nodes.at(-1)!
  const region = expanded.regions!.find((item) => item.owner_node_id === owner.id)!
  const first = nodes[0]!
  const internalEdges = definition.edges.filter(
    (edge) => selected.has(edge.source) && selected.has(edge.target),
  )
  return {
    kind: 'changed',
    diagnostics: [],
    definition: {
      ...expanded,
      nodes: expanded.nodes
        .filter((node) => !selected.has(node.id))
        .map((node) => (node.id === owner.id ? { ...node, position: first.position } : node)),
      edges: expanded.edges
        .filter((edge) => !(selected.has(edge.source) && selected.has(edge.target)))
        .map((edge) => ({
          ...edge,
          source: edge.source === nodeIds.at(-1) ? owner.id : edge.source,
          target: edge.target === nodeIds[0] ? owner.id : edge.target,
        })),
      regions: expanded.regions!.map((item) =>
        item.id === region.id
          ? {
              ...item,
              nodes: (nodes as WorkflowNode[]).map((node) => ({
                ...node,
                position: {
                  x: node.position.x - first.position.x,
                  y: node.position.y - first.position.y,
                },
              })),
              edges: internalEdges,
              entry_node_id: nodeIds[0],
              exit_node_ids: [nodeIds.at(-1)!],
            }
          : item,
      ),
    },
  }
}

function wrapPathIssues(
  definition: WorkflowDefinition,
  nodeIds: string[],
  nodes: WorkflowNode[],
): EditDiagnostic[] {
  return nodes.flatMap((node, index) => [
    ...wrapNodeIssues(node),
    ...wrapReferenceIssues(definition, node),
    ...wrapPathBoundaryIssues(definition, nodeIds, node, index),
  ])
}

function wrapPathBoundaryIssues(
  definition: WorkflowDefinition,
  nodeIds: string[],
  node: WorkflowNode,
  index: number,
): EditDiagnostic[] {
  const incoming = definition.edges.filter((edge) => edge.target === node.id)
  const outgoing = definition.edges.filter((edge) => edge.source === node.id)
  const issues = wrapBoundaryIssues(node, incoming, outgoing)
  issues.push(...wrapPathConnectionIssues(nodeIds, node, index, incoming[0], outgoing[0]))
  issues.push(...wrapPathOuterIssues(nodeIds, node, index, incoming[0], outgoing[0]))
  return issues
}

function wrapPathConnectionIssues(
  nodeIds: string[],
  node: WorkflowNode,
  index: number,
  incoming: WorkflowDefinition['edges'][number] | undefined,
  outgoing: WorkflowDefinition['edges'][number] | undefined,
): EditDiagnostic[] {
  const issues: EditDiagnostic[] = []
  if (index > 0 && !hasPreviousPathEdge(nodeIds, index, incoming))
    issues.push(diagnostic('WRAP_BOUNDARY', `“${node.name}”没有来自前一步的普通连线`, node.id))
  if (index < nodeIds.length - 1 && !hasNextPathEdge(nodeIds, index, outgoing))
    issues.push(diagnostic('WRAP_BOUNDARY', `“${node.name}”没有通向后一步的普通连线`, node.id))
  return issues
}

function hasPreviousPathEdge(
  nodeIds: string[],
  index: number,
  edge: WorkflowDefinition['edges'][number] | undefined,
): boolean {
  return edge?.source === nodeIds[index - 1] && edge.condition === null
}

function hasNextPathEdge(
  nodeIds: string[],
  index: number,
  edge: WorkflowDefinition['edges'][number] | undefined,
): boolean {
  return edge?.target === nodeIds[index + 1] && edge.condition === null
}

function wrapPathOuterIssues(
  nodeIds: string[],
  node: WorkflowNode,
  index: number,
  incoming: WorkflowDefinition['edges'][number] | undefined,
  outgoing: WorkflowDefinition['edges'][number] | undefined,
): EditDiagnostic[] {
  const issues: EditDiagnostic[] = []
  if (index === 0 && incoming && nodeIds.includes(incoming.source))
    issues.push(diagnostic('WRAP_BOUNDARY', '入口不能来自选中区域内部', node.id))
  if (index === nodeIds.length - 1 && outgoing && nodeIds.includes(outgoing.target))
    issues.push(diagnostic('WRAP_BOUNDARY', '出口不能返回选中区域内部', node.id))
  return issues
}

export function unwrapSingleNode(definition: WorkflowDefinition, ownerId: string): GraphEditResult {
  const owner = definition.nodes.find((node) => node.id === ownerId)
  if (!owner) return { kind: 'unchanged' }
  const region = definition.regions?.find((item) => item.owner_node_id === ownerId)
  const issues = unwrapIssues(definition, owner, region)
  if (issues.length) return { kind: 'blocked', diagnostics: issues }
  const child = region!.nodes[0]
  return {
    kind: 'changed',
    diagnostics: [],
    definition: {
      ...definition,
      nodes: definition.nodes.map((node) =>
        node.id === ownerId ? { ...child, position: owner.position } : node,
      ),
      edges: definition.edges.map((edge) => ({
        ...edge,
        source: edge.source === ownerId ? child.id : edge.source,
        target: edge.target === ownerId ? child.id : edge.target,
      })),
      regions: definition.regions?.filter((item) => item.id !== region!.id),
    },
  }
}

export function unwrapMainPath(definition: WorkflowDefinition, ownerId: string): GraphEditResult {
  const owner = definition.nodes.find((node) => node.id === ownerId)
  const region = definition.regions?.find((item) => item.owner_node_id === ownerId)
  if (!owner || !region || owner.capability_id !== 'flow.control.group' || region.nodes.length < 2)
    return {
      kind: 'blocked',
      diagnostics: [diagnostic('UNWRAP_STRUCTURE', '仅支持拆解含多个线性步骤的步骤组', ownerId)],
    }
  const order = orderedRegionPath(region)
  const incoming = definition.edges.filter((edge) => edge.target === ownerId)
  const outgoing = definition.edges.filter((edge) => edge.source === ownerId)
  const issues = [
    ...unwrapRegionIssues(definition, owner, region),
    ...unwrapGraphIssues(definition, owner),
    ...unwrapPathIssues(definition, owner, region, order, incoming, outgoing),
  ]
  if (issues.length) return { kind: 'blocked', diagnostics: issues }
  const firstId = order[0]!
  const lastId = order.at(-1)!
  const next: WorkflowDefinition = {
    ...definition,
    nodes: [
      ...definition.nodes.filter((node) => node.id !== ownerId),
      ...region.nodes.map((node) => ({
        ...node,
        position: {
          x: node.position.x + owner.position.x,
          y: node.position.y + owner.position.y,
        },
      })),
    ],
    edges: [
      ...definition.edges.map((edge) => ({
        ...edge,
        source: edge.source === ownerId ? lastId : edge.source,
        target: edge.target === ownerId ? firstId : edge.target,
      })),
      ...region.edges,
    ],
    regions: definition.regions?.filter((item) => item.id !== region.id),
  }
  const graphIssues = analyzeGraph(next)
  return graphIssues.length
    ? { kind: 'blocked', diagnostics: graphIssues }
    : { kind: 'changed', diagnostics: [], definition: next }
}

function orderedRegionPath(region: WorkflowRegion): string[] {
  const order: string[] = []
  let current = region.entry_node_id
  while (current && !order.includes(current)) {
    order.push(current)
    const next = region.edges.filter((edge) => edge.source === current)
    current = next.length === 1 ? next[0].target : null
  }
  return order
}

function unwrapPathIssues(
  definition: WorkflowDefinition,
  owner: WorkflowNode,
  region: WorkflowRegion,
  order: string[],
  incoming: WorkflowDefinition['edges'],
  outgoing: WorkflowDefinition['edges'],
): EditDiagnostic[] {
  const linear = isPlainLinearPath(region, order)
  const boundaries = hasPlainOuterEdges(incoming, outgoing)
  const ownerIsPlain = isPlainGroup(owner, region)
  const externalReference = hasExternalPathReference(definition, owner, region)
  const issues: EditDiagnostic[] = []
  if (!linear || !ownerIsPlain)
    issues.push(diagnostic('UNWRAP_STRUCTURE', '步骤组必须是无嵌套、无映射的线性主路径', owner.id))
  if (!boundaries)
    issues.push(diagnostic('UNWRAP_BOUNDARY', '步骤组需要一条普通入边和一条普通出边', owner.id))
  if (externalReference)
    issues.push(diagnostic('UNWRAP_REFERENCE', '其他节点仍引用区域步骤，不能直接拆解', owner.id))
  return issues
}

function isPlainLinearPath(region: WorkflowRegion, order: string[]): boolean {
  return (
    order.length === region.nodes.length &&
    region.edges.length === region.nodes.length - 1 &&
    region.exit_node_ids.length === 1 &&
    region.exit_node_ids[0] === order.at(-1) &&
    region.edges.every((edge) => edge.condition === null && !edge.mappings.length) &&
    region.nodes.every(isPlainWrappedStep)
  )
}

function isPlainWrappedStep(node: WorkflowNode): boolean {
  return (
    !unsupportedWrapType(node) &&
    !referencedNodeIds(effectiveConfig(node)).length &&
    !node.bindings?.length &&
    (!node.run_when || node.run_when === 'always') &&
    !node.cleanup_for?.length &&
    !node.best_effort
  )
}

function hasPlainOuterEdges(
  incoming: WorkflowDefinition['edges'],
  outgoing: WorkflowDefinition['edges'],
): boolean {
  return (
    incoming.length === 1 &&
    outgoing.length === 1 &&
    [...incoming, ...outgoing].every((edge) => edge.condition === null && !edge.mappings.length)
  )
}

function isPlainGroup(owner: WorkflowNode, region: WorkflowRegion): boolean {
  return (
    region.role === 'body' &&
    hasInlineBody(owner, region.id) &&
    !owner.bindings?.length &&
    owner.phase !== 'cleanup' &&
    (!owner.run_when || owner.run_when === 'always') &&
    !owner.cleanup_for?.length &&
    !owner.best_effort
  )
}

function hasInlineBody(owner: WorkflowNode, regionId: string): boolean {
  const body = owner.configuration?.body
  return (
    typeof body === 'object' &&
    body !== null &&
    'kind' in body &&
    body.kind === 'inline' &&
    'region_id' in body &&
    body.region_id === regionId
  )
}

function hasExternalPathReference(
  definition: WorkflowDefinition,
  owner: WorkflowNode,
  region: WorkflowRegion,
): boolean {
  const childIds = new Set(region.nodes.map((node) => node.id))
  return [
    ...definition.nodes.filter((node) => node.id !== owner.id),
    ...(definition.regions ?? [])
      .filter((item) => item.id !== region.id)
      .flatMap((item) => item.nodes),
  ].some(
    (node) =>
      referencedNodeIds(effectiveConfig(node)).some((id) => childIds.has(id)) ||
      node.cleanup_for?.some((id) => childIds.has(id)) ||
      node.bindings?.some((binding) => [...childIds].some((id) => binding.expression.includes(id))),
  )
}

function unwrapIssues(
  definition: WorkflowDefinition,
  owner: WorkflowNode,
  region: WorkflowRegion | undefined,
): EditDiagnostic[] {
  if (
    !['flow.control.group', 'flow.control.foreach', 'flow.control.repeat'].includes(
      owner.capability_id ?? '',
    ) ||
    !region ||
    region.nodes.length !== 1 ||
    region.edges.length > 0
  )
    return [diagnostic('UNWRAP_STRUCTURE', '仅支持拆解单步骤的步骤组或循环', owner.id)]
  return [...unwrapRegionIssues(definition, owner, region), ...unwrapGraphIssues(definition, owner)]
}

function unwrapRegionIssues(
  definition: WorkflowDefinition,
  owner: WorkflowNode,
  region: WorkflowRegion,
): EditDiagnostic[] {
  const issues: EditDiagnostic[] = []
  if (
    descendantRegions(
      definition,
      region.nodes.map((node) => node.id),
    ).length
  )
    issues.push(diagnostic('UNWRAP_NESTED', '区域内仍有嵌套控制块，不能直接拆解', owner.id))
  if (hasEntries(region.inputs) || hasEntries(owner.configuration?.inputs))
    issues.push(diagnostic('UNWRAP_INPUTS', '区域使用显式输入，请先处理输入绑定', owner.id))
  const collect = owner.configuration?.collect
  if (hasEntries(region.outputs) || hasEntries(collect))
    issues.push(diagnostic('UNWRAP_OUTPUTS', '控制块声明了输出汇总，请先处理这些输出', owner.id))
  return issues
}

function hasEntries(value: unknown): boolean {
  return !!value && typeof value === 'object' && Object.keys(value).length > 0
}

function unwrapGraphIssues(definition: WorkflowDefinition, owner: WorkflowNode): EditDiagnostic[] {
  const issues: EditDiagnostic[] = []
  if (
    definition.edges.some(
      (edge) => (edge.source === owner.id || edge.target === owner.id) && edge.mappings.length > 0,
    )
  )
    issues.push(diagnostic('UNWRAP_MAPPING', '控制块连线含字段映射，请先处理映射', owner.id))
  if (
    [...definition.nodes, ...(definition.regions ?? []).flatMap((region) => region.nodes)].some(
      (node) =>
        node.id !== owner.id &&
        (referencedNodeIds(effectiveConfig(node)).includes(owner.id) ||
          node.cleanup_for?.includes(owner.id) ||
          node.bindings?.some((binding) => binding.expression.includes(owner.id))),
    )
  )
    issues.push(diagnostic('UNWRAP_REFERENCE', '其他节点仍引用控制块，请先处理引用', owner.id))
  return issues
}

function wrapIssues(
  definition: WorkflowDefinition,
  node: WorkflowNode,
  incoming: WorkflowDefinition['edges'],
  outgoing: WorkflowDefinition['edges'],
): EditDiagnostic[] {
  return [
    ...wrapNodeIssues(node),
    ...wrapBoundaryIssues(node, incoming, outgoing),
    ...wrapReferenceIssues(definition, node),
  ]
}

function wrapNodeIssues(node: WorkflowNode): EditDiagnostic[] {
  const issues: EditDiagnostic[] = []
  if (unsupportedWrapType(node))
    issues.push(diagnostic('WRAP_NODE_UNSUPPORTED', `“${node.name}”当前不能直接包装`, node.id))
  if (referencedNodeIds(effectiveConfig(node)).length || node.bindings?.length)
    issues.push(
      diagnostic('WRAP_INPUT_REFERENCE', `“${node.name}”引用区域外节点，请先声明区域输入`, node.id),
    )
  return issues
}

function unsupportedWrapType(node: WorkflowNode): boolean {
  return Boolean(
    node.phase === 'cleanup' ||
    node.capability_id ||
    ['start', 'end', 'condition', 'dataset', 'for_each', 'subflow'].includes(
      resolveEffectiveNodeType(node),
    ),
  )
}

function wrapBoundaryIssues(
  node: WorkflowNode,
  incoming: WorkflowDefinition['edges'],
  outgoing: WorkflowDefinition['edges'],
): EditDiagnostic[] {
  const issues: EditDiagnostic[] = []
  if (incoming.length !== 1 || outgoing.length !== 1)
    issues.push(
      diagnostic(
        'WRAP_BOUNDARY',
        `“${node.name}”需要恰好一条入边和一条出边；当前入边 ${incoming.length} 条、出边 ${outgoing.length} 条`,
        node.id,
      ),
    )
  for (const edge of [...incoming, ...outgoing])
    if (edge.mappings.length)
      issues.push(
        diagnostic(
          'WRAP_MAPPING',
          `连线 ${edge.id} 含字段映射，请先显式改为区域输入/输出`,
          node.id,
          edge.id,
        ),
      )
  return issues
}

function wrapReferenceIssues(definition: WorkflowDefinition, node: WorkflowNode): EditDiagnostic[] {
  const issues: EditDiagnostic[] = []
  for (const other of definition.nodes.filter((item) => item.id !== node.id))
    if (
      referencedNodeIds(effectiveConfig(other)).includes(node.id) ||
      other.cleanup_for?.includes(node.id) ||
      other.bindings?.some((binding) => binding.expression.includes(node.id))
    )
      issues.push(
        diagnostic(
          'WRAP_OUTPUT_REFERENCE',
          `“${other.name}”仍引用 ${node.name}，请先声明区域输出`,
          other.id,
        ),
      )
  return issues
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
