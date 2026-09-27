import type { WorkflowDefinition, WorkflowNode, WorkflowRegion } from '../../lib/api'
import { addControlBlock, type ControlBlockKind } from '../../flow/editor/control-blocks'

export type WorkflowTemplateKind =
  | 'linear'
  | 'foreach_three'
  | 'repeat_three'
  | 'async_poll'
  | 'pagination'
  | 'cursor_pagination'
  | 'parallel_compare'
  | 'try_finally'

export const WORKFLOW_TEMPLATES: { value: WorkflowTemplateKind; label: string; help: string }[] = [
  { value: 'linear', label: '普通接口请求', help: '开始 → 接口 → 结束' },
  { value: 'foreach_three', label: '三组数据驱动', help: '示例集合 [1, 2, 3]，串行执行接口' },
  { value: 'repeat_three', label: '重复三次', help: '同一个接口严格执行三轮' },
  {
    value: 'async_poll',
    label: '异步状态轮询',
    help: '提交一次任务，再用只读 GET 接口按 body.status 轮询',
  },
  { value: 'pagination', label: '分页查询', help: 'page 从 1 到 3，检查接口的 page 参数' },
  { value: 'cursor_pagination', label: '游标分页', help: '按响应的 nextCursor 和 hasNext 继续' },
  { value: 'parallel_compare', label: '并行请求对照', help: '并行请求两次，请先确认接口只读' },
  { value: 'try_finally', label: '请求与清理', help: 'Try 中请求，Finally 中编辑清理步骤' },
]

const CONTROL_KIND: Record<
  Exclude<WorkflowTemplateKind, 'linear' | 'async_poll'>,
  ControlBlockKind
> = {
  foreach_three: 'foreach',
  repeat_three: 'repeat',
  pagination: 'while',
  cursor_pagination: 'while',
  parallel_compare: 'parallel',
  try_finally: 'try',
}

export function buildWorkflowTemplate(
  base: WorkflowDefinition,
  kind: WorkflowTemplateKind = 'linear',
  options: { submitApiId?: string; submitApiVersion?: number } = {},
): WorkflowDefinition {
  if (kind === 'linear') return base
  if (kind === 'async_poll') {
    return asyncPollingTemplate(base, options.submitApiId, options.submitApiVersion)
  }
  const expanded = replaceMainApiWithControl(base, CONTROL_KIND[kind], kind)
  if (kind !== 'pagination' && kind !== 'cursor_pagination') return expanded
  return paginationTemplate(expanded, kind)
}

function asyncPollingTemplate(
  base: WorkflowDefinition,
  submitApiId?: string,
  submitApiVersion?: number,
): WorkflowDefinition {
  const poll = base.nodes.find((node) => node.id === 'api')
  if (!submitApiId || !poll || poll.config.api_definition_id === submitApiId) {
    throw new Error('异步轮询模板需要两个不同的提交与查询接口')
  }
  const submit: WorkflowNode = {
    ...poll,
    id: 'submit',
    name: '提交任务一次',
    position: { x: 280, y: 80 },
    config: {
      api_definition_id: submitApiId,
      ...(submitApiVersion ? { api_version: submitApiVersion } : {}),
      request_overrides: {},
      max_retries: 0,
    },
  }
  return {
    ...base,
    nodes: [
      base.nodes[0],
      submit,
      ...base.nodes.slice(1).map((node) =>
        node.id === 'api'
          ? {
              ...node,
              name: '查询任务状态',
              position: { x: 560, y: 80 },
              config: {
                ...node.config,
                polling: {
                  expression: 'body.status',
                  operator: 'equals',
                  expected: 'SUCCESS',
                  terminal_failure_values: ['FAILED'],
                  max_attempts: 20,
                  interval_seconds: 1,
                  timeout_seconds: 30,
                },
              },
            }
          : { ...node, position: { x: 840, y: 80 } },
      ),
    ],
    edges: [
      { id: 'start-submit', source: 'start', target: 'submit', condition: null, mappings: [] },
      {
        id: 'submit-api',
        source: 'submit',
        target: 'api',
        condition: null,
        mappings: [
          {
            source: { node_id: 'submit', path: 'body.taskId' },
            transform: { kind: 'identity', template: '{{value}}' },
            target: { node_id: 'api', location: 'query', key: 'taskId' },
          },
        ],
      },
      { id: 'api-end', source: 'api', target: 'end', condition: null, mappings: [] },
    ],
  }
}

function paginationTemplate(
  expanded: WorkflowDefinition,
  kind: 'pagination' | 'cursor_pagination',
): WorkflowDefinition {
  return {
    ...expanded,
    nodes: expanded.nodes.map((node) =>
      node.capability_id === 'flow.control.while'
        ? {
            ...node,
            configuration: {
              ...node.configuration,
              ...(kind === 'cursor_pagination' ? cursorState() : pageState()),
            },
          }
        : node,
    ),
  }
}

function replaceMainApiWithControl(
  base: WorkflowDefinition,
  kind: ControlBlockKind,
  template: WorkflowTemplateKind,
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
    regions: expanded.regions?.map((region) => templateRegion(region, kind, template, api)),
  }
}

function templateRegion(
  region: WorkflowRegion,
  kind: ControlBlockKind,
  template: WorkflowTemplateKind,
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
            : template === 'cursor_pagination'
              ? { name: 'cursor', value: '{{state.cursor}}', enabled: true }
              : { name: 'page', value: '{{state.page}}', enabled: true },
        ],
      },
    }
  }
  return { ...region, nodes: [node], entry_node_id: node.id, exit_node_ids: [node.id] }
}

function pageState() {
  return {
    condition: {
      kind: 'compare',
      left: { kind: 'variable', scope: 'state', path: ['page'] },
      operator: 'lt',
      right: { kind: 'literal', value: 4 },
    },
    state: { page: { kind: 'literal', value: 1 } },
    update: { page: { kind: 'add', value: { kind: 'literal', value: 1 } } },
    policy: { concurrency: 1, max_iterations: 3, timeout_seconds: 120, on_error: 'stop' },
  }
}

function cursorState() {
  return {
    condition: {
      kind: 'compare',
      left: { kind: 'variable', scope: 'state', path: ['hasNext'] },
      operator: 'equals',
      right: { kind: 'literal', value: true },
    },
    state: {
      cursor: { kind: 'literal', value: '' },
      hasNext: { kind: 'literal', value: true },
    },
    update: {
      cursor: {
        kind: 'set',
        value: { kind: 'node_output', node_id: 'api', path: ['body', 'nextCursor'] },
      },
      hasNext: {
        kind: 'set',
        value: { kind: 'node_output', node_id: 'api', path: ['body', 'hasNext'] },
      },
    },
    policy: { concurrency: 1, max_iterations: 100, timeout_seconds: 120, on_error: 'stop' },
  }
}
