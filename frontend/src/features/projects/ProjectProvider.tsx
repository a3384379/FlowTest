import { useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'
import { useEffect, useMemo, type ReactNode } from 'react'
import { matchPath, useLocation, useNavigate } from 'react-router-dom'

import { ProjectContext, type ProjectContextValue } from './project-context'
import type { Project } from '../../lib/api'
import { useQueryInvalidated } from '../../lib/use-query-invalidated'
import {
  globalPath,
  isGlobalAdministrationSection,
  projectPath,
  projectSelectionPath,
  sectionFromPath,
} from './project-routing'
import { getManagedProject, listManagedProjects } from './project-service'

export default function ProjectProvider({ children }: { children: ReactNode }) {
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const projects = useQuery({ queryKey: ['projects'], queryFn: listManagedProjects })
  const route = matchPath('/projects/:projectId/*', location.pathname)
  const projectId = route?.params.projectId ?? null
  const section = sectionFromPath(location.pathname)
  const listedProject = projects.data?.items.find((project) => project.id === projectId) ?? null
  const routeProject = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => getManagedProject(requiredProjectId(projectId)),
    enabled: Boolean(projectId),
    retry: false,
  })
  const listInvalidated = useQueryInvalidated(['projects'])
  const detailInvalidated = useQueryInvalidated(['project', projectId])
  const currentProject = resolveCurrentProject(
    listedProject,
    projects.isSuccess && !listInvalidated,
    routeProject,
    detailInvalidated,
  )
  const availableProjects = useMemo(
    () => includeCurrentProject(projects, currentProject),
    [currentProject, projects],
  )

  useEffect(() => {
    if (projects.isSuccess && projectId && !listedProject && routeProject.isError)
      navigate('/dashboard', { replace: true })
  }, [listedProject, navigate, projectId, projects.isSuccess, routeProject.isError])

  useEffect(() => {
    if (projectId && queryClient.getQueryState(['projects'])?.isInvalidated)
      void queryClient.refetchQueries(
        { queryKey: ['projects'], exact: true, type: 'active' },
        { cancelRefetch: false },
      )
  }, [projectId, queryClient])

  const value = useMemo<ProjectContextValue>(
    () => ({
      projects: availableProjects,
      projectId,
      currentProject,
      section,
      selectProject: (nextProjectId) => {
        navigate(projectSelectionPath(nextProjectId, section))
      },
      pathFor: (nextSection) =>
        projectId && !isGlobalAdministrationSection(nextSection)
          ? projectPath(projectId, nextSection)
          : globalPath(nextSection),
    }),
    [availableProjects, currentProject, navigate, projectId, section],
  )
  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>
}

function resolveCurrentProject(
  listed: Project | null,
  listTrusted: boolean,
  detail: UseQueryResult<Project>,
  detailInvalidated: boolean,
): Project | null {
  if (listTrusted && listed) return listed
  if (detail.isSuccess && !detailInvalidated) return detail.data
  const previous = listed ?? detail.data
  return previous ? { ...previous, role: null } : null
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
