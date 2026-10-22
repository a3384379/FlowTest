import { useQueryClient, type QueryKey } from '@tanstack/react-query'
import { useCallback, useSyncExternalStore } from 'react'

export function useQueryInvalidated(queryKey: QueryKey): boolean {
  const client = useQueryClient()
  const subscribe = useCallback(
    (listener: () => void) => client.getQueryCache().subscribe(listener),
    [client],
  )
  return useSyncExternalStore(
    subscribe,
    () => client.getQueryState(queryKey)?.isInvalidated ?? false,
  )
}
