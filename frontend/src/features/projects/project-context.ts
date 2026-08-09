import { createContext } from 'react'
import type { UseQueryResult } from '@tanstack/react-query'

import type { Page, Project } from '../../lib/api'
import type { ProjectSection } from './project-routing'

export type ProjectContextValue = {
  projects: UseQueryResult<Page<Project>>
  projectId: string | null
  currentProject: Project | null
  section: ProjectSection
  selectProject: (projectId: string | null) => void
  pathFor: (section: ProjectSection) => string
}

export const ProjectContext = createContext<ProjectContextValue | null>(null)
