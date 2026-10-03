import type { ExecutionEvent, WorkflowDefinition, WorkflowNodeExecution } from '../../lib/api'

export function initialNodeExecutions(
  executionId: string,
  definition: WorkflowDefinition,
): Record<string, WorkflowNodeExecution> {
  return Object.fromEntries(
    definition.nodes.map((node) => [
      node.id,
      {
        id: `${executionId}:${node.id}`,
        node_id: node.id,
        node_type: node.type,
        name: node.name,
        status: 'pending',
        attempts: 0,
        output: null,
        result: null,
        error_code: null,
        error_message: null,
        started_at: null,
      },
    ]),
  )
}

export type NodeExecutionEvent = ExecutionEvent & {
  node_id: string
  node_status: WorkflowNodeExecution['status']
}

export function mergeExecutionEvent(
  current: WorkflowNodeExecution | undefined,
  event: NodeExecutionEvent,
): WorkflowNodeExecution {
  const base = current ?? emptyEventNode(event)
  const resultFields = event.result ? { output: event.result.output, result: event.result } : {}
  return {
    ...base,
    ...resultFields,
    status: event.node_status,
    attempts: event.attempts,
    error_code: event.error_code,
    error_message: event.error_message,
    started_at: eventStartedAt(base, event),
    completed_at: eventCompletedAt(base, event),
  }
}

function emptyEventNode(event: NodeExecutionEvent): WorkflowNodeExecution {
  return {
    id: `${event.execution_id}:${event.node_id}`,
    node_id: event.node_id,
    node_type: event.node_type ?? 'unknown',
    name: event.node_name ?? '未命名节点',
    status: 'pending',
    attempts: 0,
    output: null,
    result: null,
    error_code: null,
    error_message: null,
    started_at: null,
  }
}

function eventStartedAt(
  current: WorkflowNodeExecution,
  event: NodeExecutionEvent,
): string | null | undefined {
  if (current.started_at) return current.started_at
  return event.node_status === 'running' ? event.emitted_at : null
}

function eventCompletedAt(
  current: WorkflowNodeExecution,
  event: NodeExecutionEvent,
): string | undefined {
  if (isTerminalNodeStatus(event.node_status)) return event.emitted_at
  return current.completed_at
}

export function snapshotDefinition(snapshot: Record<string, unknown>): WorkflowDefinition | null {
  const workflow = snapshot.workflow
  if (!isRecord(workflow)) return null
  const definition = workflow.definition
  if (
    !isRecord(definition) ||
    !Array.isArray(definition.nodes) ||
    !Array.isArray(definition.edges)
  ) {
    return null
  }
  return definition as WorkflowDefinition
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isTerminalNodeStatus(status: WorkflowNodeExecution['status']): boolean {
  return !['pending', 'running'].includes(status)
}
