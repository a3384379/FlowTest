import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useRef, useState } from 'react'

import {
  apiErrorMessage,
  type ExecutionEvent,
  type WorkflowDebugResult,
  type WorkflowDefinition,
  type WorkflowExecutionDetail,
  type WorkflowVersionDiff,
} from '../../lib/api'
import { useAuthStore } from '../auth/auth-store'
import { useProjectContext } from '../projects/use-project-context'
import { useExecutionEvents } from './use-execution-events'
import {
  createWorkflow,
  debugWorkflow,
  diffWorkflowVersions,
  executeWorkflow,
  getWorkflowExecution,
  listApis,
  listArtifacts,
  listEnvironments,
  listWorkflowExecutions,
  listWorkflows,
  publishWorkflow,
  replayWorkflowNode,
  updateWorkflowDraft,
} from './workflow-service'

export type CreateWorkflowInput = { name: string; description: string; apiId: string }

export function useWorkflows() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const token = useAuthStore((store) => store.token)
  const { projects, projectId, selectProject: selectContextProject } = useProjectContext()
  const [environmentSelection, setEnvironmentSelection] = useState<string | null>(null)
  const [workflowSelection, setWorkflowSelection] = useState<string | null>(null)
  const [draftEdit, setDraftEdit] = useState<{
    workflowId: string
    definition: WorkflowDefinition
  } | null>(null)
  const [lastResult, setLastResult] = useState<WorkflowExecutionDetail | null>(null)
  const [activeExecutionId, setActiveExecutionId] = useState<string | null>(null)
  const [nodeStatuses, setNodeStatuses] = useState<Record<string, string>>({})
  const [executionDefinition, setExecutionDefinition] = useState<WorkflowDefinition | null>(null)
  const [breakpointSelection, setBreakpointSelection] = useState<string | null>(null)
  const [debugResult, setDebugResult] = useState<WorkflowDebugResult | null>(null)
  const [versionDiff, setVersionDiff] = useState<WorkflowVersionDiff | null>(null)
  const completedExecutionId = useRef<string | null>(null)
  const completingExecutionId = useRef<string | null>(null)

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
  const artifacts = useQuery({
    queryKey: ['artifacts', projectId],
    queryFn: () => listArtifacts(requiredId(projectId)),
    enabled: Boolean(projectId),
  })
  const workflows = useQuery({
    queryKey: ['workflows', projectId],
    queryFn: () => listWorkflows(requiredId(projectId)),
    enabled: Boolean(projectId),
  })
  const workflowId = selectedOrFirst(workflowSelection, workflows.data?.items)
  const selectedWorkflow = workflows.data?.items.find((item) => item.id === workflowId) ?? null
  const draftDefinition = draftSource(draftEdit, workflowId, selectedWorkflow)
  const breakpointNodes = draftDefinition.nodes.filter((node) => node.type !== 'start')
  const breakpointNodeId = selectedOrFirst(breakpointSelection, breakpointNodes)
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
  const debugMutation = useMutation({
    mutationFn: () =>
      debugWorkflow(
        requiredId(projectId),
        requiredId(workflowId),
        requiredId(environmentId),
        requiredVersion(selectedWorkflow?.current_version),
        requiredId(breakpointNodeId),
      ),
  })
  const diffMutation = useMutation({
    mutationFn: () => {
      const current = requiredVersion(selectedWorkflow?.current_version)
      if (current < 2) throw new Error('至少发布两个版本后才能比较')
      return diffWorkflowVersions(
        requiredId(projectId),
        requiredId(workflowId),
        current - 1,
        current,
      )
    },
  })
  const replayMutation = useMutation({
    mutationFn: (nodeId: string) =>
      replayWorkflowNode(
        requiredId(projectId),
        requiredId(lastResult?.execution.id ?? null),
        nodeId,
      ),
  })

  useExecutionEvents(activeExecutionId, token, handleExecutionEvent)

  function selectProject(value: string) {
    selectContextProject(value)
    setEnvironmentSelection(null)
    setWorkflowSelection(null)
    setDraftEdit(null)
    setLastResult(null)
    setActiveExecutionId(null)
    setNodeStatuses({})
    setExecutionDefinition(null)
    setBreakpointSelection(null)
    setDebugResult(null)
    setVersionDiff(null)
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
      await saveMutation.mutateAsync(draftDefinition)
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
      const execution = await executeMutation.mutateAsync()
      const runningDefinition = snapshotDefinition(execution.snapshot) ?? draftDefinition
      setLastResult(null)
      setExecutionDefinition(runningDefinition)
      setNodeStatuses(
        Object.fromEntries(runningDefinition.nodes.map((node) => [node.id, 'pending'])),
      )
      completedExecutionId.current = null
      setActiveExecutionId(execution.id)
      void watchExecution(execution.id)
      void message.info('工作流已开始运行')
    })
  }

  async function debugToBreakpoint() {
    await runMutation(message.error, async () => {
      setDebugResult(await debugMutation.mutateAsync())
      void message.success('已运行至断点前')
    })
  }

  async function compareLatestVersions() {
    await runMutation(message.error, async () => {
      setVersionDiff(await diffMutation.mutateAsync())
    })
  }

  async function replayNode(nodeId: string) {
    await runMutation(message.error, async () => {
      setDebugResult(await replayMutation.mutateAsync(nodeId))
      void message.success('节点重放完成')
    })
  }

  function handleExecutionEvent(event: ExecutionEvent) {
    if (event.type === 'node.status' && event.node_id && event.node_status) {
      const nodeId = event.node_id
      const status = event.node_status
      setNodeStatuses((current) => ({ ...current, [nodeId]: status }))
    }
    if (event.type === 'execution.completed') void completeExecution(event.execution_id)
  }

  async function watchExecution(executionId: string) {
    for (let attempt = 0; attempt < 600; attempt += 1) {
      await delay(500)
      if (await completeExecution(executionId)) return
    }
    void message.error('等待工作流执行结果超时')
  }

  async function completeExecution(executionId: string): Promise<boolean> {
    if (completedExecutionId.current === executionId) return true
    if (completingExecutionId.current === executionId) return false
    completingExecutionId.current = executionId
    try {
      const result = await getWorkflowExecution(requiredId(projectId), executionId)
      if (result.execution.status === 'running') return false
      completedExecutionId.current = executionId
      setLastResult(result)
      setNodeStatuses(Object.fromEntries(result.nodes.map((node) => [node.node_id, node.status])))
      setActiveExecutionId(null)
      await queryClient.invalidateQueries({ queryKey: ['workflow-executions', projectId] })
      void message.success(
        result.execution.status === 'passed' ? '工作流执行通过' : '工作流执行完成',
      )
      return true
    } catch {
      return false
    } finally {
      if (completingExecutionId.current === executionId) completingExecutionId.current = null
    }
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
    artifacts,
    workflows,
    workflowId,
    setWorkflowSelection,
    selectedWorkflow,
    executions,
    draftDefinition,
    designerDefinition: executionDefinition ?? draftDefinition,
    setDraftDefinition: (definition: WorkflowDefinition) => {
      if (workflowId) {
        setDraftEdit({ workflowId, definition })
        setExecutionDefinition(null)
        setNodeStatuses({})
      }
    },
    nodeStatuses,
    activeExecutionId,
    lastResult,
    breakpointNodes,
    breakpointNodeId,
    setBreakpointSelection,
    debugResult,
    versionDiff,
    closeVersionDiff: () => setVersionDiff(null),
    addWorkflow,
    saveDraft,
    publish,
    execute,
    debugToBreakpoint,
    compareLatestVersions,
    replayNode,
    creating: createMutation.isPending,
    saving: saveMutation.isPending,
    publishing: publishMutation.isPending,
    executing: executeMutation.isPending,
    debugging: debugMutation.isPending,
    comparing: diffMutation.isPending,
    replaying: replayMutation.isPending,
  }
}

type Identified = { id: string }

function draftSource(
  edit: { workflowId: string; definition: WorkflowDefinition } | null,
  workflowId: string | null,
  workflow: { draft_definition: WorkflowDefinition } | null,
): WorkflowDefinition {
  if (edit?.workflowId === workflowId) return edit.definition
  return workflow?.draft_definition ?? emptyDefinition()
}

function selectedOrFirst(selection: string | null, items?: Identified[]): string | null {
  if (selection && items?.some((item) => item.id === selection)) return selection
  return items?.at(0)?.id ?? null
}

function requiredId(value: string | null): string {
  if (!value) throw new Error('缺少必要的资源标识')
  return value
}

function requiredWorkflow<T>(value: T | null): T {
  if (!value) throw new Error('请选择工作流')
  return value
}

function requiredVersion(value: number | null | undefined): number {
  if (!value) throw new Error('工作流尚未发布')
  return value
}

function emptyDefinition(): WorkflowDefinition {
  return {
    schema_version: '1.0',
    variables: {},
    nodes: [],
    edges: [],
    settings: { fail_fast: true, concurrency: 20, default_timeout_seconds: 30 },
  }
}

function snapshotDefinition(snapshot: Record<string, unknown>): WorkflowDefinition | null {
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

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}
