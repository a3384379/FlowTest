import { useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import {
  apiErrorMessage,
  type ExecutionEvent,
  type WorkflowDefinition,
  type WorkflowExecution,
  type WorkflowExecutionDetail,
  type WorkflowNodeExecution,
} from '../../lib/api'
import { getWorkflowExecution } from './workflow-service'
import { useExecutionEvents } from './use-execution-events'
import {
  initialNodeExecutions,
  mergeExecutionEvent,
  snapshotDefinition,
  type NodeExecutionEvent,
} from './workflow-runtime'

class ExecutionScope {
  private generation = 0
  private mounted = true
  constructor(
    readonly userId: string | undefined,
    readonly projectId: string | null,
    readonly workflowId: string | null,
  ) {}
  mount(): void {
    this.mounted = true
  }
  unmount(): void {
    this.mounted = false
    this.invalidate()
  }
  invalidate(): void {
    this.generation += 1
  }
  capture(): ExecutionTicket {
    return { scope: this, generation: this.generation }
  }
  isCurrent(generation: number): boolean {
    return this.mounted && generation === this.generation
  }
}
export type ExecutionTicket = { scope: ExecutionScope; generation: number }
type ExecutionSubscription = ExecutionTicket & {
  executionId: string
  completing: boolean
  completed: boolean
  lastError: string | null
}
type ExecutionState = {
  subscription: ExecutionSubscription | null
  execution: WorkflowExecution | null
  definition: WorkflowDefinition | null
  nodes: Record<string, WorkflowNodeExecution>
  result: WorkflowExecutionDetail | null
  historyIncompleteId: string | null
}

function emptyState(): ExecutionState {
  return {
    subscription: null,
    execution: null,
    definition: null,
    nodes: {},
    result: null,
    historyIncompleteId: null,
  }
}
function isCurrent(ticket: ExecutionTicket): boolean {
  return ticket.scope.isCurrent(ticket.generation)
}
function isActive(tracking: ExecutionSubscription | null): tracking is ExecutionSubscription {
  return tracking !== null && !tracking.completed && isCurrent(tracking)
}
function belongsToScope(execution: WorkflowExecution, scope: ExecutionScope): boolean {
  return execution.project_id === scope.projectId && execution.workflow_id === scope.workflowId
}

export function useWorkflowExecution(
  userId: string | undefined,
  projectId: string | null,
  workflowId: string | null,
  token: string | null,
) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const scope = useMemo<ExecutionScope>(
    () => new ExecutionScope(userId, projectId, workflowId),
    [userId, projectId, workflowId],
  )
  const [state, setState] = useState<ExecutionState>(emptyState)
  useEffect(() => {
    scope.mount()
    return () => {
      scope.unmount()
    }
  }, [scope])
  const view = state.subscription?.scope === scope ? state : emptyState()
  const subscription = view.subscription
  const activeExecutionId = isActive(subscription) ? subscription.executionId : null

  function reserve(): ExecutionTicket {
    scope.invalidate()
    setState(emptyState())
    return scope.capture()
  }
  function reset() {
    scope.invalidate()
    setState(emptyState())
  }

  function begin(execution: WorkflowExecution, ticket?: ExecutionTicket): boolean {
    if (!belongsToScope(execution, scope) || !isCurrent(scope.capture())) return false
    const owner = ticket ?? reserve()
    if (owner.scope !== scope || !isCurrent(owner)) return false
    const tracking: ExecutionSubscription = {
      ...owner,
      executionId: execution.id,
      completing: false,
      completed: false,
      lastError: null,
    }
    const definition = snapshotDefinition(execution.snapshot)
    setState({
      subscription: tracking,
      execution,
      definition,
      nodes: definition ? initialNodeExecutions(execution.id, definition) : {},
      result: null,
      historyIncompleteId: null,
    })
    void watch(tracking)
    return true
  }

  async function finish(
    tracking: ExecutionSubscription,
    result: WorkflowExecutionDetail,
  ): Promise<boolean> {
    if (!isActive(tracking)) return true
    if (
      result.execution.id !== tracking.executionId ||
      !belongsToScope(result.execution, tracking.scope)
    )
      return false
    if (['queued', 'running'].includes(result.execution.status)) return false
    tracking.completed = true
    setState((current) =>
      isCurrent(tracking) && current.subscription === tracking
        ? {
            ...current,
            result,
            execution: result.execution,
            nodes: Object.fromEntries(result.nodes.map((node) => [node.node_id, node])),
          }
        : current,
    )
    await queryClient.invalidateQueries({
      queryKey: ['workflow-executions', tracking.scope.projectId],
    })
    if (isCurrent(tracking))
      void message.success(
        result.execution.status === 'passed' ? '工作流执行通过' : '工作流执行完成',
      )
    return true
  }

  async function complete(tracking: ExecutionSubscription): Promise<boolean> {
    if (!isActive(tracking)) return true
    if (tracking.completing || !tracking.scope.projectId) return false
    tracking.completing = true
    try {
      const result = await getWorkflowExecution(
        tracking.scope.projectId,
        tracking.executionId,
        true,
      )
      return await finish(tracking, result)
    } catch (error) {
      tracking.lastError = apiErrorMessage(error)
      return !isCurrent(tracking)
    } finally {
      tracking.completing = false
    }
  }
  async function watch(tracking: ExecutionSubscription) {
    for (let attempt = 0; attempt < 600; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 500))
      if (await complete(tracking)) return
    }
    if (isCurrent(tracking)) void message.error(tracking.lastError ?? '等待工作流执行结果超时')
  }

  function onEvent(event: ExecutionEvent) {
    if (!isActive(subscription) || event.execution_id !== subscription.executionId) return
    if (
      (event.type === 'node.status' || event.type === 'node.result') &&
      event.node_id &&
      event.node_status
    ) {
      const nodeId = event.node_id
      setState((current) =>
        current.subscription === subscription && isCurrent(subscription)
          ? {
              ...current,
              nodes: {
                ...current.nodes,
                [nodeId]: mergeExecutionEvent(current.nodes[nodeId], event as NodeExecutionEvent),
              },
            }
          : current,
      )
    }
    if (event.type === 'execution.completed') void complete(subscription)
  }
  async function reconcile(executionId: string): Promise<void> {
    if (!isActive(subscription) || executionId !== subscription.executionId || !projectId) return
    const result = await getWorkflowExecution(projectId, executionId, true)
    if (!isCurrent(subscription)) return
    if (await finish(subscription, result)) return
    if (result.execution.id !== executionId || !belongsToScope(result.execution, scope)) return
    setState((current) =>
      current.subscription === subscription && isCurrent(subscription)
        ? {
            ...current,
            execution: result.execution,
            nodes: {
              ...current.nodes,
              ...Object.fromEntries(result.nodes.map((node) => [node.node_id, node])),
            },
          }
        : current,
    )
  }
  function onHistoryGap(executionId: string) {
    if (!isActive(subscription) || executionId !== subscription.executionId) return
    setState((current) =>
      current.subscription === subscription && isCurrent(subscription)
        ? { ...current, historyIncompleteId: executionId }
        : current,
    )
  }
  useExecutionEvents(activeExecutionId, token, onEvent, reconcile, onHistoryGap)
  return { ...view, activeExecutionId, reserve, reset, begin, isCurrent }
}
