import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'

import type { Environment } from '../../lib/api'
import { useAuthStore } from '../auth/auth-store'

const selectionEvent = 'flowtest:environment-selection'

function subscribe(listener: () => void): () => void {
  window.addEventListener('storage', listener)
  window.addEventListener(selectionEvent, listener)
  return () => {
    window.removeEventListener('storage', listener)
    window.removeEventListener(selectionEvent, listener)
  }
}

function readSelection(key: string | null): string | null {
  if (!key) return null
  try {
    return localStorage.getItem(key)
  } catch {
    return '!storage-unavailable' // Unavailable storage must never choose a target.
  }
}

export function useEnvironmentSelection(projectId: string | null, items?: Environment[]) {
  const userId = useAuthStore((state) => state.user?.id)
  const key =
    userId && projectId
      ? `flowtest:environment:v1:${encodeURIComponent(userId)}:${encodeURIComponent(projectId)}`
      : null
  const [storageError, setStorageError] = useState<string | null>(null)
  const snapshot = useCallback(() => readSelection(key), [key])
  const selection = useSyncExternalStore(subscribe, snapshot, () => null)
  const selectEnvironment = useCallback(
    (id: string | null) => {
      if (!key) throw new Error('请先登录并选择项目')
      try {
        localStorage.setItem(key, id ?? '')
      } catch {
        setStorageError('无法保存环境选择，请检查浏览器存储后重试')
        return
      }
      setStorageError(null)
      window.dispatchEvent(new Event(selectionEvent))
    },
    [key],
  )
  const uniqueId = initialEnvironment(key, selection, items)
  useEffect(() => {
    let active = true
    queueMicrotask(() => {
      if (active && uniqueId) selectEnvironment(uniqueId)
    })
    return () => {
      active = false
    }
  }, [uniqueId, selectEnvironment])
  const candidate = storageError ? null : (selection ?? uniqueId)
  const environmentId = items?.some((item) => item.id === candidate) ? candidate : null
  const selectionInvalid = invalidSelection(selection, items, environmentId)
  return {
    environmentId,
    selectEnvironment,
    selectionInvalid,
    ...selectionPresentation(selectionInvalid, storageError),
  }
}

function invalidSelection(
  selection: string | null,
  items: Environment[] | undefined,
  environmentId: string | null,
): boolean {
  return Boolean(selection && items && !environmentId)
}

function selectionPresentation(invalid: boolean, storageError: string | null) {
  return {
    environmentPlaceholder: storageError ?? (invalid ? '原环境已失效，请重新选择' : '选择环境'),
    environmentStatus: invalid || storageError ? ('error' as const) : undefined,
  }
}

function initialEnvironment(
  key: string | null,
  selection: string | null,
  items?: Environment[],
): string | null {
  return key && selection === null && items?.length === 1 ? items[0].id : null
}
