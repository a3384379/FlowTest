import type { WorkflowDefinition, WorkflowNode } from '../../lib/api'
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
  return { summary: nodeSummary(node, definition), regions }
}

function nodeSummary(node: WorkflowNode, definition: WorkflowDefinition): string {
  const config = effectiveConfig(node)
  const source = sourceSummary(config, definition)
  if (source) return source
  const type = resolveEffectiveNodeType(node)
  if (type === 'api')
    return typeof config.api_version === 'number'
      ? `接口资产 · v${config.api_version}`
      : '选择接口并配置请求'
  if (type === 'start') return '流程入口'
  if (type === 'end') return '流程出口'
  if (type === 'delay' && typeof config.seconds === 'number') return `等待 ${config.seconds} 秒`
  if (node.capability_id?.startsWith('flow.control.')) return controlSummary(config)
  return '点击节点查看配置'
}

function sourceSummary(
  config: Record<string, unknown>,
  definition: WorkflowDefinition,
): string | null {
  if (typeof config.source_node_id !== 'string' || !config.source_node_id) return null
  const source = definition.nodes.find((item) => item.id === config.source_node_id)
  return source ? `来源：${source.name}` : '来源未解析 · 请核对配置'
}

function controlSummary(config: Record<string, unknown>): string {
  const policy = record(config.policy)
  const parts: string[] = []
  if (typeof config.count === 'number') parts.push(`重复 ${config.count} 次`)
  if (typeof policy.max_iterations === 'number') parts.push(`上限 ${policy.max_iterations} 轮`)
  if (typeof policy.concurrency === 'number') parts.push(`并发 ${policy.concurrency}`)
  return parts.join(' · ') || '配置条件与内部步骤'
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
