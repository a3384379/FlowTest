import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, type ReactNode } from 'react'
import { matchPath, useLocation, useNavigate } from 'react-router-dom'

import { ProjectContext, type ProjectContextValue } from './project-context'
import { globalPath, projectPath, sectionFromPath } from './project-routing'
import { listManagedProjects } from './project-service'

export default function ProjectProvider({ children }: { children: ReactNode }) {
  const location = useLocation()
  const navigate = useNavigate()
  const projects = useQuery({ queryKey: ['projects'], queryFn: listManagedProjects })
  const route = matchPath('/projects/:projectId/*', location.pathname)
  const projectId = route?.params.projectId ?? null
  const section = sectionFromPath(location.pathname)
  const currentProject = projects.data?.items.find((project) => project.id === projectId) ?? null

  useEffect(() => {
    if (projects.isSuccess && projectId && !currentProject)
      navigate('/dashboard', { replace: true })
  }, [currentProject, navigate, projectId, projects.isSuccess])

  const value = useMemo<ProjectContextValue>(
    () => ({
      projects,
      projectId,
      currentProject,
      section,
      selectProject: (nextProjectId) => {
        navigate(nextProjectId ? projectPath(nextProjectId, section) : '/dashboard')
      },
      pathFor: (nextSection) =>
        projectId ? projectPath(projectId, nextSection) : globalPath(nextSection),
    }),
    [currentProject, navigate, projectId, projects, section],
  )
  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>
}
