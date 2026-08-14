import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'

import ProjectProvider from '../features/projects/ProjectProvider'
import { projectPath, type ProjectSection } from '../features/projects/project-routing'
import { project } from './fixtures'

export default function ProjectTestProvider({
  section,
  children,
  initialEntry,
}: {
  section: ProjectSection
  children: ReactNode
  initialEntry?: string
}) {
  return (
    <MemoryRouter initialEntries={[initialEntry ?? projectPath(project.id, section)]}>
      <ProjectProvider>{children}</ProjectProvider>
    </MemoryRouter>
  )
}
