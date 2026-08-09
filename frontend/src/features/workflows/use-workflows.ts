import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useState } from 'react'

import {
  apiErrorMessage,
  type WorkflowDefinition,
  type WorkflowExecutionDetail,
} from '../../lib/api'
import {
  createWorkflow,
  executeWorkflow,
  listApis,
  listEnvironments,
  listProjects,
  listWorkflowExecutions,
  listWorkflows,
  publishWorkflow,
  updateWorkflowDraft,
} from './workflow-service'

export type CreateWorkflowInput = { name: string; description: string; apiId: string }

export function useWorkflows() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [projectSelection, setProjectSelection] = useState<string | null>(null)
  const [environmentSelection, setEnvironmentSelection] = useState<string | null>(null)
  const [workflowSelection, setWorkflowSelection] = useState<string | null>(null)
  const [draftEdit, setDraftEdit] = useState<{ workflowId: string; text: string } | null>(null)
  const [lastResult, setLastResult] = useState<WorkflowExecutionDetail | null>(null)

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
  const workflows = useQuery({
    queryKey: ['workflows', projectId],
    queryFn: () => listWorkflows(requiredId(projectId)),
    enabled: Boolean(projectId),
  })
  const workflowId = selectedOrFirst(workflowSelection, workflows.data?.items)
  const selectedWorkflow = workflows.data?.items.find((item) => item.id === workflowId) ?? null
  const draftText = draftSource(draftEdit, workflowId, selectedWorkflow)
  const executions = useQuery({
    queryKey: ['workflow-executions', projectId],
    queryFn: () => listWorkflowExecutions(requiredId(projectId)),
    enabled: Boolean(projectId),
  })

  const createMutation = useMutation({
    mutationFn: (input: CreateWorkflowInput) => createWorkflow(requiredId(projectId), input),
  })
  const saveMutation = useMutation({
    mutationFn: (definition: WorkflowDefinition) =>
      updateWorkflowDraft(requiredId(projectId), requiredWorkflow(selectedWorkflow), definition),
  })
  const publishMutation = useMutation({
    mutationFn: () => publishWorkflow(requiredId(projectId), requiredId(workflowId)),
  })
  const executeMutation = useMutation({
    mutationFn: () =>
      executeWorkflow(requiredId(projectId), requiredId(workflowId), requiredId(environmentId)),
  })

  function selectProject(value: string) {
    setProjectSelection(value)
    setEnvironmentSelection(null)
    setWorkflowSelection(null)
    setDraftEdit(null)
    setLastResult(null)
  }

  async function addWorkflow(input: CreateWorkflowInput) {
    await runMutation(message.error, async () => {
      const created = await createMutation.mutateAsync(input)
      await refreshWorkflows()
      setWorkflowSelection(created.id)
      void message.success('工作流草稿已创建')
    })
  }

  async function saveDraft() {
    await runMutation(message.error, async () => {
      const definition = parseDefinition(draftText)
      await saveMutation.mutateAsync(definition)
      setDraftEdit(null)
      await refreshWorkflows()
      void message.success('草稿已保存')
    })
  }

  async function publish() {
    await runMutation(message.error, async () => {
      const published = await publishMutation.mutateAsync()
      await refreshWorkflows()
      void message.success(`工作流 v${published.version} 已发布`)
    })
  }

  async function execute() {
    await runMutation(message.error, async () => {
      const result = await executeMutation.mutateAsync()
      setLastResult(result)
      await queryClient.invalidateQueries({ queryKey: ['workflow-executions', projectId] })
      void message.success(
        result.execution.status === 'passed' ? '工作流执行通过' : '工作流执行完成',
      )
    })
  }

  async function refreshWorkflows() {
    await queryClient.invalidateQueries({ queryKey: ['workflows', projectId] })
  }

  return {
    projects,
    projectId,
    selectProject,
    environments,
    environmentId,
    setEnvironmentSelection,
    apis,
    workflows,
    workflowId,
    setWorkflowSelection,
    selectedWorkflow,
    executions,
    draftText,
    setDraftText: (text: string) => {
      if (workflowId) setDraftEdit({ workflowId, text })
    },
    lastResult,
    addWorkflow,
    saveDraft,
    publish,
    execute,
    creating: createMutation.isPending,
    saving: saveMutation.isPending,
    publishing: publishMutation.isPending,
    executing: executeMutation.isPending,
  }
}

type Identified = { id: string }

function draftSource(
  edit: { workflowId: string; text: string } | null,
  workflowId: string | null,
  workflow: { draft_definition: WorkflowDefinition } | null,
): string {
  if (edit?.workflowId === workflowId) return edit.text
  return workflow ? JSON.stringify(workflow.draft_definition, null, 2) : ''
}

function selectedOrFirst(selection: string | null, items?: Identified[]): string | null {
  return selection ?? items?.at(0)?.id ?? null
}

function requiredId(value: string | null): string {
  if (!value) throw new Error('缺少必要的资源标识')
  return value
}

function requiredWorkflow<T>(value: T | null): T {
  if (!value) throw new Error('请选择工作流')
  return value
}

function parseDefinition(source: string): WorkflowDefinition {
  const parsed: unknown = JSON.parse(source)
  if (!isRecord(parsed) || !Array.isArray(parsed.nodes) || !Array.isArray(parsed.edges)) {
    throw new Error('工作流 JSON 必须包含 nodes 和 edges 数组')
  }
  return parsed as WorkflowDefinition
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

async function runMutation(
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
