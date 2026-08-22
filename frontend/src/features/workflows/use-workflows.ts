import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useRef, useState } from 'react'

import {
  apiErrorMessage,
  type ExecutionEvent,
  type WorkflowDebugResult,
  type WorkflowDefinition,
  type WorkflowExecution,
  type WorkflowExecutionDetail,
  type WorkflowNodeExecution,
  type WorkflowVersionDiff,
} from '../../lib/api'
import { useAuthStore } from '../auth/auth-store'
import { useProjectContext } from '../projects/use-project-context'
import { listCredentials } from '../data-sources/data-source-service'
import {
  listEventSources,
  listGraphQLSchemas,
  listGrpcDescriptors,
} from '../protocols/protocol-service'
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
export type WorkflowWorkspaceMode = 'draft' | 'run' | 'history'

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
  const [activeExecution, setActiveExecution] = useState<WorkflowExecution | null>(null)
  const [activeExecutionId, setActiveExecutionId] = useState<string | null>(null)
  const [liveNodes, setLiveNodes] = useState<Record<string, WorkflowNodeExecution>>({})
  const [executionDefinition, setExecutionDefinition] = useState<WorkflowDefinition | null>(null)
  const [workspaceMode, setWorkspaceMode] = useState<WorkflowWorkspaceMode>('draft')
  const [historyExecutionId, setHistoryExecutionId] = useState<string | null>(null)
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
  const credentials = useQuery({
    queryKey: ['credentials', projectId],
    queryFn: () => listCredentials(requiredId(projectId)),
    enabled: Boolean(projectId),
  })
  const graphqlSchemas = useQuery({
    queryKey: ['graphql-schemas', projectId],
    queryFn: () => listGraphQLSchemas(requiredId(projectId)),
    enabled: Boolean(projectId),
  })
  const grpcDescriptors = useQuery({
    queryKey: ['grpc-descriptors', projectId],
    queryFn: () => listGrpcDescriptors(requiredId(projectId)),
    enabled: Boolean(projectId),
  })
  const eventSources = useQuery({
    queryKey: ['event-sources', projectId],
    queryFn: () => listEventSources(requiredId(projectId)),
    enabled: Boolean(projectId),
  })
  const workflowId = selectedOrFirst(workflowSelection, workflows.data?.items)
  const selectedWorkflow = workflows.data?.items.find((item) => item.id === workflowId) ?? null
  const draftDefinition = draftSource(draftEdit, workflowId, selectedWorkflow)
  const breakpointNodes = draftDefinition.nodes.filter((node) => node.type !== 'start')
  const breakpointNodeId = selectedOrFirst(breakpointSelection, breakpointNodes)
  const executions = useQuery({
    queryKey: ['workflow-executions', projectId, workflowId],
    queryFn: () => listWorkflowExecutions(requiredId(projectId), requiredId(workflowId)),
    enabled: Boolean(projectId && workflowId),
  })
  const historyExecution = useQuery({
    queryKey: ['workflow-execution', projectId, historyExecutionId],
    queryFn: () => getWorkflowExecution(requiredId(projectId), requiredId(historyExecutionId)),
    enabled: Boolean(projectId && historyExecutionId && workspaceMode === 'history'),
  })
  const createMutation = useMutation({
    mutationFn: (input: CreateWorkflowInput) =>
      createWorkflow(requiredId(projectId), {
        ...input,
        apiVersion: apis.data?.items.find((api) => api.id === input.apiId)?.current_version,
      }),
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
    setActiveExecution(null)
    setActiveExecutionId(null)
    setLiveNodes({})
    setExecutionDefinition(null)
    setWorkspaceMode('draft')
    setHistoryExecutionId(null)
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
      setActiveExecution(execution)
      setExecutionDefinition(runningDefinition)
      setLiveNodes(initialNodeExecutions(execution.id, runningDefinition))
      completedExecutionId.current = null
      setActiveExecutionId(execution.id)
      setWorkspaceMode('run')
      setHistoryExecutionId(null)
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
    if (
      (event.type === 'node.status' || event.type === 'node.result') &&
      event.node_id &&
      event.node_status
    ) {
      const nodeId = event.node_id
      setLiveNodes((current) => ({
        ...current,
        [nodeId]: mergeExecutionEvent(current[nodeId], event as NodeExecutionEvent),
      }))
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
      if (['queued', 'running'].includes(result.execution.status)) return false
      completedExecutionId.current = executionId
      setLastResult(result)
      setActiveExecution(result.execution)
      setLiveNodes(Object.fromEntries(result.nodes.map((node) => [node.node_id, node])))
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

  function selectWorkflow(value: string) {
    setWorkflowSelection(value)
    setDraftEdit(null)
    setLastResult(null)
    setActiveExecution(null)
    setActiveExecutionId(null)
    setLiveNodes({})
    setExecutionDefinition(null)
    setWorkspaceMode('draft')
    setHistoryExecutionId(null)
  }

  function showDraft() {
    setWorkspaceMode('draft')
    setHistoryExecutionId(null)
  }

  function showLatestRun() {
    if (activeExecution || lastResult) setWorkspaceMode('run')
  }

  function showHistory(executionId: string) {
    setHistoryExecutionId(executionId)
    setWorkspaceMode('history')
  }

  const workspaceView = buildWorkspaceView({
    mode: workspaceMode,
    draftDefinition,
    executionDefinition,
    activeExecution,
    lastResult,
    historyDetail: historyExecution.data ?? null,
    liveNodes,
  })

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
    credentials,
    graphqlSchemas,
    grpcDescriptors,
    eventSources,
    workflowId,
    setWorkflowSelection: selectWorkflow,
    selectedWorkflow,
    executions,
    draftDefinition,
    designerDefinition: workspaceView.definition,
    setDraftDefinition: (definition: WorkflowDefinition) => {
      if (workflowId) {
        setDraftEdit({ workflowId, definition })
        setExecutionDefinition(null)
      }
    },
    nodeStatuses: workspaceView.statuses,
    activeExecutionId,
    lastResult,
    runtimeExecution: workspaceView.execution,
    runtimeNodes: workspaceView.nodes,
    runtimeChildren: workspaceView.children,
    runtimeContext: workspaceView.context,
    workspaceMode,
    showDraft,
    showLatestRun,
    showHistory,
    historyExecutionId,
    historyLoading: historyExecution.isLoading,
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

function initialNodeExecutions(
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

type NodeExecutionEvent = ExecutionEvent & {
  node_id: string
  node_status: WorkflowNodeExecution['status']
}

type WorkspaceViewInput = {
  mode: WorkflowWorkspaceMode
  draftDefinition: WorkflowDefinition
  executionDefinition: WorkflowDefinition | null
  activeExecution: WorkflowExecution | null
  lastResult: WorkflowExecutionDetail | null
  historyDetail: WorkflowExecutionDetail | null
  liveNodes: Record<string, WorkflowNodeExecution>
}

function buildWorkspaceView(input: WorkspaceViewInput) {
  if (input.mode === 'history') return historicalWorkspaceView(input)
  if (input.mode === 'run') return runningWorkspaceView(input)
  return {
    definition: input.draftDefinition,
    execution: null,
    nodes: [],
    children: [],
    statuses: {},
    context: {},
  }
}

function historicalWorkspaceView(input: WorkspaceViewInput) {
  const detail = input.historyDetail
  if (!detail) {
    return {
      definition: input.draftDefinition,
      execution: null,
      nodes: [],
      children: [],
      statuses: {},
      context: {},
    }
  }
  const nodes = detail.nodes
  return {
    definition: snapshotDefinition(detail.execution.snapshot) ?? input.draftDefinition,
    execution: detail.execution,
    nodes,
    children: detail.children,
    statuses: nodeStatusMap(nodes),
    context: detail.execution.context,
  }
}

function runningWorkspaceView(input: WorkspaceViewInput) {
  const nodes = orderedLiveNodes(input.executionDefinition, input.liveNodes)
  return {
    definition: input.executionDefinition ?? input.draftDefinition,
    execution: input.activeExecution,
    nodes,
    children: input.lastResult?.children ?? [],
    statuses: nodeStatusMap(nodes),
    context: input.lastResult?.execution.context ?? {},
  }
}

function nodeStatusMap(nodes: WorkflowNodeExecution[]): Record<string, string> {
  return Object.fromEntries(nodes.map((node) => [node.node_id, node.status]))
}

function mergeExecutionEvent(
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

function orderedLiveNodes(
  definition: WorkflowDefinition | null,
  nodes: Record<string, WorkflowNodeExecution>,
): WorkflowNodeExecution[] {
  if (!definition) return Object.values(nodes)
  return definition.nodes.flatMap((node) => (nodes[node.id] ? [nodes[node.id]] : []))
}

function isTerminalNodeStatus(status: WorkflowNodeExecution['status']): boolean {
  return !['pending', 'running'].includes(status)
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
