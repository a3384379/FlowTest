import { projectPath } from '../projects/project-routing'

export type ExecutionLocation = {
  executionId: string
  workflowId?: string | null
  nodeId?: string | null
  attempt?: number
}

export function workflowExecutionPath(projectId: string, location: ExecutionLocation): string {
  const params = new URLSearchParams()
  if (location.workflowId) params.set('focus', location.workflowId)
  params.set('execution', location.executionId)
  if (location.nodeId) params.set('node', location.nodeId)
  if (location.nodeId && location.attempt) params.set('attempt', String(location.attempt))
  return `${projectPath(projectId, 'workflows')}?${params}`
}

export function reportExecutionPath(projectId: string, location: ExecutionLocation): string {
  const params = new URLSearchParams({ execution: location.executionId })
  if (location.nodeId) params.set('node', location.nodeId)
  if (location.nodeId && location.attempt) params.set('attempt', String(location.attempt))
  return `${projectPath(projectId, 'reports')}?${params}`
}

export function executionAttempt(params: URLSearchParams): number | undefined {
  const raw = params.get('attempt')
  if (!raw || !/^[1-9]\d*$/.test(raw)) return undefined
  const value = Number(raw)
  return Number.isSafeInteger(value) ? value : undefined
}
