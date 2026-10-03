import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useRef, useState } from 'react'

import { useAuthStore } from '../auth/auth-store'
import { apiErrorMessage, type ApiVersion, type ExecutionDetail } from '../../lib/api'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'
import { executeApi, getApiExecution, listExecutions } from './api-service'

type Input = {
  projectId: string | null
  apiId: string | null
  executionId?: string
  environmentId: string | null
  expectedStatus: number
  assertions?: ApiVersion['assertions']
}

type RunInput = {
  projectId: string
  apiId: string
  environmentId: string
  expectedStatus: number
  assertions?: ApiVersion['assertions']
  scope: string
  identity: string
  sequence: number
}

export function useApiExecutions(input: Input) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const identity = useAuthStore((state) =>
    JSON.stringify([state.user?.id, state.epoch, state.organizationId]),
  )
  const scope = JSON.stringify([identity, input.projectId, input.apiId])
  const [page, setPage] = useRouteScopedState(input.projectId, scope, 1)
  const [results, setResults] = useState(new Map<string, ExecutionDetail>())
  const sequences = useRef(new Map<string, number>())
  const history = useQuery({
    queryKey: ['api-executions', identity, input.projectId, input.apiId, page],
    queryFn: () =>
      listExecutions(required(input.projectId), { apiId: required(input.apiId), page }),
    enabled: Boolean(input.projectId && input.apiId),
  })
  const selectedExecution = useQuery({
    queryKey: ['api-execution', identity, input.projectId, input.apiId, input.executionId],
    queryFn: async ({ signal }) => {
      const value = await getApiExecution(
        required(input.projectId),
        required(input.executionId),
        signal,
      )
      assertOwnership(value, input.projectId, input.apiId)
      return value
    },
    enabled: Boolean(input.projectId && input.apiId && input.executionId),
    refetchInterval: (query) => (query.state.data?.execution.status === 'running' ? 1500 : false),
  })
  const run = useMutation({
    mutationFn: (target: RunInput) =>
      executeApi(
        target.projectId,
        target.apiId,
        target.environmentId,
        target.expectedStatus,
        target.assertions,
      ),
    onSuccess: async (value, target) => {
      assertOwnership(value, target.projectId, target.apiId)
      const session = useAuthStore.getState()
      if (
        JSON.stringify([session.user?.id, session.epoch, session.organizationId]) !==
        target.identity
      )
        return
      if (sequences.current.get(target.scope) !== target.sequence) return
      setResults((previous) => new Map(previous).set(target.scope, value))
      await queryClient.invalidateQueries({
        queryKey: ['api-executions', target.identity, target.projectId, target.apiId],
      })
      void message.open({ type: statusType(value), content: executionMessage(value) })
    },
    onError: (error) => void message.error(apiErrorMessage(error)),
  })

  function execute() {
    const sequence = (sequences.current.get(scope) ?? 0) + 1
    sequences.current.set(scope, sequence)
    run.mutate({
      projectId: required(input.projectId),
      apiId: required(input.apiId),
      environmentId: required(input.environmentId),
      expectedStatus: input.expectedStatus,
      assertions: input.assertions,
      scope,
      identity,
      sequence,
    })
  }

  return {
    history,
    historyPage: page,
    setHistoryPage: setPage,
    selectedExecution,
    viewingHistory: Boolean(input.executionId),
    result: input.executionId ? (selectedExecution.data ?? null) : (results.get(scope) ?? null),
    execute,
    executing: run.isPending && run.variables?.scope === scope,
  }
}

function assertOwnership(value: ExecutionDetail, projectId: string | null, apiId: string | null) {
  if (value.execution.project_id !== projectId || value.execution.api_definition_id !== apiId) {
    throw new Error('执行记录不属于当前接口资产，请从该接口的执行历史重新选择。')
  }
}

function required(value: string | null | undefined) {
  if (!value) throw new Error('请先选择项目、环境和接口')
  return value
}

function statusType(value: ExecutionDetail): 'success' | 'info' | 'error' {
  if (value.execution.status === 'passed') return 'success'
  return value.execution.status === 'running' ? 'info' : 'error'
}

function executionMessage(value: ExecutionDetail): string {
  if (value.execution.status === 'passed') return '接口执行通过'
  if (value.execution.status === 'running') return '接口正在执行'
  if (value.execution.status === 'error') return '接口执行出错，请查看诊断'
  return '接口执行失败，请查看断言和响应'
}
