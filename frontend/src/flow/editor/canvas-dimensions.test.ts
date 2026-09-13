import { expect, it } from 'vitest'
import { updateCanvasDimensions } from './canvas-dimensions'

it('retains canvas-only measurements across selection and prunes removed nodes', () => {
  const ids = new Set(['api'])
  const measured = updateCanvasDimensions(
    new Map(),
    [{ type: 'dimensions', id: 'api', dimensions: { width: 200, height: 80 } }],
    ids,
  )
  expect(measured.get('api')).toEqual({ width: 200, height: 80 })
  expect(
    updateCanvasDimensions(measured, [{ type: 'select', id: 'api', selected: true }], ids),
  ).toBe(measured)
  expect(
    updateCanvasDimensions(
      measured,
      [{ type: 'dimensions', id: 'api', dimensions: { width: 200, height: 80 } }],
      ids,
    ),
  ).toBe(measured)
  expect(updateCanvasDimensions(measured, [], new Set()).size).toBe(0)
})
