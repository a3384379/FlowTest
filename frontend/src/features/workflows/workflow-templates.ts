import type { WorkflowDefinition, WorkflowNode, WorkflowRegion } from '../../lib/api'
import { addControlBlock, type ControlBlockKind } from '../../flow/editor/control-blocks'

export type WorkflowTemplateKind =
  | 'linear'
  | 'foreach_three'
  | 'repeat_three'
  | 'async_poll'
  | 'pagination'
  | 'parallel_compare'
  | 'try_finally'

export const WORKFLOW_TEMPLATES: { value: WorkflowTemplateKind; label: string; help: string }[] = [
  { value: 'linear', label: '普通接口请求', help: '开始 → 接口 → 结束' },
  { value: 'foreach_three', label: '三组数据驱动', help: '示例集合 [1, 2, 3]，串行执行接口' },
  { value: 'repeat_three', label: '重复三次', help: '同一个接口严格执行三轮' },
  { value: 'async_poll', label: '异步状态轮询', help: '最多查询三次，按 body.status 判断' },
  { value: 'pagination', label: '分页查询', help: 'page 从 1 到 3，检查接口的 page 参数' },
  { value: 'parallel_compare', label: '并行请求对照', help: '并行请求两次，请先确认接口只读' },
  { value: 'try_finally', label: '请求与清理', help: 'Try 中请求，Finally 中编辑清理步骤' },
]

export function buildWorkflowTemplate(
  base: WorkflowDefinition,
  kind: WorkflowTemplateKind = 'linear',
): WorkflowDefinition {
  if (kind === 'linear') return base
  if (kind === 'async_poll') {
    return {
      ...base,
      nodes: base.nodes.map((node) =>
        node.id === 'api'
          ? {
              ...node,
              config: {
                ...node.config,
                polling: {
                  expression: 'body.status',
                  operator: 'equals',
                  expected: 'success',
                  terminal_failure_values: ['failed'],
                  max_attempts: 3,
                  interval_seconds: 1,
                  timeout_seconds: 30,
                },
              },
            }
          : node,
      ),
    }
  }
  const controlKind: ControlBlockKind =
    kind === 'foreach_three'
      ? 'foreach'
      : kind === 'repeat_three'
        ? 'repeat'
        : kind === 'pagination'
          ? 'while'
          : kind === 'parallel_compare'
            ? 'parallel'
            : 'try'
  const expanded = replaceMainApiWithControl(base, controlKind)
  if (kind !== 'pagination') return expanded
  return {
    ...expanded,
    nodes: expanded.nodes.map((node) =>
      node.capability_id === 'flow.control.while'
        ? {
            ...node,
            configuration: {
              ...node.configuration,
              condition: {
                kind: 'compare',
                left: { kind: 'variable', scope: 'state', path: ['page'] },
                operator: 'lt',
                right: { kind: 'literal', value: 4 },
              },
              state: { page: { kind: 'literal', value: 1 } },
              update: { page: { kind: 'add', value: { kind: 'literal', value: 1 } } },
              policy: { concurrency: 1, max_iterations: 3, timeout_seconds: 120, on_error: 'stop' },
            },
          }
        : node,
    ),
  }
}

function replaceMainApiWithControl(
  base: WorkflowDefinition,
  kind: ControlBlockKind,
): WorkflowDefinition {
  const api = base.nodes.find((node) => node.id === 'api')!
  const expanded = addControlBlock(base, kind)
  const owner = expanded.nodes.at(-1)!
  return {
    ...expanded,
    nodes: expanded.nodes
      .filter((node) => node.id !== api.id)
      .map((node) => (node.id === owner.id ? { ...node, position: api.position } : node)),
    edges: expanded.edges.map((edge) => ({
      ...edge,
      source: edge.source === api.id ? owner.id : edge.source,
      target: edge.target === api.id ? owner.id : edge.target,
    })),
    regions: expanded.regions?.map((region) => templateRegion(region, kind, api)),
  }
}

function templateRegion(
  region: WorkflowRegion,
  kind: ControlBlockKind,
  api: WorkflowNode,
): WorkflowRegion {
  if (kind === 'parallel' && region.role.startsWith('branch:')) {
    const branch = region.role.slice('branch:'.length)
    const node = {
      ...api,
      id: `api-${branch}`,
      name: `接口请求 · ${branch}`,
      position: { x: 0, y: 0 },
    }
    return { ...region, nodes: [node], entry_node_id: node.id, exit_node_ids: [node.id] }
  }
  if (region.role !== 'body' && region.role !== 'try') return region
  const node = { ...api, position: { x: 0, y: 0 } }
  if (kind === 'foreach' || kind === 'while') {
    node.config = {
      ...api.config,
      request_overrides: {
        query_parameters: [
          kind === 'foreach'
            ? { name: 'item', value: '{{loop.item}}', enabled: true }
            : { name: 'page', value: '{{state.page}}', enabled: true },
        ],
      },
    }
  }
  return { ...region, nodes: [node], entry_node_id: node.id, exit_node_ids: [node.id] }
}
