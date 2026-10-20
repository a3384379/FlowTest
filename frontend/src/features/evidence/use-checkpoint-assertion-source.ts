import { useEffect, useState } from 'react'
import axios from 'axios'
import {
  apiErrorMessage,
  type ExecutionCheckpoint,
  type WorkflowExecutionDetail,
  type WorkflowNodeObservation,
} from '../../lib/api'
import { getWorkflowExecution } from '../workflows/workflow-service'
import { snapshotDefinition } from '../workflows/workflow-runtime'
import type { AssertionSourceContext, AssertionSourceNode } from './assertion-source'

type SourceLoad = {
  key: string
  detail?: WorkflowExecutionDetail
  error?: string
  traceId?: string
}
export function useCheckpointAssertionSource(
  projectId: string,
  checkpoint: ExecutionCheckpoint,
  observations: WorkflowNodeObservation[],
) {
  const [revision, setRevision] = useState(0)
  const [load, setLoad] = useState<SourceLoad | null>(null)
  const executionId = checkpoint.execution_id
  const nested = checkpoint.node_id.startsWith('__nested_request__:')
  const key = JSON.stringify([projectId, executionId, revision])
  useEffect(() => {
    if (nested) return
    let active = true
    void getWorkflowExecution(projectId, executionId, true)
      .then((detail) => {
        if (active) setLoad({ key, detail })
      })
      .catch((error: unknown) => {
        const traceId = axios.isAxiosError(error)
          ? error.response?.data?.error?.trace_id
          : undefined
        if (active)
          setLoad({
            key,
            error: apiErrorMessage(error),
            traceId: typeof traceId === 'string' ? traceId : undefined,
          })
      })
    return () => {
      active = false
    }
  }, [projectId, executionId, nested, key])
  const current = load?.key === key ? load : undefined
  return {
    location: checkpointAssertionLocation(projectId, checkpoint, current?.detail, observations),
    error: current?.error,
    traceId: current?.traceId,
    loading: !nested && !current,
    retry: () => setRevision((value) => value + 1),
  }
}

function checkpointAssertionLocation(
  projectId: string,
  checkpoint: ExecutionCheckpoint,
  detail: WorkflowExecutionDetail | undefined,
  observations: WorkflowNodeObservation[],
): AssertionSourceContext {
  const nested = checkpoint.node_id.startsWith('__nested_request__:')
  const owner: AssertionSourceNode = {
    node_id: checkpoint.node_id,
    node_type: checkpoint.node_type,
    name: checkpoint.node_name,
    status: checkpoint.status,
    attempts: checkpoint.attempt,
    observations,
  }
  return {
    projectId,
    executionId: checkpoint.execution_id,
    assertionNodeId: checkpoint.node_id,
    nodes: [...(detail?.nodes ?? []).filter((node) => node.node_id !== checkpoint.node_id), owner],
    frozenDefinition: detail ? snapshotDefinition(detail.execution.snapshot) : undefined,
    instanceId: nested ? checkpoint.node_id : undefined,
  }
}
