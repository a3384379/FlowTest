import { projectPath } from '../projects/project-routing'

export type ExecutionLocation = {
  executionId: string
  workflowId?: string | null
  nodeId?: string | null
  attempt?: number
} & ExecutionEvidenceLocation

export type ExecutionEvidenceLocation = {
  controlKind?: 'iteration' | 'branch'
  controlOrdinal?: number
  instanceId?: string
  instanceAttempt?: number
}

export function workflowExecutionPath(projectId: string, location: ExecutionLocation): string {
  const params = new URLSearchParams()
  if (location.workflowId) params.set('focus', location.workflowId)
  params.set('execution', location.executionId)
  if (location.nodeId) params.set('node', location.nodeId)
  if (location.nodeId && location.attempt) params.set('attempt', String(location.attempt))
  if (location.nodeId) writeExecutionEvidence(params, location)
  return `${projectPath(projectId, 'workflows')}?${params}`
}

export function reportExecutionPath(projectId: string, location: ExecutionLocation): string {
  const params = new URLSearchParams({ execution: location.executionId })
  if (location.nodeId) params.set('node', location.nodeId)
  if (location.nodeId && location.attempt) params.set('attempt', String(location.attempt))
  if (location.nodeId) writeExecutionEvidence(params, location)
  return `${projectPath(projectId, 'reports')}?${params}`
}

export function executionAttempt(params: URLSearchParams): number | undefined {
  const raw = params.get('attempt')
  if (!raw || !/^[1-9]\d*$/.test(raw)) return undefined
  const value = Number(raw)
  return Number.isSafeInteger(value) ? value : undefined
}

export function executionEvidence(params: URLSearchParams): ExecutionEvidenceLocation {
  const kind = params.get('control_kind')
  const rawOrdinal = params.get('control_ordinal')
  const ordinal =
    rawOrdinal !== null && /^(0|[1-9]\d*)$/.test(rawOrdinal) ? Number(rawOrdinal) : undefined
  const instanceId = params.get('instance') || undefined
  return {
    controlKind: kind === 'iteration' || kind === 'branch' ? kind : undefined,
    controlOrdinal: Number.isSafeInteger(ordinal) ? ordinal : undefined,
    instanceId: instanceId?.startsWith('__nested_request__:') ? instanceId : undefined,
    instanceAttempt: executionAttempt(
      new URLSearchParams({
        attempt: params.get('instance_attempt') ?? '',
      }),
    ),
  }
}

export function writeExecutionEvidence(
  params: URLSearchParams,
  location: ExecutionEvidenceLocation,
): void {
  clearExecutionEvidence(params)
  if (location.controlKind) params.set('control_kind', location.controlKind)
  if (location.controlOrdinal !== undefined)
    params.set('control_ordinal', String(location.controlOrdinal))
  if (location.instanceId) params.set('instance', location.instanceId)
  if (location.instanceId && location.instanceAttempt)
    params.set('instance_attempt', String(location.instanceAttempt))
}

export function clearExecutionEvidence(params: URLSearchParams): void {
  for (const key of ['control_kind', 'control_ordinal', 'instance', 'instance_attempt'])
    params.delete(key)
}
