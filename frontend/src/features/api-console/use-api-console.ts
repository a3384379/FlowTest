import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useState } from 'react'

import { apiErrorMessage, type ExecutionDetail } from '../../lib/api'
import {
  createApi,
  createEnvironment,
  createProject,
  executeApi,
  listApis,
  listEnvironments,
  listExecutions,
  listProjects,
  type CreateApiInput,
  type CreateEnvironmentInput,
  type CreateProjectInput,
} from './api-service'

export function useApiConsole() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [projectSelection, setProjectSelection] = useState<string | null>(null)
  const [environmentSelection, setEnvironmentSelection] = useState<string | null>(null)
  const [apiSelection, setApiSelection] = useState<string | null>(null)
  const [expectedStatus, setExpectedStatus] = useState(200)
  const [result, setResult] = useState<ExecutionDetail | null>(null)

  const projects = useQuery({ queryKey: ['projects'], queryFn: listProjects })
  const projectId = selectedOrFirst(projectSelection, projects.data?.items)
  const environments = useQuery({
    queryKey: ['environments', projectId],
    queryFn: () => listEnvironments(requiredId(projectId)),
    enabled: Boolean(projectId),
  })
  const environmentId = selectedOrFirst(environmentSelection, environments.data)
  const apis = useQuery({
    queryKey: ['apis', projectId],
    queryFn: () => listApis(requiredId(projectId)),
    enabled: Boolean(projectId),
  })
  const apiId = selectedOrFirst(apiSelection, apis.data?.items)
  const history = useQuery({
    queryKey: ['executions', projectId],
    queryFn: () => listExecutions(requiredId(projectId)),
    enabled: Boolean(projectId),
  })

  const projectMutation = useMutation({ mutationFn: createProject })
  const environmentMutation = useMutation({
    mutationFn: (input: CreateEnvironmentInput) => createEnvironment(requiredId(projectId), input),
  })
  const apiMutation = useMutation({
    mutationFn: (input: CreateApiInput) => createApi(requiredId(projectId), input),
  })
  const executionMutation = useMutation({
    mutationFn: () =>
      executeApi(
        requiredId(projectId),
        requiredId(apiId),
        requiredId(environmentId),
        expectedStatus,
      ),
    onSuccess: async (value) => {
      setResult(value)
      await queryClient.invalidateQueries({ queryKey: ['executions', projectId] })
      void message.success(executionMessage(value))
    },
    onError: (error) => void message.error(apiErrorMessage(error)),
  })

  function selectProject(value: string) {
    setProjectSelection(value)
    setEnvironmentSelection(null)
    setApiSelection(null)
    setResult(null)
  }

  async function addProject(input: CreateProjectInput) {
    await withErrorMessage(message.error, async () => {
      const project = await projectMutation.mutateAsync(input)
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
      selectProject(project.id)
    })
  }

  async function addEnvironment(input: CreateEnvironmentInput) {
    await withErrorMessage(message.error, async () => {
      const environment = await environmentMutation.mutateAsync(input)
      await queryClient.invalidateQueries({ queryKey: ['environments', projectId] })
      setEnvironmentSelection(environment.id)
    })
  }

  async function addApi(input: CreateApiInput) {
    await withErrorMessage(message.error, async () => {
      const definition = await apiMutation.mutateAsync(input)
      await queryClient.invalidateQueries({ queryKey: ['apis', projectId] })
      setApiSelection(definition.id)
    })
  }

  return {
    projects,
    projectId,
    selectProject,
    environments,
    environmentId,
    setEnvironmentSelection,
    apis,
    apiId,
    setApiSelection,
    history,
    expectedStatus,
    setExpectedStatus,
    result,
    execute: executionMutation.mutate,
    executing: executionMutation.isPending,
    addProject,
    addEnvironment,
    addApi,
    submitting: [
      projectMutation.isPending,
      environmentMutation.isPending,
      apiMutation.isPending,
    ].some(Boolean),
  }
}

type Identified = { id: string }

function selectedOrFirst(selection: string | null, items?: Identified[]): string | null {
  if (selection) return selection
  return items?.at(0)?.id ?? null
}

function requiredId(value: string | null): string {
  if (!value) throw new Error('缺少必要的资源标识')
  return value
}

function executionMessage(result: ExecutionDetail): string {
  return result.execution.status === 'passed' ? '接口执行通过' : '接口执行完成'
}

async function withErrorMessage(
  showError: (content: string) => unknown,
  operation: () => Promise<void>,
) {
  try {
    await operation()
  } catch (error) {
    showError(apiErrorMessage(error))
    throw error
  }
}
