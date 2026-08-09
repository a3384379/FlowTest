import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'

import ProjectProvider from '../features/projects/ProjectProvider'
import { projectPath, type ProjectSection } from '../features/projects/project-routing'
import { project } from './fixtures'

export default function ProjectTestProvider({
  section,
  children,
}: {
  section: ProjectSection
  children: ReactNode
}) {
  return (
    <MemoryRouter initialEntries={[projectPath(project.id, section)]}>
      <ProjectProvider>{children}</ProjectProvider>
    </MemoryRouter>
  )
}
