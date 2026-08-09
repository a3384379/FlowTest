import { useContext } from 'react'

import { ProjectContext, type ProjectContextValue } from './project-context'

export function useProjectContext(): ProjectContextValue {
  const context = useContext(ProjectContext)
  if (!context) throw new Error('useProjectContext 必须在 ProjectProvider 内使用')
  return context
}
