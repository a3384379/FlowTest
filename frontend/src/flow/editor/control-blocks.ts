import type { WorkflowDefinition, WorkflowEdge, WorkflowNode, WorkflowRegion } from '../../lib/api'

export type ControlBlockKind =
  | 'foreach'
  | 'repeat'
  | 'if'
  | 'switch'
  | 'while'
  | 'do_while'
  | 'until'
  | 'parallel'
  | 'try'
  | 'group'
  | 'fail'
  | 'return'

function region(ownerId: string, role: string): WorkflowRegion {
  const id = `region-${crypto.randomUUID()}`
  const stepId = `step-${crypto.randomUUID()}`
  return {
    id,
    owner_node_id: ownerId,
    role,
    nodes: [
      {
        id: stepId,
        type: 'delay',
        name: '等待 0 秒',
        position: { x: 0, y: 0 },
        config: { seconds: 0 },
      },
    ],
    edges: [],
    entry_node_id: stepId,
    exit_node_ids: [stepId],
    inputs: {},
    outputs: {},
  }
}

function body(item: WorkflowRegion) {
  return { kind: 'inline', region_id: item.id }
}

function condition() {
  return {
    kind: 'compare',
    left: { kind: 'literal', value: true },
    operator: 'equals',
    right: { kind: 'literal', value: true },
  }
}

function configuration(kind: ControlBlockKind, regions: WorkflowRegion[]): Record<string, unknown> {
  if (kind === 'foreach') {
    return {
      collection: { kind: 'literal', value: [1, 2, 3] },
      body: body(regions[0]),
      inputs: {},
      policy: { concurrency: 1, max_iterations: 1000, timeout_seconds: 120, on_error: 'stop' },
    }
  }
  if (kind === 'repeat') return { count: 3, body: body(regions[0]), inputs: {} }
  if (kind === 'if') {
    return {
      condition: condition(),
      true_body: body(regions[0]),
      false_body: body(regions[1]),
      inputs: {},
    }
  }
  if (isConditionLoop(kind)) {
    return conditionLoopConfiguration(kind, regions[0])
  }
  if (kind === 'parallel') {
    return {
      branches: [
        { id: 'first', label: '分支一', body: body(regions[0]) },
        { id: 'second', label: '分支二', body: body(regions[1]) },
      ],
      join: 'all',
      inputs: {},
      policy: { concurrency: 2, timeout_seconds: 120, on_error: 'stop_on_error' },
    }
  }
  if (kind === 'try') {
    return {
      try_body: body(regions[0]),
      catches: [
        { id: 'known', label: '已知错误', error_codes: ['CASE_FAIL'], body: body(regions[1]) },
      ],
      finally_body: body(regions[2]),
      expected_error_codes: [],
      inputs: {},
    }
  }
  if (kind === 'group') return { body: body(regions[0]), inputs: {} }
  if (kind === 'fail') return { code: 'CASE_FAIL', message: '主动标记失败' }
  if (kind === 'return') return { outputs: {} }
  return {
    mode: 'value',
    value: { kind: 'literal', value: 'first' },
    branches: [
      {
        id: 'first',
        label: '分支一',
        match: { kind: 'literal', value: 'first' },
        body: body(regions[0]),
      },
      {
        id: 'second',
        label: '分支二',
        match: { kind: 'literal', value: 'second' },
        body: body(regions[1]),
      },
    ],
    default: { behavior: 'run', body: body(regions[2]) },
    inputs: {},
  }
}

function isConditionLoop(kind: ControlBlockKind): kind is 'while' | 'do_while' | 'until' {
  return kind === 'while' || kind === 'do_while' || kind === 'until'
}

function conditionLoopConfiguration(kind: 'while' | 'do_while' | 'until', region: WorkflowRegion) {
  return {
    condition: {
      kind: 'compare',
      left: { kind: 'literal', value: kind === 'until' },
      operator: 'equals',
      right: { kind: 'literal', value: true },
    },
    body: body(region),
    inputs: {},
    state: {},
    update: {},
    policy: { concurrency: 1, max_iterations: 3, timeout_seconds: 120, on_error: 'stop' },
  }
}

const roles: Record<ControlBlockKind, string[]> = {
  foreach: ['body'],
  repeat: ['body'],
  if: ['true', 'false'],
  switch: ['case:first', 'case:second', 'default'],
  while: ['body'],
  do_while: ['body'],
  until: ['body'],
  parallel: ['branch:first', 'branch:second'],
  try: ['try', 'catch:known', 'finally'],
  group: ['body'],
  fail: [],
  return: [],
}

const labels: Record<ControlBlockKind, string> = {
  foreach: '集合遍历',
  repeat: '重复次数',
  if: '条件判断',
  switch: '多分支判断',
  while: '条件循环',
  do_while: '先执行后判断',
  until: '直到满足条件',
  parallel: '并行执行',
  try: '异常处理',
  group: '步骤组',
  fail: '主动失败',
  return: '返回调用方',
}

export function controlCapabilityLabel(capabilityId: string | undefined): string | null {
  if (!capabilityId?.startsWith('flow.control.')) return null
  const kind = capabilityId.slice('flow.control.'.length) as ControlBlockKind
  return labels[kind] ?? '控制块'
}

export function addControlBlock(
  definition: WorkflowDefinition,
  kind: ControlBlockKind,
): WorkflowDefinition {
  const id = `control-${crypto.randomUUID()}`
  const regions = roles[kind].map((role) => region(id, role))
  const node: WorkflowNode = {
    id,
    type: 'capability',
    name: labels[kind],
    position: { x: Math.max(0, ...definition.nodes.map((item) => item.position.x)) + 220, y: 120 },
    config: {},
    capability_id: `flow.control.${kind}`,
    capability_version: '1.0.0',
    configuration: configuration(kind, regions),
    bindings: [],
  }
  return {
    ...definition,
    schema_version: '4.0',
    run_policy: controlRunPolicy(definition, kind),
    nodes: [...definition.nodes, node],
    regions: [...(definition.regions ?? []), ...regions],
  }
}

export function addSwitchBranch(
  definition: WorkflowDefinition,
  nodeId: string,
): WorkflowDefinition | null {
  const context = switchContext(definition, nodeId)
  if (!context || context.branches.length >= 100) return null
  const { config, branches } = context
  if (!['value', 'rules'].includes(String(config.mode))) return null
  const branchId = `case-${crypto.randomUUID()}`
  const branchRegion = region(nodeId, `case:${branchId}`)
  const branch = {
    id: branchId,
    label: `分支 ${branches.length + 1}`,
    body: body(branchRegion),
    ...(config.mode === 'value'
      ? { match: { kind: 'literal', value: branchId } }
      : { condition: { ...condition(), left: { kind: 'literal', value: false } } }),
  }
  const updated = replaceControlConfiguration(definition, nodeId, {
    ...config,
    branches: [...branches, branch],
  })
  return { ...updated, regions: [...(updated.regions ?? []), branchRegion] }
}

export function removeSwitchBranch(
  definition: WorkflowDefinition,
  nodeId: string,
  branchId: string,
): WorkflowDefinition | null {
  const context = switchContext(definition, nodeId)
  if (!context || context.branches.length <= 1) return null
  const { config, branches } = context
  const branch = branches.map(asRecord).find((item) => item?.id === branchId)
  const bodyId = asRecord(branch?.body)?.region_id
  const owned = definition.regions?.find(
    (item) =>
      item.id === bodyId && item.owner_node_id === nodeId && item.role === `case:${branchId}`,
  )
  if (!owned) return null
  const removedIds = regionTreeIds(definition, owned)
  const updated = replaceControlConfiguration(definition, nodeId, {
    ...config,
    branches: branches.filter((current) => asRecord(current)?.id !== branchId),
  })
  return { ...updated, regions: updated.regions?.filter((item) => !removedIds.has(item.id)) }
}

export function setSwitchDefaultBehavior(
  definition: WorkflowDefinition,
  nodeId: string,
  behavior: 'run' | 'skip' | 'fail',
): WorkflowDefinition | null {
  const context = switchContext(definition, nodeId)
  if (!context) return null
  const { config } = context
  const current = asRecord(config.default)
  if (!current) return null
  if (current.behavior === behavior) return definition
  const existing = ownedDefaultRegion(definition, nodeId, current)
  if (current.behavior === 'run' && !existing && asRecord(current.body)?.kind === 'inline')
    return null
  const created = behavior === 'run' ? region(nodeId, 'default') : null
  const updated = replaceControlConfiguration(definition, nodeId, {
    ...config,
    default: { behavior, body: created ? body(created) : null },
  })
  return { ...updated, regions: updatedDefaultRegions(updated, existing, created) }
}

export function addTryCatch(
  definition: WorkflowDefinition,
  nodeId: string,
): WorkflowDefinition | null {
  const context = tryContext(definition, nodeId)
  if (!context || context.catches.length >= 20) return null
  const catchId = `catch-${crypto.randomUUID()}`
  const catchRegion = region(nodeId, `catch:${catchId}`)
  const existingCodes = new Set(
    context.catches.flatMap((item) => {
      const codes = asRecord(item)?.error_codes
      return Array.isArray(codes)
        ? codes.filter((code): code is string => typeof code === 'string')
        : []
    }),
  )
  let suffix = context.catches.length + 1
  while (existingCodes.has(`CASE_ERROR_${suffix}`)) suffix += 1
  const updated = replaceControlConfiguration(definition, nodeId, {
    ...context.config,
    catches: [
      ...context.catches,
      {
        id: catchId,
        label: `捕获 ${context.catches.length + 1}`,
        error_codes: [`CASE_ERROR_${suffix}`],
        body: body(catchRegion),
      },
    ],
  })
  return { ...updated, regions: [...(updated.regions ?? []), catchRegion] }
}

export function removeTryCatch(
  definition: WorkflowDefinition,
  nodeId: string,
  catchId: string,
): WorkflowDefinition | null {
  const context = tryContext(definition, nodeId)
  if (!context || (context.catches.length <= 1 && !context.config.finally_body)) return null
  const selected = context.catches.map(asRecord).find((item) => item?.id === catchId)
  const regionId = asRecord(selected?.body)?.region_id
  const owned = definition.regions?.find(
    (item) =>
      item.id === regionId && item.owner_node_id === nodeId && item.role === `catch:${catchId}`,
  )
  if (!owned) return null
  const removedIds = regionTreeIds(definition, owned)
  const updated = replaceControlConfiguration(definition, nodeId, {
    ...context.config,
    catches: context.catches.filter((item) => asRecord(item)?.id !== catchId),
  })
  return { ...updated, regions: updated.regions?.filter((item) => !removedIds.has(item.id)) }
}

export function setTryFinally(
  definition: WorkflowDefinition,
  nodeId: string,
  enabled: boolean,
): WorkflowDefinition | null {
  const context = tryContext(definition, nodeId)
  if (!context || (!enabled && context.catches.length === 0)) return null
  const current = asRecord(context.config.finally_body)
  if (Boolean(current) === enabled) return definition
  if (enabled) {
    const created = region(nodeId, 'finally')
    const updated = replaceControlConfiguration(definition, nodeId, {
      ...context.config,
      finally_body: body(created),
    })
    return { ...updated, regions: [...(updated.regions ?? []), created] }
  }
  const owned = definition.regions?.find(
    (item) =>
      item.id === current?.region_id && item.owner_node_id === nodeId && item.role === 'finally',
  )
  if (!owned) return null
  const removedIds = regionTreeIds(definition, owned)
  const updated = replaceControlConfiguration(definition, nodeId, {
    ...context.config,
    finally_body: null,
  })
  return { ...updated, regions: updated.regions?.filter((item) => !removedIds.has(item.id)) }
}

export function insertNestedControlBlock(
  definition: WorkflowDefinition,
  regionId: string,
  afterId: string,
  kind: ControlBlockKind,
): WorkflowDefinition | null {
  const parent = definition.regions?.find((item) => item.id === regionId)
  if (!parent || nestedControlDepth(definition, parent) > 4) return null
  const created = addControlBlock(definition, kind)
  const node = created.nodes.at(-1)!
  const updated = insertRegionStepAfter(parent, afterId, (previous) => ({
    ...node,
    position: { x: previous.position.x + 220, y: previous.position.y },
  }))
  if (!updated) return null
  return {
    ...created,
    nodes: definition.nodes,
    regions: created.regions?.map((item) => (item.id === regionId ? updated : item)),
  }
}

export function removeNestedControlBlock(
  definition: WorkflowDefinition,
  regionId: string,
  nodeId: string,
): WorkflowDefinition | null {
  const parent = definition.regions?.find((item) => item.id === regionId)
  const node = parent?.nodes.find((item) => item.id === nodeId)
  if (!parent || !node?.capability_id?.startsWith('flow.control.')) return null
  const links = regionRemovalLinks(parent, nodeId)
  if (!links || regionRemovalHasReferences(parent, nodeId, links)) return null
  const updated = withoutRegionStep(parent, nodeId, links)
  const descendants = new Set(descendantRegions(definition, [nodeId]).map((item) => item.id))
  return {
    ...definition,
    regions: definition.regions
      ?.filter((item) => !descendants.has(item.id))
      .map((item) => (item.id === regionId ? updated : item)),
  }
}

function nestedControlDepth(definition: WorkflowDefinition, parent: WorkflowRegion): number {
  let depth = 1
  let ownerId = parent.owner_node_id
  const seen = new Set<string>()
  while (!seen.has(ownerId)) {
    seen.add(ownerId)
    const containing = definition.regions?.find((item) =>
      item.nodes.some((node) => node.id === ownerId),
    )
    if (!containing) return depth
    ownerId = containing.owner_node_id
    depth += 1
  }
  return 5
}

function updatedDefaultRegions(
  definition: WorkflowDefinition,
  existing: WorkflowRegion | undefined,
  created: WorkflowRegion | null,
): WorkflowRegion[] {
  const removedIds = existing ? regionTreeIds(definition, existing) : new Set<string>()
  return [
    ...(definition.regions ?? []).filter((item) => !removedIds.has(item.id)),
    ...(created ? [created] : []),
  ]
}

function switchContext(definition: WorkflowDefinition, nodeId: string) {
  const node =
    definition.nodes.find((item) => item.id === nodeId) ??
    definition.regions?.flatMap((region) => region.nodes).find((item) => item.id === nodeId)
  const config = node?.configuration
  if (node?.capability_id !== 'flow.control.switch' || !Array.isArray(config?.branches)) return null
  return { config, branches: config.branches as unknown[] }
}

function tryContext(definition: WorkflowDefinition, nodeId: string) {
  const node =
    definition.nodes.find((item) => item.id === nodeId) ??
    definition.regions?.flatMap((item) => item.nodes).find((item) => item.id === nodeId)
  const config = node?.configuration
  if (node?.capability_id !== 'flow.control.try' || !Array.isArray(config?.catches)) return null
  return { config, catches: config.catches as unknown[] }
}

function replaceControlConfiguration(
  definition: WorkflowDefinition,
  nodeId: string,
  configuration: Record<string, unknown>,
): WorkflowDefinition {
  return {
    ...definition,
    nodes: definition.nodes.map((node) => (node.id === nodeId ? { ...node, configuration } : node)),
    regions: definition.regions?.map((region) => ({
      ...region,
      nodes: region.nodes.map((node) => (node.id === nodeId ? { ...node, configuration } : node)),
    })),
  }
}

function regionTreeIds(definition: WorkflowDefinition, root: WorkflowRegion): Set<string> {
  return new Set([
    root.id,
    ...descendantRegions(
      definition,
      root.nodes.map((node) => node.id),
    ).map((item) => item.id),
  ])
}

function ownedDefaultRegion(
  definition: WorkflowDefinition,
  nodeId: string,
  current: Record<string, unknown>,
): WorkflowRegion | undefined {
  const regionId = asRecord(current.body)?.region_id
  return definition.regions?.find(
    (item) => item.id === regionId && item.owner_node_id === nodeId && item.role === 'default',
  )
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function controlRunPolicy(
  definition: WorkflowDefinition,
  kind: ControlBlockKind,
): NonNullable<WorkflowDefinition['run_policy']> {
  const current = definition.run_policy
  return {
    request_budget: current?.request_budget ?? 1000,
    max_runtime_seconds: current?.max_runtime_seconds ?? 300,
    cleanup_request_budget: current?.cleanup_request_budget ?? (kind === 'try' ? 10 : null),
    force_cancel_skips_cleanup: current?.force_cancel_skips_cleanup ?? true,
  }
}

export function descendantRegions(
  definition: WorkflowDefinition,
  ownerIds: string[],
): WorkflowRegion[] {
  const pending = [...ownerIds]
  const found: WorkflowRegion[] = []
  while (pending.length) {
    const ownerId = pending.pop()!
    for (const region of definition.regions ?? []) {
      if (region.owner_node_id !== ownerId || found.some((item) => item.id === region.id)) continue
      found.push(region)
      pending.push(...region.nodes.map((node) => node.id))
    }
  }
  return found
}

export function appendRegionDelay(region: WorkflowRegion): WorkflowRegion | null {
  return appendRegionStep(region, newDelayStep)
}

export function appendRegionApi(
  region: WorkflowRegion,
  apiId: string,
  apiVersion: number,
): WorkflowRegion | null {
  return appendRegionStep(region, (previous) => newApiStep(apiId, apiVersion, previous))
}

export function insertRegionDelayAfter(
  region: WorkflowRegion,
  afterId: string,
): WorkflowRegion | null {
  return insertRegionStepAfter(region, afterId, newDelayStep)
}

export function insertRegionApiAfter(
  region: WorkflowRegion,
  afterId: string,
  apiId: string,
  apiVersion: number,
): WorkflowRegion | null {
  return insertRegionStepAfter(region, afterId, (previous) =>
    newApiStep(apiId, apiVersion, previous),
  )
}

export function removeRegionStep(region: WorkflowRegion, nodeId: string): WorkflowRegion | null {
  const selected = region.nodes.find((node) => node.id === nodeId)
  if (region.nodes.length <= 1 || !selected || selected.capability_id?.startsWith('flow.control.'))
    return null
  const links = regionRemovalLinks(region, nodeId)
  if (!links || regionRemovalHasReferences(region, nodeId, links)) return null
  return withoutRegionStep(region, nodeId, links)
}

export function moveRegionStep(
  region: WorkflowRegion,
  nodeId: string,
  direction: -1 | 1,
): WorkflowRegion | null {
  const path = linearRegionPath(region)
  if (!path) return null
  return moveRegionStepTo(region, nodeId, path.indexOf(nodeId) + direction)
}

export function moveRegionStepTo(
  region: WorkflowRegion,
  nodeId: string,
  targetIndex: number,
): WorkflowRegion | null {
  const path = linearRegionPath(region)
  if (
    !path ||
    region.nodes.some((node) => region.nodes.some((other) => nodeReferences(node, other.id)))
  )
    return null
  const index = path.indexOf(nodeId)
  if (
    index < 0 ||
    !Number.isInteger(targetIndex) ||
    targetIndex < 0 ||
    targetIndex >= path.length ||
    index === targetIndex
  )
    return null
  const original = path.map((id) => region.nodes.find((node) => node.id === id)!)
  const orderedEdges = path
    .slice(0, -1)
    .map((id) => region.edges.find((edge) => edge.source === id)!)
  const moved = path.filter((id) => id !== nodeId)
  moved.splice(targetIndex, 0, nodeId)
  return {
    ...region,
    nodes: moved.map((id, position) => ({
      ...region.nodes.find((node) => node.id === id)!,
      position: original[position].position,
    })),
    edges: orderedEdges.map((edge, position) => ({
      ...edge,
      source: moved[position],
      target: moved[position + 1],
    })),
    entry_node_id: moved[0],
    exit_node_ids: [moved.at(-1)!],
  }
}

export function connectRegionSteps(
  region: WorkflowRegion,
  sourceId: string,
  targetId: string,
): WorkflowRegion | null {
  const path = linearRegionPath(region)
  if (!path || sourceId === targetId) return null
  const sourceIndex = path.indexOf(sourceId)
  const targetIndex = path.indexOf(targetId)
  if (sourceIndex < 0 || targetIndex < 0 || path[sourceIndex + 1] === targetId) return null
  return moveRegionStepTo(
    region,
    targetId,
    targetIndex < sourceIndex ? sourceIndex : sourceIndex + 1,
  )
}

export function linearRegionPath(region: WorkflowRegion): string[] | null {
  if (!hasLinearRegionShape(region)) return null
  const ids = new Set(region.nodes.map((node) => node.id))
  const seen = new Set<string>()
  const path: string[] = []
  let current: string | null | undefined = region.entry_node_id
  while (current && ids.has(current) && !seen.has(current)) {
    seen.add(current)
    path.push(current)
    const outgoing = region.edges.filter((edge) => edge.source === current)
    if (outgoing.length > 1) return null
    current = outgoing[0]?.target
  }
  return path.length === region.nodes.length && path.at(-1) === region.exit_node_ids[0] && !current
    ? path
    : null
}

function hasLinearRegionShape(region: WorkflowRegion): boolean {
  return Boolean(
    region.entry_node_id &&
    region.exit_node_ids.length === 1 &&
    region.edges.length === region.nodes.length - 1 &&
    region.edges.every((edge) => !edge.condition && edge.mappings.length === 0),
  )
}

type RemovalLinks = { incoming?: WorkflowEdge; outgoing?: WorkflowEdge }

function regionRemovalLinks(region: WorkflowRegion, nodeId: string): RemovalLinks | null {
  const incoming = region.edges.filter((edge) => edge.target === nodeId)
  const outgoing = region.edges.filter((edge) => edge.source === nodeId)
  if (incoming.length > 1 || outgoing.length > 1) return null
  if (incoming.length + outgoing.length === 0) return null
  if (invalidEntryBoundary(region, nodeId, incoming.length)) return null
  if (invalidExitBoundary(region, nodeId, incoming.length, outgoing.length)) return null
  return { incoming: incoming[0], outgoing: outgoing[0] }
}

function invalidEntryBoundary(region: WorkflowRegion, nodeId: string, incoming: number): boolean {
  return incoming === 0 ? region.entry_node_id !== nodeId : region.entry_node_id === nodeId
}

function invalidExitBoundary(
  region: WorkflowRegion,
  nodeId: string,
  incoming: number,
  outgoing: number,
): boolean {
  const isExit = region.exit_node_ids.includes(nodeId)
  if (outgoing === 0) return !isExit || incoming === 0
  return isExit
}

function regionRemovalHasReferences(
  region: WorkflowRegion,
  nodeId: string,
  links: RemovalLinks,
): boolean {
  if (unsafeRemovalEdge(links.incoming) || unsafeRemovalEdge(links.outgoing)) return true
  if (region.edges.some((edge) => hasNodeReference(edge.mappings, nodeId))) return true
  if (region.nodes.some((node) => node.id !== nodeId && nodeReferences(node, nodeId))) return true
  return hasNodeReference(region.inputs, nodeId) || hasNodeReference(region.outputs, nodeId)
}

function unsafeRemovalEdge(edge: WorkflowEdge | undefined): boolean {
  return Boolean(edge?.condition || edge?.mappings.length)
}

function nodeReferences(node: WorkflowNode, nodeId: string): boolean {
  return (
    hasNodeReference(node.config, nodeId) ||
    hasNodeReference(node.configuration, nodeId) ||
    Boolean(node.bindings?.length)
  )
}

function withoutRegionStep(
  region: WorkflowRegion,
  nodeId: string,
  links: RemovalLinks,
): WorkflowRegion {
  const nextId = links.outgoing?.target
  const previousId = links.incoming?.source
  const replacementEdge = links.incoming && nextId ? [{ ...links.incoming, target: nextId }] : []
  return {
    ...region,
    nodes: region.nodes.filter((node) => node.id !== nodeId),
    edges: region.edges
      .filter((edge) => edge.source !== nodeId && edge.target !== nodeId)
      .concat(replacementEdge),
    entry_node_id: region.entry_node_id === nodeId ? (nextId ?? null) : region.entry_node_id,
    exit_node_ids: region.exit_node_ids.map((id) => (id === nodeId ? (previousId ?? id) : id)),
  }
}

function hasNodeReference(value: unknown, nodeId: string): boolean {
  if (typeof value === 'string') return value.includes(nodeId)
  if (Array.isArray(value)) return value.some((item) => hasNodeReference(item, nodeId))
  if (!value || typeof value !== 'object') return false
  return Object.entries(value).some(
    ([key, item]) =>
      ((key === 'node_id' || key === 'source_node_id' || key === 'target_node_id') &&
        item === nodeId) ||
      hasNodeReference(item, nodeId),
  )
}

function newApiStep(apiId: string, apiVersion: number, previous?: WorkflowNode): WorkflowNode {
  return {
    id: `step-${crypto.randomUUID()}`,
    type: 'api',
    name: '接口请求',
    position: previous ? { x: previous.position.x + 220, y: previous.position.y } : { x: 0, y: 0 },
    config: {
      api_definition_id: apiId,
      api_version: apiVersion,
      request_overrides: {},
      max_retries: 0,
      retry_on: ['network_error', '5xx'],
    },
  }
}

export function appendRegionSignal(
  region: WorkflowRegion,
  owner: WorkflowNode,
  signal: 'break' | 'continue',
): WorkflowRegion | null {
  if (!canAppendRegionSignal(region, owner)) return null
  return appendRegionStep(region, (previous) => ({
    id: `step-${crypto.randomUUID()}`,
    type: 'capability',
    name: signal === 'break' ? '退出当前循环' : '继续下一轮',
    position: previous ? { x: previous.position.x + 220, y: previous.position.y } : { x: 0, y: 0 },
    config: {},
    capability_id: `flow.control.${signal}`,
    capability_version: '1.0.0',
    configuration: {},
    bindings: [],
  }))
}

export function canAppendRegionSignal(region: WorkflowRegion, owner: WorkflowNode): boolean {
  const serialLoops = new Set([
    'flow.control.foreach',
    'flow.control.repeat',
    'flow.control.while',
    'flow.control.do_while',
    'flow.control.until',
  ])
  if (
    region.owner_node_id !== owner.id ||
    region.role !== 'body' ||
    !owner.capability_id ||
    !serialLoops.has(owner.capability_id)
  )
    return false
  const policy = owner.configuration?.policy
  if (policy && typeof policy === 'object' && 'concurrency' in policy && policy.concurrency !== 1)
    return false
  return true
}

function appendRegionStep(
  region: WorkflowRegion,
  create: (previous?: WorkflowNode) => WorkflowNode,
): WorkflowRegion | null {
  if (region.nodes.length === 0) {
    const step = create()
    return { ...region, nodes: [step], entry_node_id: step.id, exit_node_ids: [step.id] }
  }
  if (region.exit_node_ids.length !== 1) return null
  const previous = region.nodes.find((node) => node.id === region.exit_node_ids[0])
  if (!previous) return null
  const step = create(previous)
  return {
    ...region,
    nodes: [...region.nodes, step],
    edges: [
      ...region.edges,
      {
        id: `edge-${crypto.randomUUID()}`,
        source: previous.id,
        target: step.id,
        condition: null,
        mappings: [],
      },
    ],
    exit_node_ids: [step.id],
  }
}

function insertRegionStepAfter(
  region: WorkflowRegion,
  afterId: string,
  create: (previous: WorkflowNode) => WorkflowNode,
): WorkflowRegion | null {
  const index = region.nodes.findIndex((node) => node.id === afterId)
  if (index < 0) return null
  const outgoing = region.edges.filter((edge) => edge.source === afterId)
  if (outgoing.length > 1 || outgoing.some((edge) => edge.condition || edge.mappings.length))
    return null
  if (outgoing.length === 0 && !region.exit_node_ids.includes(afterId)) return null
  if (outgoing.length > 0 && region.exit_node_ids.includes(afterId)) return null
  const previous = region.nodes[index]
  const step = create(previous)
  return {
    ...region,
    nodes: [
      ...region.nodes.slice(0, index + 1),
      step,
      ...region.nodes
        .slice(index + 1)
        .map((node) =>
          node.position.x > previous.position.x
            ? { ...node, position: { ...node.position, x: node.position.x + 220 } }
            : node,
        ),
    ],
    edges: [
      ...region.edges.map((edge) =>
        edge.source === afterId ? { ...edge, source: step.id } : edge,
      ),
      {
        id: `edge-${crypto.randomUUID()}`,
        source: afterId,
        target: step.id,
        condition: null,
        mappings: [],
      },
    ],
    exit_node_ids: outgoing.length
      ? region.exit_node_ids
      : region.exit_node_ids.map((id) => (id === afterId ? step.id : id)),
  }
}

function newDelayStep(previous?: WorkflowNode): WorkflowNode {
  return {
    id: `step-${crypto.randomUUID()}`,
    type: 'delay',
    name: '等待 0 秒',
    position: previous ? { x: previous.position.x + 220, y: previous.position.y } : { x: 0, y: 0 },
    config: { seconds: 0 },
  }
}

function remapReferences(value: unknown, ids: Map<string, string>): unknown {
  if (Array.isArray(value)) return value.map((item) => remapReferences(item, ids))
  if (value === null || typeof value !== 'object') return value
  if ('kind' in value && value.kind === 'literal') return structuredClone(value)
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [
      key,
      (key === 'node_id' ||
        key === 'region_id' ||
        key === 'source_node_id' ||
        key === 'target_node_id') &&
      typeof item === 'string'
        ? (ids.get(item) ?? item)
        : remapReferences(item, ids),
    ]),
  )
}

function copiedBranchIds(configuration: Record<string, unknown> | undefined): Map<string, string> {
  const result = new Map<string, string>()
  for (const field of ['branches', 'catches']) {
    const branches = configuration?.[field]
    if (!Array.isArray(branches)) continue
    for (const branch of branches) {
      if (branch && typeof branch === 'object' && typeof branch.id === 'string') {
        result.set(branch.id, `${branch.id.slice(0, 100)}-copy-${crypto.randomUUID().slice(0, 8)}`)
      }
    }
  }
  return result
}

function remapBranches(
  configuration: Record<string, unknown> | undefined,
  ids: Map<string, string>,
  branches: Map<string, string>,
): Record<string, unknown> | undefined {
  if (!configuration) return undefined
  const copy = remapReferences(configuration, ids) as Record<string, unknown>
  for (const field of ['branches', 'catches']) {
    const items = copy[field]
    if (!Array.isArray(items)) continue
    copy[field] = items.map((item) =>
      item && typeof item === 'object' && typeof item.id === 'string'
        ? { ...item, id: branches.get(item.id) ?? item.id }
        : item,
    )
  }
  return copy
}

export function copyControlRegions(
  definition: WorkflowDefinition,
  sourceNodeId: string,
  copiedNodeId: string,
): { configuration: Record<string, unknown> | undefined; regions: WorkflowRegion[] } {
  const source = definition.nodes.find((node) => node.id === sourceNodeId)
  const owned = descendantRegions(definition, [sourceNodeId])
  const branches = copiedBranchIds(source?.configuration)
  for (const region of owned) {
    for (const node of region.nodes) {
      for (const [oldId, newId] of copiedBranchIds(node.configuration)) branches.set(oldId, newId)
    }
  }
  const ids = new Map<string, string>([[sourceNodeId, copiedNodeId]])
  for (const region of owned) {
    ids.set(region.id, `region-${crypto.randomUUID()}`)
    for (const node of region.nodes) ids.set(node.id, `step-${crypto.randomUUID()}`)
    for (const edge of region.edges) ids.set(edge.id, `edge-${crypto.randomUUID()}`)
  }
  return {
    configuration: remapBranches(source?.configuration, ids, branches),
    regions: owned.map((item) => ({
      ...structuredClone(item),
      id: ids.get(item.id)!,
      owner_node_id: ids.get(item.owner_node_id)!,
      role: item.role.includes(':')
        ? `${item.role.split(':')[0]}:${branches.get(item.role.split(':')[1]) ?? item.role.split(':')[1]}`
        : item.role,
      nodes: item.nodes.map((node) => ({
        ...structuredClone(node),
        id: ids.get(node.id)!,
        configuration: remapBranches(node.configuration, ids, branches),
        config: remapReferences(node.config, ids) as Record<string, unknown>,
      })),
      edges: item.edges.map((edge) => ({
        ...structuredClone(edge),
        id: ids.get(edge.id)!,
        source: ids.get(edge.source)!,
        target: ids.get(edge.target)!,
        mappings: edge.mappings.map((mapping) => ({
          ...mapping,
          source: {
            ...mapping.source,
            node_id: ids.get(mapping.source.node_id) ?? mapping.source.node_id,
          },
          target: {
            ...mapping.target,
            node_id: ids.get(mapping.target.node_id) ?? mapping.target.node_id,
          },
        })),
      })),
      entry_node_id: item.entry_node_id ? ids.get(item.entry_node_id)! : null,
      exit_node_ids: item.exit_node_ids.map((id) => ids.get(id)!),
      inputs: remapReferences(item.inputs, ids) as Record<string, unknown>,
      outputs: remapReferences(item.outputs, ids) as Record<string, unknown>,
    })),
  }
}
