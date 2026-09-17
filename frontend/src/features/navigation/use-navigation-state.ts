import { useState, useSyncExternalStore } from 'react'
import { useLocation } from 'react-router-dom'

import type { ProjectSection } from '../projects/project-routing'
import { groupForSection, type NavigationGroupKey } from './navigation-config'
import {
  legalGroupKeys,
  readNavigationPreference,
  writeNavigationPreference,
} from './navigation-preferences'

const mobileQuery = '(max-width: 991px)'
const compactQuery = '(max-width: 1279px)'

function viewportMode(): 'mobile' | 'compact' | 'wide' {
  if (window.matchMedia(mobileQuery).matches) return 'mobile'
  return window.matchMedia(compactQuery).matches ? 'compact' : 'wide'
}

function subscribeViewport(callback: () => void): () => void {
  const media = [window.matchMedia(mobileQuery), window.matchMedia(compactQuery)]
  media.forEach((item) => item.addEventListener('change', callback))
  return () => media.forEach((item) => item.removeEventListener('change', callback))
}

function currentGroup(section: ProjectSection): NavigationGroupKey[] {
  const group = groupForSection(section)
  return group ? [group.key] : []
}

export function useNavigationState(
  userId: string,
  section: ProjectSection,
  isSystemAdmin: boolean,
) {
  const location = useLocation()
  const viewport = useSyncExternalStore(subscribeViewport, viewportMode)
  const route = `${location.pathname}:${isSystemAdmin}`
  const [state, setState] = useState(() => {
    const preference = readNavigationPreference(userId)
    const routeKeys = currentGroup(section)
    return {
      route,
      viewport,
      collapsedPreference: preference.collapsed,
      openKeys: routeKeys.length ? routeKeys : preference.openKeys,
      popupKeys: [] as NavigationGroupKey[],
      drawerOpen: false,
    }
  })
  const collapsed = viewport !== 'mobile' && (state.collapsedPreference ?? viewport === 'compact')
  if (state.route !== route || state.viewport !== viewport) {
    // Synchronize only on navigation or breakpoint changes, never on ordinary renders.
    setState({
      ...state,
      route,
      viewport,
      openKeys: currentGroup(section),
      popupKeys: [],
      drawerOpen: false,
    })
  }

  function changeOpenKeys(keys: string[]): void {
    const previous = collapsed ? state.popupKeys : state.openKeys
    const added = legalGroupKeys(keys).find((key) => !previous.includes(key))
    const next = added ? [added] : legalGroupKeys(keys).slice(-1)
    setState({ ...state, [collapsed ? 'popupKeys' : 'openKeys']: next })
    if (!collapsed)
      writeNavigationPreference(userId, { collapsed: state.collapsedPreference, openKeys: next })
  }

  function toggleCollapsed(): void {
    const next = !collapsed
    const routeKeys = currentGroup(section)
    const openKeys = routeKeys.length ? routeKeys : state.openKeys
    setState({ ...state, collapsedPreference: next, openKeys, popupKeys: [] })
    writeNavigationPreference(userId, { collapsed: next, openKeys })
  }

  function setDrawerOpen(drawerOpen: boolean): void {
    setState({ ...state, drawerOpen })
  }

  return {
    mobile: viewport === 'mobile',
    collapsed,
    openKeys: collapsed ? state.popupKeys : state.openKeys,
    drawerOpen: state.drawerOpen,
    changeOpenKeys,
    toggleCollapsed,
    setDrawerOpen,
  }
}
