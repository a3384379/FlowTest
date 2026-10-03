import { act, renderHook } from '@testing-library/react'
import { expect, it } from 'vitest'

import { useRouteScopedState } from './use-route-scoped-state'

it('keeps callbacks stable within a scope and ignores a late update from another project or route', () => {
  const { result, rerender } = renderHook(
    ({ project, route }) => useRouteScopedState(project, route, 'initial'),
    { initialProps: { project: 'first', route: 'object-a' } },
  )
  const oldUpdate = result.current[1]
  act(() => oldUpdate('first edit'))
  expect(result.current[0]).toBe('first edit')
  expect(result.current[1]).toBe(oldUpdate)
  rerender({ project: 'second', route: 'object-b' })
  act(() => result.current[1]('second edit'))
  act(() => oldUpdate('late first response'))
  expect(result.current[0]).toBe('second edit')
  const secondUpdate = result.current[1]
  rerender({ project: 'second', route: 'object-c' })
  act(() => result.current[1]('third edit'))
  act(() => secondUpdate('late second response'))
  expect(result.current[0]).toBe('third edit')
})
