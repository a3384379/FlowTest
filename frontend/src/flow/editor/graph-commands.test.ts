/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import type { WorkflowDefinition } from '../../lib/api'
import { analyzeGraph, editorNode, restoreEditedNode } from './graph-analysis'
import {
  applyDeletion,
  applyNodePositions,
  connectGraphNodes,
  planDeletion,
  reconnectGraphEdge,
  swapBranches,
} from './graph-commands'

function fixture(name: string): unknown {
  return JSON.parse(
    readFileSync(resolve(process.cwd(), '../docs/workflow-editor-codeplan/fixtures', name), 'utf8'),
  )
}
const linear = fixture('01-linear.json')
const mapped = fixture('03-mapped-edge.json')
const cleanup = fixture('05-cleanup-phase.json')
const capability = fixture('08-capability-start.json')
const graph = (value: unknown) => structuredClone(value) as WorkflowDefinition
const selection = (nodeIds: string[] = [], edgeIds: string[] = []) => ({
  nodeIds,
  edgeIds,
  primary: null,
})

describe('workflow graph commands', () => {
  it('DEL01/04 deletes and retains a recoverable complete mapped edge without mutating input', () => {
    const definition = graph(mapped)
    const original = structuredClone(definition)
    const plan = planDeletion(definition, selection([], ['a-b']))
    expect(plan.mappingCount).toBe(1)
    expect(plan.requiresConfirmation).toBe(true)
    const result = applyDeletion(definition, plan)
    expect(result.kind).toBe('changed')
    if (result.kind === 'changed')
      expect(result.definition.edges.map((edge) => edge.id)).toEqual(['s-a', 'b-e'])
    expect(definition).toEqual(original)
  })
  it('DEL06 protects legacy and capability boundaries', () => {
    for (const input of [linear, capability]) {
      const definition = graph(input)
      const plan = planDeletion(definition, selection(['start', 'end']))
      expect(plan.protectedNodeIds).toEqual(['start', 'end'])
      expect(applyDeletion(definition, plan).kind).toBe('unchanged')
    }
  })
  it('DEL07 blocks deletion referenced by a retained cleanup node', () => {
    const definition = graph(cleanup)
    const plan = planDeletion(definition, selection(['api']))
    expect(plan.references.some((issue) => issue.nodeId === 'cleanup')).toBe(true)
    expect(applyDeletion(definition, plan).kind).toBe('blocked')
  })
  it('DATA05 distinguishes cleanup from unreachable main nodes', () => {
    expect(analyzeGraph(graph(cleanup))).toEqual([])
    const definition = graph(linear)
    definition.edges.pop()
    expect(analyzeGraph(definition).some((issue) => issue.code === 'UNREACHABLE_END')).toBe(true)
  })
  it('EDGE03 rejects cycles, boundaries and cross-phase connections', () => {
    const definition = graph(cleanup)
    for (const [sourceId, targetId] of [
      ['api', 'api'],
      ['api', 'start'],
      ['end', 'api'],
      ['api', 'cleanup'],
    ]) {
      expect(
        connectGraphNodes(definition, { sourceId, targetId, branch: null, edgeId: 'new' }).kind,
      ).toBe('blocked')
    }
  })
  it('EDGE05 preserves mapping paths and rebinds endpoint IDs in one edit', () => {
    const definition = graph(mapped)
    definition.nodes.push({ ...definition.nodes[2], id: 'api3' })
    const result = reconnectGraphEdge(definition, 'a-b', {
      sourceId: 'api',
      targetId: 'api3',
      branch: null,
      edgeId: 'ignored',
    })
    expect(result.kind).toBe('changed')
    if (result.kind !== 'changed') return
    const edge = result.definition.edges.find((item) => item.id === 'a-b')!
    expect(edge.mappings[0].source.path).toBe('body.id')
    expect(edge.mappings[0].target.node_id).toBe('api3')
    expect(edge.mappings[0].transform).toEqual(definition.edges[1].mappings[0].transform)
    expect(definition.edges[1].target).toBe('api2')
  })
  it('HIST05/DATA07 treats equal positions as no-op and invalid positions atomically', () => {
    const definition = graph(linear)
    expect(
      applyNodePositions(definition, [{ id: 'api', position: definition.nodes[1].position }]).kind,
    ).toBe('unchanged')
    expect(
      applyNodePositions(definition, [
        { id: 'api', position: { x: 30, y: 50 } },
        { id: 'end', position: { x: NaN, y: 0 } },
      ]).kind,
    ).toBe('blocked')
    expect(definition).toEqual(linear)
  })
})

it('accepts true and false branches to the same target and swaps them atomically', () => {
  const definition = graph(linear)
  const condition = {
    ...definition.nodes[1],
    type: 'condition' as const,
    config: { source_node_id: 'start', expression: 'ready', expected: true },
  }
  const base = {
    ...definition,
    nodes: definition.nodes.map((node) => (node.id === condition.id ? condition : node)),
    edges: [],
  }
  const connection = {
    sourceId: condition.id,
    targetId: 'end',
    branch: 'true' as const,
    edgeId: 'true-edge',
  }
  const first = connectGraphNodes(base, connection)
  expect(first.kind).toBe('changed')
  if (first.kind !== 'changed') throw new Error('connection failed')
  expect(connectGraphNodes(first.definition, { ...connection, edgeId: 'duplicate' }).kind).toBe(
    'blocked',
  )
  expect(connectGraphNodes(base, { ...connection, branch: null }).kind).toBe('blocked')
  const second = connectGraphNodes(first.definition, {
    ...connection,
    branch: 'false',
    edgeId: 'false-edge',
  })
  expect(second.kind).toBe('changed')
  if (second.kind !== 'changed') throw new Error('connection failed')
  const swapped = swapBranches(second.definition, condition.id)
  expect(swapped.kind).toBe('changed')
  if (swapped.kind !== 'changed') throw new Error('swap failed')
  expect(swapped.definition.edges.map((edge) => [edge.id, edge.condition])).toEqual([
    ['true-edge', 'false'],
    ['false-edge', 'true'],
  ])
  expect(swapBranches(first.definition, condition.id).kind).toBe('unchanged')
})
it('does not alter an invalid reconnect or same-endpoint reconnect', () => {
  const definition = graph(linear)
  const edge = definition.edges[0]
  const input = {
    sourceId: edge.source,
    targetId: edge.target,
    branch: edge.condition,
    edgeId: edge.id,
  }
  expect(reconnectGraphEdge(definition, edge.id, input).kind).toBe('unchanged')
  expect(reconnectGraphEdge(definition, 'missing', input).kind).toBe('unchanged')
  expect(reconnectGraphEdge(definition, edge.id, { ...input, targetId: 'start' }).kind).toBe(
    'blocked',
  )
  for (const edgeId of ['', 'x'.repeat(129), definition.edges[1].id]) {
    expect(
      connectGraphNodes({ ...definition, edges: [definition.edges[1]] }, { ...input, edgeId }).kind,
    ).toBe('blocked')
  }
})
it('diagnoses malformed boundaries, mapping endpoints, cleanup budget, and missing references', () => {
  const definition = graph(cleanup)
  const invalid = {
    ...definition,
    nodes: definition.nodes
      .map((node) =>
        node.phase === 'cleanup'
          ? { ...node, type: 'subflow' as const, cleanup_for: ['missing'] }
          : node,
      )
      .filter((node) => node.type !== 'end'),
    run_policy: undefined,
  }
  const codes = analyzeGraph(invalid).map((issue) => issue.code)
  expect(codes).toContain('END_COUNT')
  expect(codes).toContain('CLEANUP_REFERENCE')
  expect(codes).toContain('CLEANUP_BUDGET')
  const mappedDefinition = graph(mapped)
  mappedDefinition.edges[1].mappings[0].target.node_id = 'wrong'
  expect(analyzeGraph(mappedDefinition).map((issue) => issue.code)).toContain('MAPPING_ENDPOINT')
  const duplicateData = {
    ...graph(linear),
    nodes: [
      { ...graph(linear).nodes[0], type: 'dataset' as const },
      { ...graph(linear).nodes[1], type: 'dataset' as const },
    ],
  }
  expect(analyzeGraph(duplicateData).map((issue) => issue.code)).toEqual(
    expect.arrayContaining(['START_COUNT', 'DATASET_COUNT']),
  )
})
it('preserves legacy capability representation and refuses opaque retained references on deletion', () => {
  const definition = graph(capability)
  const original = definition.nodes[0]
  expect(editorNode(original).type).toBe('start')
  expect(restoreEditedNode(original, { ...editorNode(original), name: '开始改名' })).toMatchObject({
    type: 'capability',
    capability_id: original.capability_id,
    configuration: original.configuration,
  })
  const opaque = {
    ...graph(linear).nodes[1],
    id: 'opaque',
    type: 'capability' as const,
    capability_id: 'unknown.extension',
    bindings: [{ input: 'x', expression: 'node_outputs.api.body' }],
  }
  const withOpaque = { ...graph(linear), nodes: [...graph(linear).nodes, opaque] }
  const plan = planDeletion(withOpaque, selection(['api']))
  expect(plan.references.map((issue) => issue.code)).toEqual(
    expect.arrayContaining(['BINDING_REVIEW', 'CAPABILITY_REVIEW']),
  )
  expect(applyDeletion(withOpaque, plan).kind).toBe('blocked')
  expect(applyDeletion(withOpaque, planDeletion(withOpaque, selection())).kind).toBe('unchanged')
})

it.each([
  '01-linear.json',
  '02-conditional-branches.json',
  '03-mapped-edge.json',
  '04-extended-request.json',
  '05-cleanup-phase.json',
  '06-json-parse-mapping.json',
  '07-disconnected-local-draft.json',
  '08-capability-start.json',
])(
  'DATA02/03/04/05 preserves every non-position field through a position round trip: %s',
  (name) => {
    const original = graph(fixture(name))
    const result = applyNodePositions(
      original,
      original.nodes.map((node) => ({
        id: node.id,
        position: { x: node.position.x + 37, y: node.position.y + 19 },
      })),
    )
    expect(result.kind).toBe('changed')
    if (result.kind !== 'changed') throw new Error('Expected position change')
    const restored = applyNodePositions(
      result.definition,
      original.nodes.map((node) => ({ id: node.id, position: node.position })),
    )
    expect(restored.kind).toBe('changed')
    if (restored.kind !== 'changed') throw new Error('Expected position restoration')
    expect(restored.definition).toEqual(original)
  },
)

it('accepts ordinary snapshot edges when serialization omits null conditions', () => {
  const snapshot = JSON.parse(
    JSON.stringify(linear, (_key, value) => (value === null ? undefined : value)),
  ) as WorkflowDefinition
  expect(analyzeGraph(snapshot)).toEqual([])
  expect(planDeletion(snapshot, selection([], [snapshot.edges[0].id])).requiresConfirmation).toBe(
    false,
  )
})
