import { useSyncExternalStore } from 'react'

export function reducedMotionEnabled(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function subscribeMotion(listener: () => void): () => void {
  const media = window.matchMedia('(prefers-reduced-motion: reduce)')
  media.addEventListener('change', listener)
  return () => media.removeEventListener('change', listener)
}

export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribeMotion, reducedMotionEnabled)
}
