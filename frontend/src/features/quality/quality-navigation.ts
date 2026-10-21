import { projectPath } from '../projects/project-routing'

export function qualityRunPath(projectId: string, runId: string, planId?: string): string {
  const params = new URLSearchParams({ run: runId })
  if (planId) params.set('focus', planId)
  return `${projectPath(projectId, 'tasks')}?${params}`
}
