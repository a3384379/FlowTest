import { createContext, useContext } from 'react'

export type InspectorPresentation = 'quick' | 'fullscreen'

export const InspectorPresentationContext = createContext<InspectorPresentation>('quick')

export function useInspectorPresentation(): InspectorPresentation {
  return useContext(InspectorPresentationContext)
}
