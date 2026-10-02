import { describe, expect, it, vi } from 'vitest'

import { keepSelectionVisible } from './WorkflowDesigner'
import { workflowDefinition } from '../test/fixtures'

type SelectionViewport = Parameters<typeof keepSelectionVisible>[0]

function viewport() {
  return {
    getNode: vi.fn<SelectionViewport['getNode']>(() => undefined),
    getViewport: vi.fn(() => ({ x: 0, y: 0, zoom: 1 })),
    setCenter: vi.fn<SelectionViewport['setCenter']>(async () => true),
  }
}

describe('workflow selection viewport', () => {
  it('centers an offscreen node with its initial dimensions before measurement', () => {
    const instance = viewport()
    const node = workflowDefinition.nodes[1]
    keepSelectionVisible(
      instance,
      workflowDefinition,
      { kind: 'node', id: node.id },
      { width: 50, height: 50 },
      { width: 0, height: 0 },
    )
    expect(instance.setCenter).toHaveBeenCalledWith(node.position.x + 116, node.position.y + 55, {
      duration: 0,
      zoom: 1,
    })
  })

  it('leaves the viewport unchanged when the node and toolbar already fit', () => {
    const instance = viewport()
    instance.getViewport.mockReturnValue({ x: 200, y: 200, zoom: 1 })
    keepSelectionVisible(
      instance,
      workflowDefinition,
      { kind: 'node', id: workflowDefinition.nodes[1].id },
      { width: 1000, height: 800 },
      { width: 240, height: 36 },
    )
    expect(instance.setCenter).not.toHaveBeenCalled()
  })

  it('ignores a missing selection or an edge with missing endpoints', () => {
    const instance = viewport()
    for (const selection of [null, { kind: 'edge' as const, id: 'missing' }]) {
      keepSelectionVisible(
        instance,
        workflowDefinition,
        selection,
        { width: 50, height: 50 },
        { width: 0, height: 0 },
      )
    }
    expect(instance.setCenter).not.toHaveBeenCalled()
  })

  it('centers an offscreen edge between its endpoint centers', () => {
    const instance = viewport()
    const edge = workflowDefinition.edges[0]
    const source = workflowDefinition.nodes.find((node) => node.id === edge.source)!
    const target = workflowDefinition.nodes.find((node) => node.id === edge.target)!
    keepSelectionVisible(
      instance,
      workflowDefinition,
      { kind: 'edge', id: edge.id },
      { width: 50, height: 50 },
      { width: 0, height: 0 },
    )
    expect(instance.setCenter).toHaveBeenCalledWith(
      (source.position.x + target.position.x) / 2 + 116,
      (source.position.y + target.position.y) / 2 + 55,
      { duration: 0, zoom: 1 },
    )
  })

  it('keeps a measured runtime node centered after fitting a short canvas', () => {
    const instance = viewport()
    instance.getNode.mockReturnValue({ measured: { width: 232, height: 125 } })
    instance.getViewport.mockReturnValue({ x: 194, y: 62.5, zoom: 1 })
    keepSelectionVisible(
      instance,
      workflowDefinition,
      { kind: 'node', id: 'api' },
      { width: 820, height: 250 },
      { width: 400, height: 44 },
    )
    expect(instance.setCenter).not.toHaveBeenCalled()
  })

  it('includes the measured node height when checking toolbar clearance', () => {
    const instance = viewport()
    instance.getNode.mockReturnValue({ measured: { width: 300, height: 200 } })
    instance.getViewport.mockReturnValue({ x: 0, y: 420, zoom: 1 })
    keepSelectionVisible(
      instance,
      workflowDefinition,
      { kind: 'node', id: 'api' },
      { width: 800, height: 600 },
      { width: 200, height: 40 },
    )
    expect(instance.setCenter).toHaveBeenCalledWith(250, 100, { duration: 0, zoom: 1 })
  })

  it('centers edges using each endpoint size without changing stored positions', () => {
    const instance = viewport()
    instance.getNode.mockImplementation((id) =>
      id === 'start' ? { measured: { width: 200, height: 80 } } : { width: 300, height: 200 },
    )
    const before = structuredClone(workflowDefinition)
    keepSelectionVisible(
      instance,
      workflowDefinition,
      { kind: 'edge', id: 'start-api' },
      { width: 50, height: 50 },
      { width: 0, height: 0 },
    )
    expect(instance.setCenter).toHaveBeenCalledWith(175, 70, { duration: 0, zoom: 1 })
    expect(workflowDefinition).toEqual(before)
  })
})
