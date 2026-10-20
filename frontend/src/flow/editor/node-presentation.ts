import type { ApiDefinition, WorkflowDefinition, WorkflowNode } from '../../lib/api'
import { parseValueSource } from './control-source-browser'
import { effectiveConfig, resolveEffectiveNodeType } from './graph-analysis'
import { nodeDataSources } from './node-data-sources'
export { nodeDataSources } from './node-data-sources'

export type RegionPreview = { id: string; label: string; steps: string[] }
export type DataReference = { id: string; source: string; target: string; label: string }

const regionLabels: Readonly<Record<string, string>> = {
  body: '内部步骤',
  true: '条件成立',
  false: '条件不成立',
  try: '尝试',
  catch: '异常处理',
  finally: '最终处理',
  default: '默认分支',
}

export function nodePresentation(
  node: WorkflowNode,
  definition: WorkflowDefinition,
  apis: ApiDefinition[] = [],
): {
  summary: string
  regions: RegionPreview[]
} {
  const regions = (definition.regions ?? [])
    .filter((region) => region.owner_node_id === node.id)
    .map((region) => ({
      id: region.id,
      label: regionLabels[region.role] ?? region.role,
      steps: region.nodes.map((child) => child.name),
    }))
  return { summary: nodeSummary(node, definition, apis), regions }
}

function nodeSummary(
  node: WorkflowNode,
  definition: WorkflowDefinition,
  apis: ApiDefinition[],
): string {
  const config = effectiveConfig(node)
  const type = resolveEffectiveNodeType(node)
  const source = sourceSummary(config, definition)
  if (source) return sourceIntent(type, config, source, definition)
  if (type === 'api') return apiSummary(config, apis)
  if (type === 'start') return '流程入口'
  if (type === 'end') return '流程出口'
  if (type === 'delay' && typeof config.seconds === 'number') return `等待 ${config.seconds} 秒`
  if (node.capability_id?.startsWith('flow.control.'))
    return controlSummary(config, node, definition)
  return `配置类型：${node.capability_id ?? node.type}`
}

function sourceSummary(
  config: Record<string, unknown>,
  definition: WorkflowDefinition,
): string | null {
  if (typeof config.source_node_id !== 'string' || !config.source_node_id) return null
  return sourcePath(config.source_node_id, config.expression, definition)
}

function sourcePath(id: string, expression: unknown, definition: WorkflowDefinition): string {
  const source = allNodes(definition).find((item) => item.id === id)
  return `${source?.name ?? `节点不存在（${id}）`} · ${typeof expression === 'string' ? expression : '表达式未提供'}`
}

function sourceIntent(
  type: string,
  config: Record<string, unknown>,
  source: string,
  definition: WorkflowDefinition,
): string {
  if (type === 'extract') return `提取 ${source} → ${String(config.variable ?? '变量未提供')}`
  if (type === 'for_each')
    return `遍历 ${source} · 子流程 v${String(config.workflow_version ?? '未提供')} · 并发 ${String(config.concurrency ?? '未提供')}`
  if (type === 'assert' || type === 'condition') {
    const expected =
      typeof config.expected_source_node_id === 'string'
        ? sourcePath(config.expected_source_node_id, config.expected_expression, definition)
        : previewValue(config.expected)
    const operator =
      config.assertion_type === 'json_schema' ? '符合 JSON Schema' : operatorText(config.operator)
    return `${source} ${operator} ${expected}`
  }
  return `来源：${source}`
}

function controlSummary(
  config: Record<string, unknown>,
  node: WorkflowNode,
  definition: WorkflowDefinition,
): string {
  const policy = record(config.policy)
  const parts: string[] = []
  const intent = controlIntent(config, node.capability_id ?? '', definition)
  if (intent) parts.push(intent)
  if (typeof config.count === 'number') parts.push(`重复 ${config.count} 次`)
  if (typeof policy.max_iterations === 'number') parts.push(`上限 ${policy.max_iterations} 轮`)
  if (typeof policy.concurrency === 'number') parts.push(`并发 ${policy.concurrency}`)
  if (typeof policy.on_error === 'string') parts.push(`异常：${policy.on_error}`)
  if (typeof policy.timeout_seconds === 'number') parts.push(`最长 ${policy.timeout_seconds} 秒`)
  return parts.join(' · ') || '配置条件与内部步骤'
}

function apiSummary(config: Record<string, unknown>, apis: ApiDefinition[]): string {
  const api = apis.find((item) => item.id === config.api_definition_id)
  const version = typeof config.api_version === 'number' ? `v${config.api_version}` : '版本未提供'
  if (!api) return `接口资产 · ${version} · 摘要未载入`
  const request =
    api.current_version === config.api_version && api.method && api.path
      ? `${api.method} ${api.path}`
      : '固定版本请求摘要未提供'
  return `${api.name} · ${version} · ${request}`
}

function controlIntent(
  config: Record<string, unknown>,
  capability: string,
  definition: WorkflowDefinition,
): string {
  if (config.condition)
    return `${capability === 'flow.control.until' ? '直到' : '条件'}：${conditionText(config.condition, definition)}`
  if (config.collection) return `遍历：${valueText(config.collection, definition)}`
  if (Array.isArray(config.branches))
    return `${config.branches.length} 个分支 · ${branchIntent(config, definition)}`
  if (Array.isArray(config.catches))
    return `${config.catches.length} 个异常处理 · finally ${config.finally_body ? '已配置' : '未配置'}`
  return ''
}

function branchIntent(config: Record<string, unknown>, definition: WorkflowDefinition): string {
  if (config.join === 'all') return '等待全部完成'
  if (config.join === 'any') return '等待任一完成'
  const subject =
    config.mode === 'value' ? `匹配 ${valueText(config.value, definition)}` : '按条件匹配'
  const branches = Array.isArray(config.branches) ? config.branches : []
  const previews = branches.slice(0, 3).map((value) => {
    const branch = record(value)
    const condition = branch.condition
      ? conditionText(branch.condition, definition)
      : valueText(branch.match, definition)
    return `${String(branch.label ?? branch.id ?? '未命名分支')}：${condition}`
  })
  if (branches.length > 3) previews.push(`另 ${branches.length - 3} 个分支（配置中查看）`)
  return [subject, ...previews].join(' · ')
}

function conditionText(value: unknown, definition: WorkflowDefinition, depth = 0): string {
  if (depth > 8) return '条件超出显示深度，请查看配置'
  const condition = record(value)
  if (condition.kind === 'compare') {
    const right = condition.right == null ? '' : ` ${valueText(condition.right, definition)}`
    return `${valueText(condition.left, definition)} ${operatorText(condition.operator)}${right}`
  }
  if (condition.kind === 'not')
    return `非（${conditionText(condition.condition, definition, depth + 1)}）`
  if (['all', 'any'].includes(String(condition.kind)) && Array.isArray(condition.conditions)) {
    const conjunction = condition.kind === 'all' ? ' 且 ' : ' 或 '
    return `（${condition.conditions.map((item) => conditionText(item, definition, depth + 1)).join(conjunction)}）`
  }
  return `条件未解析（${String(condition.kind ?? '类型未提供')}）`
}

function valueText(value: unknown, definition: WorkflowDefinition): string {
  const source = parseValueSource(value)
  if (!source) return '来源未解析'
  if (source.kind === 'literal') return previewValue(source.value)
  if (source.kind === 'variable') return `${source.scope}.${source.path.join('.')}`
  const name =
    allNodes(definition).find((node) => node.id === source.node_id)?.name ?? source.node_id
  return `${name}.${source.path.join('.')}`
}

function allNodes(definition: WorkflowDefinition): WorkflowNode[] {
  return [...definition.nodes, ...(definition.regions ?? []).flatMap((region) => region.nodes)]
}

function previewValue(value: unknown): string {
  const text = JSON.stringify(value) ?? '未提供'
  return text.length > 120 ? `${text.slice(0, 120)}…（配置中查看完整值）` : text
}

function operatorText(value: unknown): string {
  const operators: Readonly<Record<string, string>> = {
    equals: '等于',
    not_equals: '不等于',
    gt: '大于',
    gte: '大于等于',
    lt: '小于',
    lte: '小于等于',
    contains: '包含',
    in: '属于',
    exists: '存在',
    not_exists: '不存在',
    is_null: '为空值',
    not_null: '非空值',
    is_empty: '为空集合',
    not_empty: '非空集合',
    length_equals: '长度等于',
    length_gt: '长度大于',
    length_lt: '长度小于',
  }
  return operators[String(value)] ?? `运算符 ${String(value ?? '未提供')}`
}

// These are view data only. They never enter WorkflowDefinition.edges or graph commands.
export function dataReferences(definition: WorkflowDefinition, targetId?: string): DataReference[] {
  const known = new Set(definition.nodes.map((node) => node.id))
  return nodeDataSources(definition, targetId)
    .filter(
      (reference) =>
        reference.sourceId &&
        known.has(reference.sourceId) &&
        known.has(reference.target) &&
        !reference.reason,
    )
    .map((reference) => ({
      id: reference.id,
      source: reference.sourceId!,
      target: reference.target,
      label: `${reference.path} → ${reference.targetPath}`,
    }))
}

export function unresolvedReferenceCount(definition: WorkflowDefinition): number {
  return nodeDataSources(definition).filter((reference) => reference.reason).length
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}
