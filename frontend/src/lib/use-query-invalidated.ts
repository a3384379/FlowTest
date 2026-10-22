import { useQueryClient, type QueryKey } from '@tanstack/react-query'
import { useCallback, useSyncExternalStore } from 'react'

export function useQueryInvalidated(queryKey: QueryKey): boolean {
  const client = useQueryClient()
  const cache = client.getQueryCache()
  const { queryHash } = client.defaultQueryOptions({ queryKey })
  const getSnapshot = useCallback(
    () => cache.get(queryHash)?.state.isInvalidated ?? false,
    [cache, queryHash],
  )
  const subscribe = useCallback(
    (listener: () => void) => {
      let previous = getSnapshot()
      return cache.subscribe((event) => {
        if (event.query.queryHash !== queryHash) return
        const next = getSnapshot()
        if (previous === next) return
        previous = next
        listener()
      })
    },
    [cache, getSnapshot, queryHash],
  )
  return useSyncExternalStore(subscribe, getSnapshot)
}
