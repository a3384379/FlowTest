import type { WorkflowDefinition, WorkflowNode } from '../../lib/api'
import { parseValueSource, type ValueSource } from './control-source-browser'
import { effectiveConfig, resolveEffectiveNodeType } from './graph-analysis'

export type NodeDataSource = {
  id: string
  target: string
  targetPath: string
  kind: 'node_output' | 'variable' | 'expression'
  sourceId?: string
  path: string
  scope: string
  expression?: string
  reason?: string
}

const variableLabels: Readonly<Record<string, string>> = {
  runtime: '运行变量',
  workflow: '流程变量',
  input: '输入变量',
  local: '局部变量',
  loop: '循环变量',
  state: '循环状态',
  error: '异常上下文',
}
const regionLabels: Readonly<Record<string, string>> = {
  body: '内部步骤',
  true: '条件成立',
  false: '条件不成立',
  try: '尝试',
  catch: '异常处理',
  finally: '最终处理',
  default: '默认分支',
}

export function referenceNodes(definition: WorkflowDefinition): WorkflowNode[] {
  return [...definition.nodes, ...(definition.regions ?? []).flatMap((region) => region.nodes)]
}

export function nodeDataSources(definition: WorkflowDefinition, nodeId?: string): NodeDataSource[] {
  const references = referenceNodes(definition).flatMap((node) => sourcesOfNode(definition, node))
  for (const region of definition.regions ?? []) {
    for (const field of ['inputs', 'outputs'] as const)
      collectTypedSources(region[field], ['regions', region.id, field], (source, path) => {
        references.push(
          typedReference(definition, region.owner_node_id, formatValuePath(path), source),
        )
      })
  }
  const edges = [
    ...definition.edges,
    ...(definition.regions ?? []).flatMap((region) => region.edges),
  ]
  for (const edge of edges) {
    for (const mapping of edge.mappings) {
      const targetPath = `mappings.${edge.id}.${mapping.target.location}.${mapping.target.key}`
      references.push(
        nodeOutputSource(
          definition,
          mapping.target.node_id,
          targetPath,
          mapping.source.node_id,
          mapping.source.path,
          mapping.source.path,
        ),
      )
    }
  }
  return nodeId ? references.filter((reference) => reference.target === nodeId) : references
}

function sourcesOfNode(definition: WorkflowDefinition, node: WorkflowNode): NodeDataSource[] {
  const config = effectiveConfig(node)
  const references = legacySources(definition, node, config)
  if (node.capability_id?.startsWith('flow.control.'))
    collectTypedSources(config, [], (source, path) => {
      references.push(typedReference(definition, node.id, formatValuePath(path), source))
    })
  for (const binding of node.bindings ?? []) {
    references.push(
      opaqueSource(node.id, `bindings.${binding.input}`, '表达式未解析', binding.expression),
    )
  }
  return references
}

function legacySources(
  definition: WorkflowDefinition,
  node: WorkflowNode,
  config: Record<string, unknown>,
): NodeDataSource[] {
  if (!['extract', 'assert', 'condition', 'for_each'].includes(resolveEffectiveNodeType(node)))
    return []
  const fields = [
    ['source_node_id', 'expression'],
    ['expected_source_node_id', 'expected_expression'],
  ]
  return fields.flatMap(([sourceKey, expressionKey]) => {
    const sourceId = config[sourceKey]
    if (typeof sourceId !== 'string' || !sourceId) return []
    const expression =
      typeof config[expressionKey] === 'string' ? (config[expressionKey] as string) : undefined
    return [
      nodeOutputSource(
        definition,
        node.id,
        `$.${sourceKey}`,
        sourceId,
        expression ?? '$',
        expression,
      ),
    ]
  })
}

function collectTypedSources(
  value: unknown,
  path: Array<string | number>,
  visit: (source: ValueSource | null, path: Array<string | number>) => void,
): void {
  if (!value || typeof value !== 'object') return
  const item = value as Record<string, unknown>
  // Literal payloads are data, including any source-shaped objects inside their values.
  if (item.kind === 'literal') return
  const source = parseValueSource(value)
  if (source) {
    visit(source, path)
    return
  }
  if (item.kind === 'node_output' || item.kind === 'variable') {
    visit(null, path)
    return
  }
  if (path.length >= 32) {
    visit(null, path)
    return
  }
  const children = Array.isArray(value)
    ? value.map((child, index) => [index, child] as const)
    : Object.entries(item)
  for (const [key, child] of children) collectTypedSources(child, [...path, key], visit)
}

function typedReference(
  definition: WorkflowDefinition,
  target: string,
  targetPath: string,
  source: ValueSource | null,
): NodeDataSource {
  if (!source || source.kind === 'literal')
    return opaqueSource(target, targetPath, '来源契约未解析')
  if (source.kind === 'node_output')
    return nodeOutputSource(
      definition,
      target,
      targetPath,
      source.node_id,
      formatValuePath(source.path),
    )
  return {
    id: referenceId(target, targetPath),
    target,
    targetPath,
    kind: 'variable',
    path: formatValuePath(source.path),
    scope: `${variableLabels[source.scope]} · ${source.scope}`,
  }
}

function nodeOutputSource(
  definition: WorkflowDefinition,
  target: string,
  targetPath: string,
  sourceId: string,
  path: string,
  expression?: string,
): NodeDataSource {
  const exists = referenceNodes(definition).some((node) => node.id === sourceId)
  const reason = exists
    ? sourceId === target
      ? '来源引用当前节点，请核对执行作用域'
      : undefined
    : '来源节点不存在'
  return {
    id: referenceId(target, targetPath),
    target,
    targetPath,
    kind: 'node_output',
    sourceId,
    path,
    expression,
    scope: exists ? nodeScope(definition, sourceId) : '未解析',
    reason,
  }
}

function opaqueSource(
  target: string,
  targetPath: string,
  reason: string,
  expression?: string,
): NodeDataSource {
  return {
    id: referenceId(target, targetPath),
    target,
    targetPath,
    kind: 'expression',
    path: expression ?? '未提供',
    scope: '未解析',
    expression,
    reason,
  }
}

function referenceId(target: string, targetPath: string): string {
  return `data-source:${JSON.stringify([target, targetPath])}`
}

function nodeScope(definition: WorkflowDefinition, nodeId: string): string {
  const region = definition.regions?.find((candidate) =>
    candidate.nodes.some((node) => node.id === nodeId),
  )
  if (!region) return '主流程'
  const owner = referenceNodes(definition).find((node) => node.id === region.owner_node_id)
  return `${owner?.name ?? region.owner_node_id} / ${regionLabels[region.role] ?? region.role} · ${region.id}`
}

export function formatValuePath(path: Array<string | number>): string {
  return (
    '$' +
    path
      .map((segment) => {
        if (typeof segment === 'number') return `[${segment}]`
        return /^[A-Za-z_$][\w$]*$/.test(segment) ? `.${segment}` : `[${JSON.stringify(segment)}]`
      })
      .join('')
  )
}
