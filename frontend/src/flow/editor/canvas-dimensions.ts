import type { NodeChange } from '@xyflow/react'

export type CanvasDimensions = ReadonlyMap<string, { width: number; height: number }>

export function updateCanvasDimensions(
  current: CanvasDimensions,
  changes: NodeChange[],
  nodeIds: ReadonlySet<string>,
): CanvasDimensions {
  const next = new Map([...current].filter(([id]) => nodeIds.has(id)))
  for (const change of changes) {
    if (change.type !== 'dimensions' || !change.dimensions || !nodeIds.has(change.id)) continue
    next.set(change.id, change.dimensions)
  }
  const equal =
    next.size === current.size &&
    [...next].every(([id, size]) => {
      const previous = current.get(id)
      return previous?.width === size.width && previous.height === size.height
    })
  return equal ? current : next
}
