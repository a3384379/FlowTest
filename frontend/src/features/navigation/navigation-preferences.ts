import { navigationGroups, type NavigationGroupKey } from './navigation-config'

export interface NavigationPreference {
  collapsed: boolean | null
  openKeys: NavigationGroupKey[]
}

export function readNavigationPreference(userId: string): NavigationPreference {
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(storageKey(userId)) ?? '{}')
    if (!value || typeof value !== 'object' || Array.isArray(value)) return defaults()
    const stored = value as { collapsed?: unknown; openKeys?: unknown }
    return {
      collapsed: typeof stored.collapsed === 'boolean' ? stored.collapsed : null,
      openKeys: legalGroupKeys(stored.openKeys).slice(-1),
    }
  } catch {
    return defaults()
  }
}

export function writeNavigationPreference(userId: string, preference: NavigationPreference): void {
  try {
    window.localStorage.setItem(storageKey(userId), JSON.stringify(preference))
  } catch {
    // Browser storage is optional; navigation works for the current session.
  }
}

export function legalGroupKeys(value: unknown): NavigationGroupKey[] {
  if (!Array.isArray(value)) return []
  return value.filter((key): key is NavigationGroupKey =>
    navigationGroups.some((group) => group.key === key),
  )
}

function defaults(): NavigationPreference {
  return { collapsed: null, openKeys: [] }
}

function storageKey(userId: string): string {
  return `flowtest:navigation:v1:${userId}`
}
