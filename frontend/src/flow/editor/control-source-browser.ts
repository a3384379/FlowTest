import type { WorkflowDefinition, WorkflowEdge, WorkflowNode, WorkflowRegion } from '../../lib/api'

export type ValueSource =
  | { kind: 'literal'; value: unknown }
  | { kind: 'variable'; scope: string; path: Array<string | number> }
  | { kind: 'node_output'; node_id: string; path: Array<string | number> }

export type SourceChoice = {
  key: string
  label: string
  source: ValueSource | null
  reason?: string
}

export function conditionStateSources(
  definition: WorkflowDefinition,
  node: WorkflowNode,
  phase: 'initial' | 'update',
): SourceChoice[] {
  const containing = definition.regions?.find((region) =>
    region.nodes.some((item) => item.id === node.id),
  )
  const body = definition.regions?.find(
    (region) => region.owner_node_id === node.id && region.role === 'body',
  )
  const graph = phase === 'initial' ? containing : body
  return [
    ...baseVariableChoices(definition),
    ...scopedVariableChoices(node, containing, body, phase),
    ...nodeOutputChoices(definition, node, graph, body, phase),
    ...outOfScopeChoices(definition.regions ?? [], graph),
  ]
}

function baseVariableChoices(definition: WorkflowDefinition): SourceChoice[] {
  return [
    ...(definition.runtime_inputs ?? []).map((input) =>
      variableChoice('runtime', input.name, `运行输入 · ${input.name}`),
    ),
    ...Object.keys(definition.variables).map((name) =>
      variableChoice('workflow', name, `工作流变量 · ${name}`),
    ),
  ]
}

function scopedVariableChoices(
  node: WorkflowNode,
  containing: WorkflowRegion | undefined,
  body: WorkflowRegion | undefined,
  phase: 'initial' | 'update',
): SourceChoice[] {
  const config = node.configuration ?? {}
  const inputs =
    phase === 'initial' ? containing?.inputs : { ...asRecord(config.inputs), ...body?.inputs }
  const choices = Object.keys(inputs ?? {}).map((name) =>
    variableChoice('input', name, `当前区域输入 · ${name}`),
  )
  if (phase === 'initial') {
    choices.push({
      key: 'state-before-start',
      label: '当前块状态 · 循环开始前尚未初始化',
      source: null,
      reason: '当前块状态尚未初始化，仅可在条件判断和每轮更新中读取',
    })
  } else {
    choices.push(
      ...Object.keys(asRecord(config.state)).map((name) =>
        variableChoice('state', name, `当前块状态 · ${name}`),
      ),
      ...['index', 'iteration'].map((name) => variableChoice('loop', name, `当前轮次 · ${name}`)),
    )
  }
  return choices
}

function nodeOutputChoices(
  definition: WorkflowDefinition,
  node: WorkflowNode,
  graph: WorkflowRegion | undefined,
  body: WorkflowRegion | undefined,
  phase: 'initial' | 'update',
): SourceChoice[] {
  const scope = graphContext(definition, graph)
  const guaranteed = guaranteedOutputs(scope, node.id, body, phase)
  return scope.nodes
    .filter((candidate) => candidate.id !== node.id && !['start', 'end'].includes(candidate.type))
    .map((candidate) => outputChoice(candidate, guaranteed.has(candidate.id), phase))
}

function graphContext(definition: WorkflowDefinition, graph: WorkflowRegion | undefined) {
  return {
    nodes: graph?.nodes ?? definition.nodes,
    edges: graph?.edges ?? definition.edges,
    entry: graph?.entry_node_id ?? definition.nodes.find((item) => item.type === 'start')?.id,
  }
}

function guaranteedOutputs(
  scope: ReturnType<typeof graphContext>,
  nodeId: string,
  body: WorkflowRegion | undefined,
  phase: 'initial' | 'update',
): Set<string> {
  return phase === 'initial'
    ? guaranteedBefore(scope.nodes, scope.edges, scope.entry, nodeId)
    : guaranteedBeforeAllExits(scope.nodes, scope.edges, scope.entry, body?.exit_node_ids ?? [])
}

function outputChoice(
  candidate: WorkflowNode,
  available: boolean,
  phase: 'initial' | 'update',
): SourceChoice {
  return {
    key: `output:${candidate.id}`,
    label: `节点输出 · ${candidate.name}`,
    source: available ? { kind: 'node_output', node_id: candidate.id, path: [] } : null,
    ...(!available
      ? { reason: phase === 'initial' ? '该节点可能尚未执行' : '该节点不是每条区域路径的必经步骤' }
      : {}),
  }
}

function outOfScopeChoices(
  regions: WorkflowRegion[],
  graph: WorkflowRegion | undefined,
): SourceChoice[] {
  return regions
    .filter((region) => region.id !== graph?.id)
    .flatMap((region) =>
      region.nodes
        .filter((candidate) => !['start', 'end'].includes(candidate.type))
        .map((candidate) => ({
          key: `outside:${region.id}:${candidate.id}`,
          label: `其他区域节点 · ${candidate.name}`,
          source: null,
          reason: '节点不在当前可见作用域',
        })),
    )
}

function variableChoice(scope: string, name: string, label: string): SourceChoice {
  return { key: `${scope}:${name}`, label, source: { kind: 'variable', scope, path: [name] } }
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function guaranteedBeforeAllExits(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  entry: string | null | undefined,
  exits: string[],
): Set<string> {
  if (!entry || !exits.length) return new Set()
  const reachable = reachableFrom(entry, edges)
  if (exits.some((exit) => !reachable.has(exit))) return new Set()
  const sets = exits.map((exit) => new Set([...guaranteedBefore(nodes, edges, entry, exit), exit]))
  return intersect(sets)
}

function guaranteedBefore(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  entry: string | null | undefined,
  target: string,
): Set<string> {
  if (!entry || !nodes.some((node) => node.id === target)) return new Set()
  const reachable = reachableFrom(entry, edges)
  if (!reachable.has(target)) return new Set()
  const dominators = computeDominators(reachable, edges, entry)
  const result = dominators.get(target)!
  result.delete(target)
  return result
}

function computeDominators(
  reachable: Set<string>,
  edges: WorkflowEdge[],
  entry: string,
): Map<string, Set<string>> {
  const predecessors = buildPredecessors(reachable, edges)
  const dominators = new Map(
    [...reachable].map((id) => [id, id === entry ? new Set([entry]) : new Set(reachable)]),
  )
  let changed = true
  while (changed) {
    changed = false
    for (const id of reachable) {
      if (id === entry) continue
      const parents = predecessors.get(id) ?? []
      const next = new Set([id, ...intersect(parents.map((parent) => dominators.get(parent)!))])
      const previous = dominators.get(id)!
      if (next.size === previous.size && [...next].every((item) => previous.has(item))) continue
      dominators.set(id, next)
      changed = true
    }
  }
  return dominators
}

function buildPredecessors(reachable: Set<string>, edges: WorkflowEdge[]): Map<string, string[]> {
  const predecessors = new Map<string, string[]>()
  for (const edge of edges) {
    if (!reachable.has(edge.source) || !reachable.has(edge.target)) continue
    predecessors.set(edge.target, [...(predecessors.get(edge.target) ?? []), edge.source])
  }
  return predecessors
}

function reachableFrom(entry: string, edges: WorkflowEdge[]): Set<string> {
  const reachable = new Set<string>()
  const pending = [entry]
  while (pending.length) {
    const current = pending.pop()!
    if (reachable.has(current)) continue
    reachable.add(current)
    pending.push(...edges.filter((edge) => edge.source === current).map((edge) => edge.target))
  }
  return reachable
}

function intersect(sets: Set<string>[]): Set<string> {
  if (!sets.length) return new Set()
  return new Set([...sets[0]].filter((value) => sets.every((set) => set.has(value))))
}
