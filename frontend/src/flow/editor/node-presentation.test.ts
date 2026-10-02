import { describe, expect, it } from 'vitest'
import { workflowDefinition } from '../../test/fixtures'
import { dataReferences, nodePresentation } from './node-presentation'

describe('workflow presentation data', () => {
  it('derives references from saved contracts without changing execution edges or interpreting literal values', () => {
    const definition = structuredClone(workflowDefinition)
    const target = {
      ...definition.nodes[0],
      id: 'assert',
      type: 'assert' as const,
      name: '金额断言',
    }
    definition.nodes.push(target)
    target.config = { source_node_id: 'api', expected_source_node_id: 'missing' }
    target.configuration = {
      inputs: {
        actual: { kind: 'node_output', node_id: 'api', path: ['body'] },
        literal: { kind: 'literal', value: { kind: 'node_output', node_id: 'start', path: [] } },
      },
    }
    const before = structuredClone(definition)
    expect(dataReferences(definition)).toEqual([
      { id: 'data-reference:api:assert', source: 'api', target: 'assert', label: '数据引用' },
    ])
    expect(definition).toEqual(before)
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
