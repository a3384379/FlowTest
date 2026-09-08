import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { useRouteScopedSelection, useRouteScopedState } from './use-route-scoped-state'

describe('route-scoped state', () => {
  it('follows route and project changes without discarding an in-route manual selection', () => {
    const rendered = renderHook(
      ({ projectId, routeId }) => useRouteScopedSelection(projectId, routeId),
      { initialProps: { projectId: 'project-1', routeId: 'route-a' as string | null } },
    )

    expect(rendered.result.current[0]).toBe('route-a')
    act(() => rendered.result.current[1]('manual-selection'))
    expect(rendered.result.current[0]).toBe('manual-selection')

    rendered.rerender({ projectId: 'project-1', routeId: 'route-b' })
    expect(rendered.result.current[0]).toBe('route-b')

    rendered.rerender({ projectId: 'project-2', routeId: null })
    expect(rendered.result.current[0]).toBeNull()
  })

  it('drops local route state as soon as its project scope changes', () => {
    const rendered = renderHook(
      ({ projectId }) => useRouteScopedState<string | null>(projectId, 'proposal-a', null),
      { initialProps: { projectId: 'project-1' } },
    )

    act(() => rendered.result.current[1]('local-proposal'))
    expect(rendered.result.current[0]).toBe('local-proposal')

    rendered.rerender({ projectId: 'project-2' })
    expect(rendered.result.current[0]).toBeNull()
  })
})
