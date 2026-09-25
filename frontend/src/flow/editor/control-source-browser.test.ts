import { describe, expect, it } from 'vitest'

import { workflowDefinition } from '../../test/fixtures'
import type { WorkflowDefinition, WorkflowRegion } from '../../lib/api'
import { addControlBlock } from './control-blocks'
import { conditionStateSources } from './control-source-browser'

function example(): WorkflowDefinition {
  const expanded = addControlBlock(workflowDefinition, 'while')
  const owner = expanded.nodes.at(-1)!
  const body = expanded.regions![0]
  const sibling: WorkflowRegion = {
    ...body,
    id: 'sibling-region',
    owner_node_id: 'different-control',
    nodes: [
      { id: 'other-step', type: 'api', name: '兄弟分支', position: { x: 0, y: 0 }, config: {} },
    ],
    entry_node_id: 'other-step',
    exit_node_ids: ['other-step'],
  }
  return {
    ...expanded,
    runtime_inputs: [
      {
        name: 'caseId',
        value_type: 'string',
        required: true,
        nullable: false,
        description: '',
      },
    ],
    variables: { tenant: 'flowtest' },
    nodes: expanded.nodes.map((node) =>
      node.id === owner.id
        ? {
            ...node,
            configuration: {
              ...node.configuration,
              state: { page: { kind: 'literal', value: 1 } },
            },
          }
        : node,
    ),
    edges: [
      workflowDefinition.edges[0],
      { id: 'api-control', source: 'api', target: owner.id, condition: null, mappings: [] },
      { id: 'control-end', source: owner.id, target: 'end', condition: null, mappings: [] },
    ],
    regions: [{ ...body, inputs: { token: { kind: 'literal', value: 'x' } } }, sibling],
  }
}

describe('condition loop source browser', () => {
  it('lists declared inputs, guaranteed upstream outputs, and unavailable state reasons', () => {
    const definition = example()
    const owner = definition.nodes.at(-1)!
    const choices = conditionStateSources(definition, owner, 'initial')
    expect(choices.find((choice) => choice.key === 'runtime:caseId')?.source).toEqual({
      kind: 'variable',
      scope: 'runtime',
      path: ['caseId'],
    })
    expect(choices.find((choice) => choice.key === 'workflow:tenant')?.source).toEqual({
      kind: 'variable',
      scope: 'workflow',
      path: ['tenant'],
    })
    expect(choices.find((choice) => choice.key === 'output:api')?.source).toEqual({
      kind: 'node_output',
      node_id: 'api',
      path: [],
    })
    expect(choices.find((choice) => choice.key === 'state-before-start')?.reason).toContain(
      '初始化',
    )
    expect(
      choices.find((choice) => choice.key === 'outside:sibling-region:other-step')?.reason,
    ).toContain('作用域')
  })

  it('offers current state, iteration, region inputs, and completed body output for updates', () => {
    const definition = example()
    const owner = definition.nodes.at(-1)!
    const choices = conditionStateSources(definition, owner, 'update')
    expect(choices.find((choice) => choice.key === 'state:page')?.source).toEqual({
      kind: 'variable',
      scope: 'state',
      path: ['page'],
    })
    expect(choices.find((choice) => choice.key === 'loop:index')?.source).toEqual({
      kind: 'variable',
      scope: 'loop',
      path: ['index'],
    })
    expect(choices.find((choice) => choice.key === 'input:token')?.source).toEqual({
      kind: 'variable',
      scope: 'input',
      path: ['token'],
    })
    expect(
      choices.find((choice) => choice.key === `output:${definition.regions![0].entry_node_id}`)
        ?.source,
    ).toMatchObject({ kind: 'node_output' })
  })

  it('explains when an upstream node can be skipped', () => {
    const definition = example()
    const owner = definition.nodes.at(-1)!
    const branching = {
      ...definition,
      edges: [
        ...definition.edges,
        { id: 'start-control', source: 'start', target: owner.id, condition: null, mappings: [] },
      ],
    }
    const choices = conditionStateSources(branching, owner, 'initial')
    expect(choices.find((choice) => choice.key === 'output:api')).toMatchObject({
      source: null,
      reason: '该节点可能尚未执行',
    })
  })
})
