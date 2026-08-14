import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, type ReactNode } from 'react'
import { matchPath, useLocation, useNavigate } from 'react-router-dom'

import { ProjectContext, type ProjectContextValue } from './project-context'
import { globalPath, projectPath, sectionFromPath } from './project-routing'
import { getManagedProject, listManagedProjects } from './project-service'

export default function ProjectProvider({ children }: { children: ReactNode }) {
  const location = useLocation()
  const navigate = useNavigate()
  const projects = useQuery({ queryKey: ['projects'], queryFn: listManagedProjects })
  const route = matchPath('/projects/:projectId/*', location.pathname)
  const projectId = route?.params.projectId ?? null
  const section = sectionFromPath(location.pathname)
  const listedProject = projects.data?.items.find((project) => project.id === projectId) ?? null
  const routeProject = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => getManagedProject(requiredProjectId(projectId)),
    enabled: projects.isSuccess && Boolean(projectId) && !listedProject,
    retry: false,
  })
  const currentProject = listedProject ?? routeProject.data ?? null
  const availableProjects = useMemo(
    () => includeCurrentProject(projects, currentProject),
    [currentProject, projects],
  )

  useEffect(() => {
    if (projects.isSuccess && projectId && !listedProject && routeProject.isError)
      navigate('/dashboard', { replace: true })
  }, [listedProject, navigate, projectId, projects.isSuccess, routeProject.isError])

  const value = useMemo<ProjectContextValue>(
    () => ({
      projects: availableProjects,
      projectId,
      currentProject,
      section,
      selectProject: (nextProjectId) => {
        navigate(nextProjectId ? projectPath(nextProjectId, section) : '/dashboard')
      },
      pathFor: (nextSection) =>
        projectId ? projectPath(projectId, nextSection) : globalPath(nextSection),
    }),
    [availableProjects, currentProject, navigate, projectId, section],
  )
  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>
}

function includeCurrentProject(
  projects: ProjectContextValue['projects'],
  currentProject: ProjectContextValue['currentProject'],
): ProjectContextValue['projects'] {
  if (!currentProject || !projects.data) return projects
  if (projects.data.items.some((project) => project.id === currentProject.id)) return projects
  return {
    ...projects,
    data: {
      ...projects.data,
      items: [currentProject, ...projects.data.items],
    },
  }
}

function requiredProjectId(projectId: string | null): string {
  if (!projectId) throw new Error('请选择项目')
  return projectId
}
