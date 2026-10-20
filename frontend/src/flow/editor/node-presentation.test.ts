import { describe, expect, it } from 'vitest'
import { apiDefinition, workflowDefinition } from '../../test/fixtures'
import type { WorkflowNode } from '../../lib/api'
import {
  dataReferences,
  nodeDataSources,
  nodePresentation,
  unresolvedReferenceCount,
} from './node-presentation'

describe('workflow presentation data', () => {
  it('explains legacy extraction, comparison and iteration from the saved definition', () => {
    const base = workflowDefinition.nodes[1]
    const config = {
      source_node_id: 'api',
      expression: 'body.amount',
      operator: 'gt',
      expected: 10,
    }
    const summary = (type: WorkflowNode['type'], overrides = {}) =>
      nodePresentation({ ...base, type, config: { ...config, ...overrides } }, workflowDefinition)
        .summary
    expect(summary('assert')).toBe('查询用户 · body.amount 大于 10')
    expect(
      summary('condition', {
        expected_source_node_id: 'start',
        expected_expression: 'variables.limit',
      }),
    ).toBe('查询用户 · body.amount 大于 开始 · variables.limit')
    expect(summary('extract', { variable: 'amount' })).toBe('提取 查询用户 · body.amount → amount')
    expect(
      summary('for_each', { expression: 'body.items', workflow_version: 3, concurrency: 2 }),
    ).toBe('遍历 查询用户 · body.items · 子流程 v3 · 并发 2')
    expect(summary('assert', { source_node_id: 'missing' })).toContain('节点不存在（missing）')
  })

  it('explains compound conditions, unary checks and switch branches without inventing operands', () => {
    const definition = structuredClone(workflowDefinition)
    const compare = {
      kind: 'compare',
      left: { kind: 'variable', scope: 'state', path: ['ready'] },
      operator: 'exists',
    }
    const node: WorkflowNode = {
      ...definition.nodes[1],
      type: 'capability',
      capability_id: 'flow.control.until',
      configuration: {
        condition: {
          kind: 'all',
          conditions: [compare, { kind: 'not', condition: { kind: 'any', conditions: [compare] } }],
        },
        policy: { max_iterations: 8, timeout_seconds: 45 },
      },
    }
    const before = structuredClone(node)
    expect(nodePresentation(node, definition).summary).toBe(
      '直到：（state.ready 存在 且 非（（state.ready 存在））） · 上限 8 轮 · 最长 45 秒',
    )
    node.capability_id = 'flow.control.switch'
    node.configuration = {
      mode: 'rules',
      branches: [{ id: 'ready', label: '已就绪', condition: compare }],
    }
    expect(nodePresentation(node, definition).summary).toContain(
      '1 个分支 · 按条件匹配 · 已就绪：state.ready 存在',
    )
    expect(before.configuration?.condition).toEqual({
      kind: 'all',
      conditions: [compare, { kind: 'not', condition: { kind: 'any', conditions: [compare] } }],
    })
    expect(definition).toEqual(workflowDefinition)
  })

  it('marks truncated values and unknown control expressions explicitly', () => {
    const node: WorkflowNode = {
      ...workflowDefinition.nodes[1],
      type: 'capability',
      capability_id: 'flow.control.if',
      configuration: {
        condition: {
          kind: 'compare',
          left: { kind: 'literal', value: 'x'.repeat(150) },
          operator: 'equals',
          right: { kind: 'literal', value: 'y' },
        },
      },
    }
    expect(nodePresentation(node, workflowDefinition).summary).toContain('…（配置中查看完整值）')
    node.configuration = { condition: { kind: 'unknown' } }
    expect(nodePresentation(node, workflowDefinition).summary).toContain('条件未解析（unknown）')
  })

  it('uses request metadata only when it belongs to the pinned API version', () => {
    const node = {
      ...workflowDefinition.nodes[1],
      config: { api_definition_id: apiDefinition.id, api_version: 1 },
    }
    const asset = {
      ...apiDefinition,
      name: '订单查询',
      current_version: 1,
      method: 'GET',
      path: '/orders',
    }
    expect(nodePresentation(node, workflowDefinition, [asset]).summary).toContain('GET /orders')
    expect(
      nodePresentation(node, workflowDefinition, [{ ...asset, current_version: 2 }]).summary,
    ).toContain('固定版本请求摘要未提供')
    expect(
      nodePresentation(node, workflowDefinition, [{ ...asset, current_version: 2 }]).summary,
    ).not.toContain('GET /orders')
  })

  it('derives references from saved contracts without changing execution edges or interpreting literal values', () => {
    const definition = structuredClone(workflowDefinition)
    const target = {
      ...definition.nodes[0],
      id: 'assert',
      type: 'capability' as const,
      capability_id: 'flow.control.foreach',
      name: '金额断言',
    }
    definition.nodes.push(target)
    target.configuration = {
      inputs: {
        expected: { kind: 'node_output', node_id: 'missing', path: ['body', 'expected'] },
        actual: { kind: 'node_output', node_id: 'api', path: ['body'] },
        second: { kind: 'node_output', node_id: 'api', path: ['body', 'items', 0, 'unit.price'] },
        loop: { kind: 'variable', scope: 'loop', path: ['item', 'amount'] },
        literal: { kind: 'literal', value: { kind: 'node_output', node_id: 'start', path: [] } },
      },
    }
    const before = structuredClone(definition)
    const sources = nodeDataSources(definition, target.id)
    expect(sources.filter((source) => source.sourceId === 'api')).toHaveLength(2)
    expect(sources).toContainEqual(
      expect.objectContaining({
        kind: 'node_output',
        path: '$.body.items[0]["unit.price"]',
        targetPath: '$.inputs.second',
        scope: '主流程',
      }),
    )
    expect(sources).toContainEqual(
      expect.objectContaining({
        kind: 'variable',
        path: '$.item.amount',
        scope: '循环变量 · loop',
        targetPath: '$.inputs.loop',
      }),
    )
    expect(sources).toContainEqual(
      expect.objectContaining({ sourceId: 'missing', reason: '来源节点不存在' }),
    )
    expect(dataReferences(definition)).toHaveLength(2)
    expect(dataReferences(definition).every((reference) => reference.source === 'api')).toBe(true)
    expect(new Set(dataReferences(definition).map((reference) => reference.id)).size).toBe(2)
    expect(unresolvedReferenceCount(definition)).toBe(1)
    expect(definition).toEqual(before)
  })

  it('keeps opaque bindings and invalid sources explicit without inventing dependencies', () => {
    const definition = structuredClone(workflowDefinition)
    const target = definition.nodes.find((node) => node.id === 'api')!
    target.type = 'capability'
    target.capability_id = 'flow.control.group'
    target.configuration = {
      inputs: { invalid: { kind: 'node_output', node_id: 'start', path: 'body' } },
    }
    target.bindings = [{ input: 'token', expression: '{{unknown.token}}' }]
    expect(nodeDataSources(definition, 'api')).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ targetPath: '$.inputs.invalid', reason: '来源契约未解析' }),
        expect.objectContaining({
          targetPath: 'bindings.token',
          expression: '{{unknown.token}}',
          reason: '表达式未解析',
        }),
      ]),
    )
    expect(dataReferences(definition)).toEqual([])
    expect(unresolvedReferenceCount(definition)).toBe(2)
  })

  it('does not interpret assertion literals or HTTP payloads as control sources', () => {
    const definition = structuredClone(workflowDefinition)
    const literal = { kind: 'node_output', node_id: 'start', path: ['value'] }
    const target = definition.nodes.find((node) => node.id === 'api')!
    target.configuration = { body: literal }
    target.config = { body: literal }
    const assertion = {
      ...target,
      id: 'assert',
      type: 'assert' as const,
      config: {
        source_node_id: 'api',
        expression: 'body',
        expected: literal,
      },
    }
    definition.nodes.push(assertion)
    expect(nodeDataSources(definition, 'api')).toEqual([])
    expect(nodeDataSources(definition, 'assert')).toHaveLength(1)
    expect(dataReferences(definition).map((reference) => reference.source)).toEqual(['api'])
  })

  it('focuses direct sources and reports the actual region of nested nodes', () => {
    const definition = structuredClone(workflowDefinition)
    const end = definition.nodes.find((node) => node.id === 'end')!
    end.type = 'extract'
    end.config = { source_node_id: 'api', expression: 'body.id' }
    const api = definition.nodes.find((node) => node.id === 'api')!
    api.type = 'extract'
    api.config = { source_node_id: 'start', expression: 'variables.id' }
    expect(dataReferences(definition, end.id).map((reference) => reference.target)).toEqual(['end'])
    const inner = {
      ...end,
      id: 'inner',
      name: '内部断言',
      config: { source_node_id: 'inside', expression: 'body.amount' },
    }
    definition.regions = [
      {
        id: 'body-region',
        owner_node_id: api.id,
        role: 'body',
        nodes: [{ ...api, id: 'inside', name: '内部请求', config: {} }, inner],
        edges: [],
        entry_node_id: 'inside',
        exit_node_ids: ['inner'],
        inputs: {},
        outputs: {},
      },
    ]
    expect(nodeDataSources(definition, inner.id)).toContainEqual(
      expect.objectContaining({ sourceId: 'inside', scope: '查询用户 / 内部步骤 · body-region' }),
    )
    expect(dataReferences(definition).some((reference) => reference.target === inner.id)).toBe(
      false,
    )
  })

  it('uses owned region contents for previews and leaves empty regions explicit', () => {
    const definition = structuredClone(workflowDefinition)
    const owner = definition.nodes.find((node) => node.id === 'api')!
    owner.type = 'capability'
    owner.capability_id = 'flow.control.repeat'
    owner.configuration = { count: 3, policy: { concurrency: 1, max_iterations: 10 } }
    definition.regions = [
      {
        id: 'body',
        owner_node_id: owner.id,
        role: 'body',
        nodes: [],
        edges: [],
        entry_node_id: null,
        exit_node_ids: [],
        inputs: {},
        outputs: {},
      },
    ]
    expect(nodePresentation(owner, definition)).toEqual({
      summary: '重复 3 次 · 上限 10 轮 · 并发 1',
      regions: [{ id: 'body', label: '内部步骤', steps: [] }],
    })
    expect(definition.regions[0].nodes).toEqual([])
  })
})
