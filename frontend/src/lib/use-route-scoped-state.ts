import { useState } from 'react'

type RouteScopedValue<T> = {
  projectId: string | null
  routeKey: string | null
  value: T
}

export function useRouteScopedState<T>(
  projectId: string | null,
  routeKey: string | null,
  initialValue: T,
): readonly [T, (value: T) => void] {
  const [state, setState] = useState<RouteScopedValue<T>>({
    projectId,
    routeKey,
    value: initialValue,
  })
  const isCurrentScope = state.projectId === projectId && state.routeKey === routeKey
  if (!isCurrentScope) {
    setState({ projectId, routeKey, value: initialValue })
  }
  const value = isCurrentScope ? state.value : initialValue
  return [value, (nextValue: T) => setState({ projectId, routeKey, value: nextValue })] as const
}

export function useRouteScopedSelection(
  projectId: string | null,
  routeSelectionId: string | null,
): readonly [string | null, (value: string | null) => void] {
  return useRouteScopedState(projectId, routeSelectionId, routeSelectionId)
}
