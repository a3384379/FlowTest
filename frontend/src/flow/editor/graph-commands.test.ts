/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import type { WorkflowDefinition } from '../../lib/api'
import { analyzeGraph, editorNode, restoreEditedNode } from './graph-analysis'
import {
  addControlBlock,
  addSwitchBranch,
  addTryCatch,
  appendRegionApi,
  appendRegionDelay,
  appendRegionSignal,
  connectRegionSteps,
  insertRegionApiAfter,
  insertRegionDelayAfter,
  insertNestedControlBlock,
  removeNestedControlBlock,
  removeSwitchBranch,
  removeTryCatch,
  setSwitchDefaultBehavior,
  setTryFinally,
} from './control-blocks'
import { insertNodeOnEdge, pasteNode } from '../workflow-graph'
import {
  applyDeletion,
  applyNodePositions,
  connectGraphNodes,
  planDeletion,
  reconnectGraphEdge,
  swapBranches,
  unwrapMainPath,
  unwrapSingleNode,
  wrapMainNode,
  wrapMainPath,
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
const nodeSelection = (id: string) => ({ kind: 'node' as const, id })
const edgeSelection = (id: string) => ({ kind: 'edge' as const, id })

describe('workflow graph commands', () => {
  it('adds and removes a Switch branch with its owned region in one definition update', () => {
    const base = addControlBlock(graph(linear), 'switch')
    const owner = base.nodes.at(-1)!
    const added = addSwitchBranch(base, owner.id)!
    const branches = added.nodes.at(-1)!.configuration!.branches as {
      id: string
      body: { region_id: string }
    }[]
    expect(branches).toHaveLength(3)
    expect(added.regions).toHaveLength(4)
    const newBranch = branches[2]
    expect(added.regions?.find((item) => item.id === newBranch.body.region_id)).toMatchObject({
      owner_node_id: owner.id,
      role: `case:${newBranch.id}`,
    })
    const removed = removeSwitchBranch(added, owner.id, newBranch.id)!
    expect(removed.nodes.at(-1)!.configuration!.branches).toEqual(owner.configuration!.branches)
    expect(removed.regions).toEqual(base.regions)
    expect(removeSwitchBranch(base, owner.id, 'missing')).toBeNull()
  })

  it('changes Switch default behavior without leaving an orphaned region', () => {
    const base = addControlBlock(graph(linear), 'switch')
    const owner = base.nodes.at(-1)!
    const skipped = setSwitchDefaultBehavior(base, owner.id, 'skip')!
    expect(skipped.nodes.at(-1)!.configuration!.default).toEqual({ behavior: 'skip', body: null })
    expect(skipped.regions?.map((item) => item.role)).toEqual(['case:first', 'case:second'])
    const restored = setSwitchDefaultBehavior(skipped, owner.id, 'run')!
    const current = restored.nodes.at(-1)!.configuration!.default as {
      behavior: string
      body: { region_id: string }
    }
    expect(current.behavior).toBe('run')
    expect(restored.regions?.find((item) => item.id === current.body.region_id)?.role).toBe(
      'default',
    )
  })

  it('edits Try catches and Finally together with their regions', () => {
    const base = addControlBlock(graph(linear), 'try')
    const owner = base.nodes.at(-1)!
    const added = addTryCatch(base, owner.id)!
    const catches = added.nodes.at(-1)!.configuration!.catches as {
      id: string
      error_codes: string[]
      body: { region_id: string }
    }[]
    expect(catches).toHaveLength(2)
    expect(catches[1].error_codes).not.toEqual(catches[0].error_codes)
    expect(added.regions?.find((item) => item.id === catches[1].body.region_id)).toMatchObject({
      owner_node_id: owner.id,
      role: `catch:${catches[1].id}`,
    })
    const removed = removeTryCatch(added, owner.id, catches[1].id)!
    expect(removed.nodes.at(-1)!.configuration!.catches).toEqual(owner.configuration!.catches)
    expect(removed.regions).toEqual(base.regions)

    const withoutFinally = setTryFinally(base, owner.id, false)!
    expect(withoutFinally.nodes.at(-1)!.configuration!.finally_body).toBeNull()
    expect(withoutFinally.regions?.some((item) => item.role === 'finally')).toBe(false)
    expect(removeTryCatch(withoutFinally, owner.id, 'known')).toBeNull()
    const restored = setTryFinally(withoutFinally, owner.id, true)!
    const finallyBody = restored.nodes.at(-1)!.configuration!.finally_body as {
      region_id: string
    }
    expect(restored.regions?.find((item) => item.id === finallyBody.region_id)?.role).toBe(
      'finally',
    )
  })

  it('reconnects a linear region by moving the target after the source atomically', () => {
    const base = addControlBlock(graph(linear), 'group').regions![0]
    const region = appendRegionDelay(appendRegionDelay(appendRegionDelay(base)!)!)!
    const ids = region.nodes.map((node) => node.id)
    const reordered = connectRegionSteps(region, ids[0], ids[3])!
    expect(reordered.nodes.map((node) => node.id)).toEqual([ids[0], ids[3], ids[1], ids[2]])
    expect(reordered.edges.map((edge) => edge.id)).toEqual(region.edges.map((edge) => edge.id))
    expect(reordered.edges.map((edge) => [edge.source, edge.target])).toEqual([
      [ids[0], ids[3]],
      [ids[3], ids[1]],
      [ids[1], ids[2]],
    ])
    expect(connectRegionSteps(region, ids[0], ids[1])).toBeNull()
    expect(connectRegionSteps(region, ids[1], ids[1])).toBeNull()
    expect(
      connectRegionSteps(
        { ...region, edges: [{ ...region.edges[0], condition: 'true' }, ...region.edges.slice(1)] },
        ids[0],
        ids[3],
      ),
    ).toBeNull()
  })

  it('inserts and removes a nested control with its descendant regions atomically', () => {
    const base = addControlBlock(graph(linear), 'group')
    const region = base.regions![0]
    const inserted = insertNestedControlBlock(base, region.id, region.entry_node_id!, 'if')!
    expect(inserted.nodes).toEqual(base.nodes)
    const parent = inserted.regions!.find((item) => item.id === region.id)!
    const nested = parent.nodes.at(-1)!
    expect(parent.edges).toEqual([
      expect.objectContaining({ source: region.entry_node_id, target: nested.id }),
    ])
    expect(inserted.regions?.filter((item) => item.owner_node_id === nested.id)).toHaveLength(2)
    const removed = removeNestedControlBlock(inserted, region.id, nested.id)!
    expect(removed.regions).toEqual(base.regions)
    expect(removed.nodes).toEqual(base.nodes)
  })

  it('rejects nested controls beyond the supported four-region depth', () => {
    let definition = addControlBlock(graph(linear), 'group')
    let target = definition.regions![0]
    for (let depth = 1; depth <= 4; depth += 1) {
      definition = insertNestedControlBlock(definition, target.id, target.entry_node_id!, 'group')!
      const nested = definition.regions!.find((item) => item.id === target.id)!.nodes.at(-1)!
      target = definition.regions!.find((item) => item.owner_node_id === nested.id)!
    }
    expect(
      insertNestedControlBlock(definition, target.id, target.entry_node_id!, 'group'),
    ).toBeNull()
  })

  it('updates a nested Switch and its owned branch regions together', () => {
    const base = addControlBlock(graph(linear), 'group')
    const body = base.regions![0]
    const nested = insertNestedControlBlock(base, body.id, body.entry_node_id!, 'switch')!
    const nodeId = nested.regions![0].nodes.at(-1)!.id
    const withBranch = addSwitchBranch(nested, nodeId)!
    const parentNode = withBranch.regions![0].nodes.at(-1)!
    expect(parentNode.configuration?.branches).toHaveLength(3)
    const newBranch = (parentNode.configuration?.branches as Array<{ id: string }>).at(-1)!
    expect(withBranch.regions?.find((item) => item.role === `case:${newBranch.id}`)).toBeDefined()
    const removed = removeSwitchBranch(withBranch, nodeId, newBranch.id)!
    expect(removed.regions![0].nodes.at(-1)!.configuration?.branches).toHaveLength(2)
    expect(removed.regions?.some((item) => item.role === `case:${newBranch.id}`)).toBe(false)
    const skipped = setSwitchDefaultBehavior(removed, nodeId, 'skip')!
    expect(skipped.regions![0].nodes.at(-1)!.configuration?.default).toEqual({
      behavior: 'skip',
      body: null,
    })
    expect(
      skipped.regions?.some((item) => item.owner_node_id === nodeId && item.role === 'default'),
    ).toBe(false)
  })

  it('extends a serial control region without changing its entry boundary', () => {
    const region = addControlBlock(graph(linear), 'foreach').regions![0]
    const expanded = appendRegionDelay(region)!
    expect(expanded.entry_node_id).toBe(region.entry_node_id)
    expect(expanded.nodes).toHaveLength(2)
    expect(expanded.edges).toEqual([
      expect.objectContaining({
        source: region.exit_node_ids[0],
        target: expanded.exit_node_ids[0],
      }),
    ])
    expect(expanded.nodes.at(-1)?.config.seconds).toBe(0)
  })
  it('starts an empty inline region with one versioned API step and rejects ambiguous exits', () => {
    const region = addControlBlock(graph(linear), 'group').regions![0]
    const empty = { ...region, nodes: [], edges: [], entry_node_id: null, exit_node_ids: [] }
    const apiId = 'aa200000-0000-4000-8000-000000000001'
    const created = appendRegionApi(empty, apiId, 3)!
    expect(created.nodes).toHaveLength(1)
    expect(created.entry_node_id).toBe(created.nodes[0].id)
    expect(created.exit_node_ids).toEqual([created.nodes[0].id])
    expect(created.nodes[0].config).toEqual(
      expect.objectContaining({ api_definition_id: apiId, api_version: 3 }),
    )
    expect(appendRegionApi({ ...region, exit_node_ids: [] }, apiId, 3)).toBeNull()
  })
  it('inserts an API between existing region steps without changing the entry or exit', () => {
    const first = addControlBlock(graph(linear), 'group').regions![0]
    const serial = appendRegionDelay(first)!
    const apiId = 'aa200000-0000-4000-8000-000000000001'
    const inserted = insertRegionApiAfter(serial, serial.entry_node_id!, apiId, 4)!
    const newNode = inserted.nodes[1]
    expect(newNode.config).toEqual(
      expect.objectContaining({ api_definition_id: apiId, api_version: 4 }),
    )
    expect(inserted.entry_node_id).toBe(serial.entry_node_id)
    expect(inserted.exit_node_ids).toEqual(serial.exit_node_ids)
    expect(newNode.position.x).toBe(serial.nodes[0].position.x + 220)
    expect(inserted.nodes[2].position.x).toBe(serial.nodes[1].position.x + 220)
    expect(inserted.edges).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ source: serial.entry_node_id, target: newNode.id }),
        expect.objectContaining({ source: newNode.id, target: serial.exit_node_ids[0] }),
      ]),
    )
    expect(serial.nodes).toHaveLength(2)
    const mappedRegion = structuredClone(serial)
    mappedRegion.edges[0].mappings = graph(mapped).edges[1].mappings
    expect(insertRegionDelayAfter(mappedRegion, serial.entry_node_id!)).toBeNull()
    const atExit = insertRegionDelayAfter(serial, serial.exit_node_ids[0])!
    expect(atExit.exit_node_ids).toEqual([atExit.nodes.at(-1)!.id])
  })
  it('adds loop signals only to a serial loop body', () => {
    const definition = addControlBlock(graph(linear), 'foreach')
    const owner = definition.nodes.at(-1)!
    const body = definition.regions![0]
    const updated = appendRegionSignal(body, owner, 'break')!
    expect(updated.nodes.at(-1)).toEqual(
      expect.objectContaining({ capability_id: 'flow.control.break', configuration: {} }),
    )
    expect(updated.edges.at(-1)).toEqual(
      expect.objectContaining({ source: body.exit_node_ids[0], target: updated.exit_node_ids[0] }),
    )
    expect(
      appendRegionSignal(
        body,
        { ...owner, configuration: { ...owner.configuration, policy: { concurrency: 2 } } },
        'continue',
      ),
    ).toBeNull()
    expect(
      appendRegionSignal(body, { ...owner, capability_id: 'flow.control.group' }, 'break'),
    ).toBeNull()
  })
  it('wraps one isolated main node atomically and keeps undo inputs intact', () => {
    const original = graph(linear)
    const result = wrapMainNode(original, 'api', 'foreach')
    expect(result.kind).toBe('changed')
    if (result.kind !== 'changed') return
    const wrapped = result.definition
    const owner = wrapped.nodes.find((node) => node.capability_id === 'flow.control.foreach')!
    const body = wrapped.regions!.find((region) => region.owner_node_id === owner.id)!
    expect(wrapped.nodes.some((node) => node.id === 'api')).toBe(false)
    expect(body.nodes).toEqual([expect.objectContaining({ id: 'api', type: 'api' })])
    expect(body.entry_node_id).toBe('api')
    expect(body.exit_node_ids).toEqual(['api'])
    expect(wrapped.edges).toEqual([
      expect.objectContaining({ id: 's-a', source: 'start', target: owner.id }),
      expect.objectContaining({ id: 'a-e', source: owner.id, target: 'end' }),
    ])
    expect(original.nodes.some((node) => node.id === 'api')).toBe(true)
    expect(analyzeGraph(wrapped)).toEqual([])
  })

  it('wraps a continuous two-step path with its original internal edge', () => {
    const original = graph(linear)
    const second = {
      ...structuredClone(original.nodes[1]),
      id: 'next',
      name: '下一个接口',
      position: { x: 480, y: 0 },
    }
    original.nodes.splice(2, 0, second)
    original.edges.splice(1, 1, {
      id: 'a-n',
      source: 'api',
      target: 'next',
      condition: null,
      mappings: [],
    })
    original.edges.push({ id: 'n-e', source: 'next', target: 'end', condition: null, mappings: [] })

    const result = wrapMainPath(original, ['api', 'next'], 'group')
    expect(result.kind).toBe('changed')
    if (result.kind !== 'changed') return
    const owner = result.definition.nodes.find(
      (node) => node.capability_id === 'flow.control.group',
    )!
    const region = result.definition.regions!.find((item) => item.owner_node_id === owner.id)!
    expect(result.definition.nodes.map((node) => node.id)).not.toContain('api')
    expect(result.definition.nodes.map((node) => node.id)).not.toContain('next')
    expect(result.definition.edges).toEqual([
      expect.objectContaining({ id: 's-a', source: 'start', target: owner.id }),
      expect.objectContaining({ id: 'n-e', source: owner.id, target: 'end' }),
    ])
    expect(region.nodes.map((node) => node.id)).toEqual(['api', 'next'])
    expect(region.edges).toEqual([
      expect.objectContaining({ id: 'a-n', source: 'api', target: 'next' }),
    ])
    expect(region.entry_node_id).toBe('api')
    expect(region.exit_node_ids).toEqual(['next'])
    expect(analyzeGraph(result.definition)).toEqual([])
    expect(original.nodes.some((node) => node.id === 'next')).toBe(true)

    const reversed = wrapMainPath(original, ['next', 'api'], 'group')
    expect(reversed.kind).toBe('blocked')
    if (reversed.kind === 'blocked')
      expect(reversed.diagnostics).toEqual(
        expect.arrayContaining([expect.objectContaining({ code: 'WRAP_BOUNDARY' })]),
      )

    const mapped = structuredClone(original)
    mapped.edges[1].mappings = graph(fixture('03-mapped-edge.json')).edges[1].mappings
    const blocked = wrapMainPath(mapped, ['api', 'next'], 'group')
    expect(blocked.kind).toBe('blocked')
    if (blocked.kind === 'blocked')
      expect(blocked.diagnostics).toEqual(
        expect.arrayContaining([expect.objectContaining({ code: 'WRAP_MAPPING' })]),
      )

    const referenced = structuredClone(original)
    referenced.nodes.find((node) => node.id === 'end')!.config.source_node_id = 'next'
    const referenceBlocked = wrapMainPath(referenced, ['api', 'next'], 'group')
    expect(referenceBlocked.kind).toBe('blocked')
    if (referenceBlocked.kind === 'blocked')
      expect(referenceBlocked.diagnostics).toEqual(
        expect.arrayContaining([expect.objectContaining({ code: 'WRAP_OUTPUT_REFERENCE' })]),
      )
  })

  it('unwraps a linear multi-step group and preserves node and edge identities', () => {
    const original = graph(linear)
    const second = {
      ...structuredClone(original.nodes[1]),
      id: 'next',
      name: '下一个接口',
      position: { x: 480, y: 0 },
    }
    original.nodes.splice(2, 0, second)
    original.edges.splice(1, 1, {
      id: 'a-n',
      source: 'api',
      target: 'next',
      condition: null,
      mappings: [],
    })
    original.edges.push({ id: 'n-e', source: 'next', target: 'end', condition: null, mappings: [] })
    const wrapped = wrapMainPath(original, ['api', 'next'], 'group')
    expect(wrapped.kind).toBe('changed')
    if (wrapped.kind !== 'changed') return
    const owner = wrapped.definition.nodes.find(
      (node) => node.capability_id === 'flow.control.group',
    )!

    const result = unwrapMainPath(wrapped.definition, owner.id)
    expect(result.kind).toBe('changed')
    if (result.kind !== 'changed') return
    expect(result.definition.nodes.map((node) => node.id).sort()).toEqual(
      original.nodes.map((node) => node.id).sort(),
    )
    expect(result.definition.edges).toEqual(
      expect.arrayContaining(original.edges.map((edge) => expect.objectContaining(edge))),
    )
    expect(result.definition.nodes.find((node) => node.id === 'next')?.position).toEqual(
      second.position,
    )
    expect(result.definition.regions).toEqual([])
    expect(analyzeGraph(result.definition)).toEqual([])

    const mapped = structuredClone(wrapped.definition)
    mapped.regions![0].edges[0].mappings = graph(fixture('03-mapped-edge.json')).edges[1].mappings
    expect(unwrapMainPath(mapped, owner.id)).toEqual(expect.objectContaining({ kind: 'blocked' }))
    const referenced = structuredClone(wrapped.definition)
    referenced.nodes.find((node) => node.id === 'end')!.config.source_node_id = 'api'
    expect(unwrapMainPath(referenced, owner.id)).toEqual(
      expect.objectContaining({ kind: 'blocked' }),
    )
  })

  it('rejects wrapping a mapped or externally referenced node with specific diagnostics', () => {
    const mappedResult = wrapMainNode(graph(mapped), 'api', 'group')
    expect(mappedResult.kind).toBe('blocked')
    if (mappedResult.kind === 'blocked')
      expect(mappedResult.diagnostics).toEqual(
        expect.arrayContaining([expect.objectContaining({ code: 'WRAP_MAPPING' })]),
      )
    const referenced = graph(linear)
    referenced.nodes[2].config.source_node_id = 'api'
    const referencedResult = wrapMainNode(referenced, 'api', 'group')
    expect(referencedResult.kind).toBe('blocked')
    if (referencedResult.kind === 'blocked')
      expect(referencedResult.diagnostics).toEqual(
        expect.arrayContaining([expect.objectContaining({ code: 'WRAP_OUTPUT_REFERENCE' })]),
      )
  })
  it('unwraps a single step only when no region bindings or dependent references remain', () => {
    const result = wrapMainNode(graph(linear), 'api', 'group')
    expect(result.kind).toBe('changed')
    if (result.kind !== 'changed') return
    const owner = result.definition.nodes.find(
      (node) => node.capability_id === 'flow.control.group',
    )!
    const unwrapped = unwrapSingleNode(result.definition, owner.id)
    expect(unwrapped.kind).toBe('changed')
    if (unwrapped.kind !== 'changed') return
    expect(unwrapped.definition.nodes.map((node) => node.id).sort()).toEqual([
      'api',
      'end',
      'start',
    ])
    expect(unwrapped.definition.edges).toEqual(graph(linear).edges)
    expect(unwrapped.definition.regions).toEqual([])

    const bound = structuredClone(result.definition)
    bound.regions![0].inputs = { value: { kind: 'literal', value: 1 } }
    const blocked = unwrapSingleNode(bound, owner.id)
    expect(blocked.kind).toBe('blocked')
    if (blocked.kind === 'blocked')
      expect(blocked.diagnostics).toEqual(
        expect.arrayContaining([expect.objectContaining({ code: 'UNWRAP_INPUTS' })]),
      )
    const configured = structuredClone(result.definition)
    configured.nodes.find((node) => node.id === owner.id)!.configuration!.inputs = {
      value: { kind: 'literal', value: 1 },
    }
    const configBlocked = unwrapSingleNode(configured, owner.id)
    expect(configBlocked.kind).toBe('blocked')
    if (configBlocked.kind === 'blocked')
      expect(configBlocked.diagnostics).toEqual(
        expect.arrayContaining([expect.objectContaining({ code: 'UNWRAP_INPUTS' })]),
      )
  })
  it('inserts a control block into a selected edge as one connected graph change', () => {
    const definition = addControlBlock(
      {
        ...graph(linear),
        run_policy: {
          request_budget: null,
          max_runtime_seconds: null,
          cleanup_request_budget: null,
          force_cancel_skips_cleanup: false,
        },
      },
      'foreach',
    )
    expect(definition.run_policy?.request_budget).toBe(1000)
    const node = definition.nodes.at(-1)!
    const connected = insertNodeOnEdge(definition, node.id, 'a-e')
    expect(connected?.edges).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ id: 'a-e', source: 'api', target: node.id }),
        expect.objectContaining({ source: node.id, target: 'end', condition: null }),
      ]),
    )
    expect(connected?.nodes.find((item) => item.id === node.id)?.position.x).toBe(480)
    const mappedDefinition = addControlBlock(graph(mapped), 'foreach')
    expect(insertNodeOnEdge(mappedDefinition, mappedDefinition.nodes.at(-1)!.id, 'a-b')).toBeNull()
  })
  it('copies and deletes a control block with every owned region atomically', () => {
    const definition = addControlBlock(graph(linear), 'if')
    const source = definition.nodes.at(-1)!
    const copied = pasteNode(definition, source)
    const duplicate = copied.nodes.at(-1)!
    expect(copied.regions).toHaveLength(4)
    expect(
      new Set(copied.regions?.flatMap((region) => region.nodes.map((node) => node.id))).size,
    ).toBe(4)
    expect(duplicate.configuration?.true_body).toEqual({
      kind: 'inline',
      region_id: copied.regions?.find(
        (region) => region.owner_node_id === duplicate.id && region.role === 'true',
      )?.id,
    })
    const removed = applyDeletion(copied, planDeletion(copied, nodeSelection(source.id)))
    expect(removed.kind).toBe('changed')
    if (removed.kind !== 'changed') return
    expect(removed.definition.regions).toHaveLength(2)
    expect(
      removed.definition.regions?.every((region) => region.owner_node_id === duplicate.id),
    ).toBe(true)
  })
  it('regenerates copied Switch branch IDs and their region roles', () => {
    const original = addControlBlock(graph(linear), 'switch')
    const copied = pasteNode(original, original.nodes.at(-1)!)
    const node = copied.nodes.at(-1)!
    const branches = node.configuration?.branches as Array<{
      id: string
      body: { region_id: string }
    }>
    expect(branches.map((branch) => branch.id)).not.toEqual(['first', 'second'])
    for (const branch of branches) {
      expect(copied.regions).toContainEqual(
        expect.objectContaining({
          owner_node_id: node.id,
          role: `case:${branch.id}`,
          id: branch.body.region_id,
        }),
      )
    }
  })

  it('DEL01/04 deletes and retains a recoverable complete mapped edge without mutating input', () => {
    const definition = graph(mapped)
    const original = structuredClone(definition)
    const plan = planDeletion(definition, edgeSelection('a-b'))
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
      const startPlan = planDeletion(definition, nodeSelection('start'))
      const endPlan = planDeletion(definition, nodeSelection('end'))
      expect(startPlan.protectedNodeIds).toEqual(['start'])
      expect(endPlan.protectedNodeIds).toEqual(['end'])
      expect(applyDeletion(definition, startPlan).kind).toBe('unchanged')
      expect(applyDeletion(definition, endPlan).kind).toBe('unchanged')
    }
  })
  it('DEL07 blocks deletion referenced by a retained cleanup node', () => {
    const definition = graph(cleanup)
    const plan = planDeletion(definition, nodeSelection('api'))
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
  const plan = planDeletion(withOpaque, nodeSelection('api'))
  expect(plan.references.map((issue) => issue.code)).toEqual(
    expect.arrayContaining(['BINDING_REVIEW', 'CAPABILITY_REVIEW']),
  )
  expect(applyDeletion(withOpaque, plan).kind).toBe('blocked')
  expect(applyDeletion(withOpaque, planDeletion(withOpaque, null)).kind).toBe('unchanged')
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
  expect(planDeletion(snapshot, edgeSelection(snapshot.edges[0].id)).requiresConfirmation).toBe(
    false,
  )
})
