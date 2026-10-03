import { getProjectPermission } from '../projects/project-service'
import { analyzeGraph } from '../../flow/editor/graph-analysis'
import { nodeEditorScope } from '../../flow/editor/editor-identity'
import { useDraftSession } from '../drafts/draft-session'
import { useEnvironmentSelection } from '../projects/environment-selection'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  apiErrorMessage,
  type Page,
  type WorkflowDebugResult,
  type WorkflowDefinition,
  type WorkflowExecution,
  type WorkflowExecutionDetail,
  type Workflow,
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
import { useWorkflowExecution, type ExecutionTicket } from './use-workflow-execution'
import { snapshotDefinition } from './workflow-runtime'
import type { WorkflowTemplateKind } from './workflow-templates'
import {
  clearWorkflowDrafts,
  readWorkflowDraft,
  removeWorkflowDraft,
  workflowDraftKey,
  writeWorkflowDraft,
  type WorkflowDraftKey,
} from './workflow-draft-store'
import { useRouteScopedSelection, useRouteScopedState } from '../../lib/use-route-scoped-state'
import {
  createWorkflow,
  deleteWorkflow,
  debugWorkflow,
  diffWorkflowVersions,
  executeWorkflow,
  getWorkflow,
  getWorkflowExecution,
  listApis,
  listArtifacts,
  listEnvironments,
  listWorkflowExecutions,
  listWorkflows,
  publishWorkflow,
  replayWorkflowNode,
  rerunFailedWorkflowItems,
  type FailedItemRerunRequest,
  updateWorkflowDraft,
} from './workflow-service'

export type CreateWorkflowInput = {
  name: string
  description: string
  apiId: string
  submitApiId?: string
  template?: WorkflowTemplateKind
}
export type WorkflowWorkspaceMode = 'draft' | 'run' | 'history'
export type WorkflowDraftEdit = {
  workflowId: string
  definition: WorkflowDefinition
  baseRevision: number
  editVersion: number
}

export function useWorkflows(initialWorkflowId?: string, initialExecutionId?: string) {
  const { message, modal } = App.useApp()
  const queryClient = useQueryClient()
  const token = useAuthStore((store) => store.token)
  const userId = useAuthStore((store) => store.user?.id)
  const { projects, projectId, selectProject: selectContextProject } = useProjectContext()
  const permissions = useQuery({
    queryKey: ['project-permissions', projectId],
    queryFn: () => getProjectPermission(requiredId(projectId)),
    enabled: Boolean(projectId),
  })
  const canEdit = permissions.data?.capabilities.includes('edit') ?? false
  const draftScope = `${userId ?? 'anonymous'}:${projectId ?? 'global'}`
  const [workflowSearch, setWorkflowSearchValue] = useRouteScopedState(projectId, null, '')
  const [workflowPage, setWorkflowPage] = useRouteScopedState(projectId, null, 1)
  const [deletedWorkflowIds, setDeletedWorkflowIds] = useRouteScopedState<string[]>(
    draftScope,
    null,
    [],
  )
  const [workflowSelection, setWorkflowSelection] = useRouteScopedSelection(
    projectId,
    initialWorkflowId ?? null,
  )
  const [workflowSelectionCleared, setWorkflowSelectionCleared] = useState(false)
  const [draftEdit, setDraftEdit] = useState<WorkflowDraftEdit | null>(null)
  const draftSession = useDraftSession()
  const [memoryDraftIds, setMemoryDraftIds] = useState<string[]>([])
  const [draftStorageError, setDraftStorageErrorState] = useState<string | null>(null)
  const draftVersionRef = useRef(0)
  const previousUserIdRef = useRef<string | undefined>(userId)
  const scopedMemory = useMemo(
    () => draftSession.workflowScope(draftScope),
    [draftSession, draftScope],
  )
  const memoryDraftsRef = useMemo(() => ({ current: scopedMemory.drafts }), [scopedMemory])
  const draftGenerationRef = useMemo(() => ({ current: scopedMemory.generations }), [scopedMemory])
  const previousDraftScopeRef = useRef(draftScope)
  const { workspaceMode, setWorkspaceMode, historyExecutionId, setHistoryExecutionId } =
    useExecutionSelection(projectId, initialExecutionId)
  const [breakpointSelection, setBreakpointSelection] = useState<string | null>(null)
  const [debugResult, setDebugResult] = useState<WorkflowDebugResult | null>(null)
  const [versionDiff, setVersionDiff] = useState<WorkflowVersionDiff | null>(null)

  const environments = useQuery({
    queryKey: ['environments', projectId],
    queryFn: () => listEnvironments(requiredId(projectId)),
    enabled: Boolean(projectId),
  })
  const {
    environmentId,
    selectEnvironment: setEnvironmentSelection,
    selectionInvalid: environmentSelectionInvalid,
    environmentPlaceholder,
    environmentStatus,
  } = useEnvironmentSelection(projectId, environments.data)
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
    queryKey: ['workflows', projectId, 'catalog', workflowSearch, workflowPage],
    queryFn: () =>
      listWorkflows(requiredId(projectId), {
        page: workflowPage,
        pageSize: 100,
        search: workflowSearch,
      }),
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
  const { workflowId, selectedWorkflow } = useSelectedWorkflow(
    projectId,
    workflowSelection,
    workflowSelectionCleared,
    workflows.data,
    Boolean(initialExecutionId),
    isCompleteWorkflowCatalog(workflowSearch, workflows.data),
  )
  const runtime = useWorkflowExecution(userId, projectId, workflowId, token)
  const {
    result: lastResult,
    execution: activeExecution,
    definition: executionDefinition,
    nodes: liveNodes,
    activeExecutionId,
    historyIncompleteId: eventHistoryIncompleteId,
  } = runtime
  const setDraftStorageError = useCallback(
    (error: string | null, targetId = workflowId) => {
      setDraftStorageErrorState(error)
      if (targetId) {
        if (error) scopedMemory.storageErrors.set(targetId, error)
        else scopedMemory.storageErrors.delete(targetId)
      }
      draftSession.markUnsafe(draftScope, scopedMemory.storageErrors.size > 0)
    },
    [draftSession, draftScope, scopedMemory, workflowId],
  )
  const activeWorkflowIdRef = useRef<string | null>(workflowId)
  const publicationKey = JSON.stringify([
    userId,
    projectId,
    workflowId,
    selectedWorkflow?.draft_revision,
    canEdit,
  ])
  const publicationKeyRef = useRef(publicationKey)
  useEffect(() => {
    activeWorkflowIdRef.current = workflowId
  }, [workflowId])
  useEffect(() => {
    publicationKeyRef.current = publicationKey
  }, [publicationKey])
  const selectedWorkflowId = selectedWorkflow?.id
  const draftKey = useMemo(
    () => workflowDraftIdentity(userId, projectId, workflowId),
    [projectId, userId, workflowId],
  )
  useEffect(() => {
    const previousUserId = previousUserIdRef.current
    if (previousUserId && previousUserId !== userId) {
      const cleared = clearWorkflowDrafts(previousUserId)
      if (!cleared.ok) setDraftStorageError(cleared.error)
    }
    previousUserIdRef.current = userId
  }, [userId, setDraftStorageError])
  useEffect(() => {
    if (previousDraftScopeRef.current === draftScope) return
    previousDraftScopeRef.current = draftScope
    draftVersionRef.current = 0
    let active = true
    queueMicrotask(() => {
      if (!active) return
      setMemoryDraftIds([...scopedMemory.drafts.keys()])
      setDraftEdit(null)
    })
    return () => {
      active = false
    }
  }, [draftScope, scopedMemory])
  useEffect(() => {
    if (!draftStorageError || memoryDraftIds.length === 0) return
    const blockUnload = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', blockUnload)
    return () => window.removeEventListener('beforeunload', blockUnload)
  }, [draftStorageError, memoryDraftIds.length])
  useEffect(() => {
    let active = true
    queueMicrotask(() => {
      if (!active) return
      if (!draftKey || !selectedWorkflowId) {
        setDraftEdit(null)
        draftVersionRef.current = 0
        return
      }
      const inMemory = memoryDraftsRef.current.get(selectedWorkflowId)
      const restored = readWorkflowDraft(draftKey)
      if (inMemory) {
        setDraftEdit(inMemory)
        setMemoryDraftIds([...memoryDraftsRef.current.keys()])
        draftVersionRef.current = inMemory.editVersion
      } else if (restored) {
        setDraftEdit({
          workflowId: restored.resourceKey.workflowId,
          definition: restored.content,
          baseRevision: restored.baseRevision,
          editVersion: restored.editVersion,
        })
        draftVersionRef.current = restored.editVersion
      } else {
        setDraftEdit(null)
        draftVersionRef.current = 0
      }
      setDraftStorageErrorState(scopedMemory.storageErrors.get(selectedWorkflowId) ?? null)
    })
    return () => {
      active = false
    }
  }, [draftKey, selectedWorkflowId, draftScope, draftSession, memoryDraftsRef, scopedMemory])
  const draftDefinition = draftSource(draftEdit, workflowId, selectedWorkflow)
  const breakpointNodes = draftDefinition.nodes.filter((node) => node.type !== 'start')
  const breakpointNodeId = selectedOrFirst(breakpointSelection, breakpointNodes)
  const executions = useQuery({
    queryKey: ['workflow-executions', projectId, workflowId],
    queryFn: () => listWorkflowExecutions(requiredId(projectId), requiredId(workflowId)),
    enabled: canLoadExecutionHistory(projectId, workflowId),
  })
  const historyExecution = useQuery({
    queryKey: ['workflow-execution', projectId, historyExecutionId],
    queryFn: () =>
      getWorkflowExecution(requiredId(projectId), requiredId(historyExecutionId), true),
    enabled: canLoadHistory(projectId, historyExecutionId, workspaceMode),
  })
  const createMutation = useMutation({
    mutationFn: (input: CreateWorkflowInput) =>
      createWorkflow(requiredId(projectId), {
        ...input,
        apiVersion: apis.data?.items.find((api) => api.id === input.apiId)?.current_version,
        submitApiVersion: apis.data?.items.find((api) => api.id === input.submitApiId)
          ?.current_version,
      }),
  })
  const deleteMutation = useMutation({
    mutationFn: (targetWorkflowId: string) =>
      deleteWorkflow(requiredId(projectId), targetWorkflowId),
  })
  const saveMutation = useMutation({
    mutationFn: (input: {
      projectId: string
      workflow: Workflow
      definition: WorkflowDefinition
      expectedRevision: number
    }) =>
      updateWorkflowDraft(
        input.projectId,
        input.workflow,
        input.definition,
        input.expectedRevision,
      ),
  })
  const publishMutation = useMutation({
    mutationFn: (target: { projectId: string; workflowId: string }) =>
      publishWorkflow(target.projectId, target.workflowId),
  })
  const executeMutation = useMutation({
    mutationFn: (target: {
      projectId: string
      workflowId: string
      environmentId: string
      version: number
    }) =>
      executeWorkflow(target.projectId, target.workflowId, target.environmentId, target.version),
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
  const rerunFailedItemsMutation = useMutation({
    mutationFn: (input: { executionId: string; payload: FailedItemRerunRequest }) =>
      rerunFailedWorkflowItems(requiredId(projectId), input.executionId, input.payload),
  })

  function selectProject(value: string) {
    selectContextProject(value)
    setWorkflowSelection(null)
    setWorkflowSelectionCleared(false)
    setDraftEdit(null)
    draftVersionRef.current = 0
    runtime.reset()
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

  async function removeWorkflow(targetWorkflowId = workflowId) {
    if (!targetWorkflowId) return
    invalidateWorkflowDraft(targetWorkflowId)
    await runMutation(message.error, async () => {
      await deleteMutation.mutateAsync(targetWorkflowId)
      setDeletedWorkflowIds([...deletedWorkflowIds, targetWorkflowId])
      const discarded = discardWorkflowDraft(targetWorkflowId)
      if (!discarded.ok) clearMemoryDraft(targetWorkflowId)
      if (targetWorkflowId === workflowId) {
        setWorkflowSelection(null)
        setDraftEdit(null)
        draftVersionRef.current = 0
      }
      await refreshWorkflows()
      void message.success('工作流已删除，历史执行仍会保留')
    })
  }

  function hasPendingNodeEditor(targetWorkflowId: string | null): boolean {
    if (!targetWorkflowId) return false
    const scope = nodeEditorScope(userId ?? 'anonymous', projectId ?? 'embedded', targetWorkflowId)
    if (!draftSession.dirtyNodeEditorKeys(scope).length) return false
    void message.warning('有尚未应用的节点配置，请先返回节点应用或丢弃修改。')
    return true
  }
  function validForSave(definition: WorkflowDefinition): boolean {
    const issues = analyzeGraph(definition)
    if (!issues.length) return true
    void message.error(`流程结构未完成：${issues[0].message}。修改已保留在本地。`)
    return false
  }
  async function saveDraft() {
    if (!canEdit || hasPendingNodeEditor(workflowId) || !validForSave(draftDefinition)) return
    const expectedRevision = draftEdit?.baseRevision ?? selectedWorkflow?.draft_revision
    if (!expectedRevision) return
    const editVersionAtStart = draftVersionRef.current
    const workflowIdAtStart = workflowId
    const draftKeyAtStart = draftKey
    const generationAtStart = draftGenerationRef.current.get(workflowIdAtStart ?? '') ?? 0
    await runMutation(message.error, async () => {
      const saved = await saveMutation.mutateAsync({
        projectId: requiredId(projectId),
        workflow: requiredWorkflow(selectedWorkflow),
        definition: draftDefinition,
        expectedRevision,
      })
      if (!workflowIdAtStart || !draftKeyAtStart) return
      if (!isDraftGenerationCurrent(workflowIdAtStart, generationAtStart)) return
      await synchronizeWorkflow(draftKeyAtStart.projectId, saved)
      if (!isDraftGenerationCurrent(workflowIdAtStart, generationAtStart)) return
      const latest = memoryDraftsRef.current.get(workflowIdAtStart)
      const hasNewerEdit = Boolean(latest && latest.editVersion !== editVersionAtStart)
      if (latest && hasNewerEdit) rebaseWorkflowDraft(latest, saved.draft_revision, draftKeyAtStart)
      else clearPersistedWorkflowDraft(workflowIdAtStart, draftKeyAtStart)
      await refreshWorkflows()
      void message.success(hasNewerEdit ? '服务器已保存，更新后的本地草稿仍待保存' : '草稿已保存')
    })
  }

  function clearPersistedWorkflowDraft(targetWorkflowId: string, targetKey: WorkflowDraftKey) {
    memoryDraftsRef.current.delete(targetWorkflowId)
    setMemoryDraftIds([...memoryDraftsRef.current.keys()])
    const removed = removeWorkflowDraft(targetKey)
    if (!removed.ok) setDraftStorageError(removed.error, targetWorkflowId)
    else {
      setDraftStorageError(null, targetWorkflowId)
      if (activeWorkflowIdRef.current === targetWorkflowId) setDraftEdit(null)
    }
  }

  function rebaseWorkflowDraft(
    latest: WorkflowDraftEdit,
    baseRevision: number,
    targetKey: WorkflowDraftKey,
  ) {
    const rebased = { ...latest, baseRevision }
    memoryDraftsRef.current.set(latest.workflowId, rebased)
    setMemoryDraftIds([...memoryDraftsRef.current.keys()])
    const persisted = writeWorkflowDraft(
      targetKey,
      rebased.definition,
      rebased.baseRevision,
      rebased.editVersion,
    )
    setDraftStorageError(persisted.ok ? null : persisted.error, latest.workflowId)
    if (activeWorkflowIdRef.current === latest.workflowId) setDraftEdit(rebased)
  }

  async function publish() {
    if (!canEdit || hasPendingNodeEditor(workflowId)) return
    const confirmedKey = publicationKeyRef.current
    const target = { projectId: requiredId(projectId), workflowId: requiredId(workflowId) }
    const approved = await modal.confirm({
      title: '发布服务器草稿？',
      content: '发布仅使用服务器已保存的草稿。本地修改不会自动保存或包含在此次发布中。',
      okText: '发布服务器草稿',
      cancelText: '取消',
    })
    if (!approved) return
    if (publicationKeyRef.current !== confirmedKey) {
      void message.warning('工作流或权限已变化，本次发布已取消，请重新确认。')
      return
    }
    if (hasPendingNodeEditor(target.workflowId)) return
    await runMutation(message.error, async () => {
      const published = await publishMutation.mutateAsync(target)
      await queryClient.cancelQueries({
        queryKey: ['workflow', target.projectId, target.workflowId],
        exact: true,
      })
      const detail = await getWorkflow(target.projectId, target.workflowId)
      await synchronizeWorkflow(target.projectId, detail)
      await refreshWorkflows()
      void message.success(`工作流 v${published.version} 已发布`)
    })
  }

  async function execute() {
    if (!canEdit || hasPendingNodeEditor(workflowId)) return
    const target = {
      projectId: requiredId(projectId),
      workflowId: requiredId(workflowId),
      environmentId: requiredId(environmentId),
      version: requiredVersion(selectedWorkflow?.current_version),
    }
    const ticket = runtime.reserve()
    await runMutation(message.error, async () => {
      const execution = await executeMutation.mutateAsync(target)
      if (beginExecution(execution, ticket)) void message.info('工作流已开始运行')
    })
  }

  function beginExecution(execution: WorkflowExecution, ticket?: ExecutionTicket): boolean {
    if (!runtime.begin(execution, ticket)) return false
    setWorkspaceMode('run')
    setHistoryExecutionId(null)
    return true
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

  async function rerunFailedItems(executionId: string, payload: FailedItemRerunRequest) {
    const ticket = runtime.reserve()
    const execution = await rerunFailedItemsMutation.mutateAsync({ executionId, payload })
    if (beginExecution(execution, ticket)) void message.info('失败项派生运行已开始，原运行报告保留')
  }

  async function refreshWorkflows() {
    await queryClient.invalidateQueries({ queryKey: ['workflows', projectId] })
  }

  async function synchronizeWorkflow(targetProjectId: string, saved: Workflow) {
    const queryKey = ['workflow', targetProjectId, saved.id]
    await Promise.all([
      queryClient.cancelQueries({ queryKey, exact: true }),
      queryClient.cancelQueries({ queryKey: ['workflows', targetProjectId] }),
    ])
    queryClient.setQueryData<Workflow>(queryKey, saved)
    queryClient.setQueriesData<Page<Workflow>>(
      { queryKey: ['workflows', targetProjectId] },
      (page) =>
        page
          ? {
              ...page,
              items: page.items.map((item) => (item.id === saved.id ? saved : item)),
            }
          : page,
    )
  }

  function selectWorkflow(value: string | null) {
    setWorkflowSelection(value)
    setWorkflowSelectionCleared(value === null)
    setDraftEdit(null)
    draftVersionRef.current = 0
    runtime.reset()
    setWorkspaceMode('draft')
    setHistoryExecutionId(null)
  }

  function canSaveTarget(targetWorkflowId: string): boolean {
    return canEdit && !hasPendingNodeEditor(targetWorkflowId)
  }
  async function saveWorkflowDraftFor(targetWorkflowId: string): Promise<void> {
    if (!canSaveTarget(targetWorkflowId)) {
      throw new Error('工作流暂不能保存，请先处理未应用配置或编辑权限。')
    }
    if (!projectId || !userId) throw new Error('项目或登录状态已变化，页签保持打开。')
    const targetKey = workflowDraftKey(userId, projectId, targetWorkflowId)
    const memoryDraft = memoryDraftsRef.current.get(targetWorkflowId)
    const storedDraft = readWorkflowDraft(targetKey)
    const targetDraft = memoryDraft ?? restoreWorkflowEdit(storedDraft, targetWorkflowId)
    if (!targetDraft) throw new Error('本地草稿无法读取，页签保持打开。')
    if (!validForSave(targetDraft.definition)) {
      throw new Error('流程结构未完成，页签保持打开。')
    }
    const generationAtStart = draftGenerationRef.current.get(targetWorkflowId) ?? 0
    await runMutation(message.error, async () => {
      const targetWorkflow = await getWorkflow(projectId, targetWorkflowId)
      const saved = await updateWorkflowDraft(
        projectId,
        targetWorkflow,
        targetDraft.definition,
        targetDraft.baseRevision,
      )
      if (!isDraftGenerationCurrent(targetWorkflowId, generationAtStart)) return
      await synchronizeWorkflow(projectId, saved)
      if (!isDraftGenerationCurrent(targetWorkflowId, generationAtStart)) return
      const latestMemoryDraft = memoryDraftsRef.current.get(targetWorkflowId)
      if (isNewerDraft(latestMemoryDraft, targetDraft.editVersion)) {
        const rebased = { ...latestMemoryDraft, baseRevision: saved.draft_revision }
        memoryDraftsRef.current.set(targetWorkflowId, rebased)
        setMemoryDraftIds([...memoryDraftsRef.current.keys()])
        const persisted = writeWorkflowDraft(
          targetKey,
          rebased.definition,
          rebased.baseRevision,
          rebased.editVersion,
        )
        setDraftStorageError(persisted.ok ? null : persisted.error, targetWorkflowId)
        await refreshWorkflows()
        throw new Error('保存期间又产生了本地修改，页签保持打开。')
      }
      memoryDraftsRef.current.delete(targetWorkflowId)
      setMemoryDraftIds([...memoryDraftsRef.current.keys()])
      const removed = removeWorkflowDraft(targetKey)
      setDraftStorageError(removed.ok ? null : removed.error, targetWorkflowId)
      await refreshWorkflows()
      if (!removed.ok) throw new Error(`${removed.error}，页签保持打开。`)
    })
  }

  function isDraftGenerationCurrent(targetWorkflowId: string, generation: number): boolean {
    return (draftGenerationRef.current.get(targetWorkflowId) ?? 0) === generation
  }

  function discardWorkflowDraft(targetWorkflowId: string) {
    invalidateWorkflowDraft(targetWorkflowId)
    if (userId && projectId) {
      const removed = removeWorkflowDraft(workflowDraftKey(userId, projectId, targetWorkflowId))
      if (!removed.ok) {
        setDraftStorageError(removed.error, targetWorkflowId)
        return removed
      }
    }
    clearMemoryDraft(targetWorkflowId)
    setDraftStorageError(null, targetWorkflowId)
    return { ok: true } as const
  }

  function invalidateWorkflowDraft(targetWorkflowId: string) {
    draftGenerationRef.current.set(
      targetWorkflowId,
      (draftGenerationRef.current.get(targetWorkflowId) ?? 0) + 1,
    )
  }

  function clearMemoryDraft(targetWorkflowId: string) {
    const scope = nodeEditorScope(userId ?? 'anonymous', projectId ?? 'embedded', targetWorkflowId)
    for (const key of draftSession.nodeEditors.keys())
      if (key.startsWith(scope)) draftSession.clearNodeEditor(key)
    memoryDraftsRef.current.delete(targetWorkflowId)
    setMemoryDraftIds([...memoryDraftsRef.current.keys()])
    if (activeWorkflowIdRef.current === targetWorkflowId) {
      setDraftEdit(null)
      draftVersionRef.current = 0
    }
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
  const knownWorkflows = knownWorkflowItems(
    queryClient
      .getQueriesData<Page<Workflow>>({ queryKey: ['workflows', projectId] })
      .flatMap(([, page]) => page?.items ?? []),
    selectedWorkflow,
    deletedWorkflowIds,
  )

  return {
    projects,
    projectId,
    selectProject,
    environments,
    environmentId,
    environmentSelectionInvalid,
    environmentPlaceholder,
    environmentStatus,
    setEnvironmentSelection,
    apis,
    artifacts,
    workflows,
    knownWorkflows,
    workflowSearch,
    setWorkflowSearch: (value: string) => {
      setWorkflowPage(1)
      setWorkflowSearchValue(value)
    },
    workflowPage,
    setWorkflowPage,
    workflowCatalogComplete: isCompleteWorkflowCatalog(workflowSearch, workflows.data),
    deletedWorkflowIds,
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
      if (workflowId && draftKey) {
        const editVersion = draftVersionRef.current + 1
        const baseRevision = draftEdit?.baseRevision ?? selectedWorkflow?.draft_revision ?? 1
        const persisted = writeWorkflowDraft(draftKey, definition, baseRevision, editVersion)
        draftVersionRef.current = editVersion
        const edit = { workflowId, definition, baseRevision, editVersion }
        memoryDraftsRef.current.set(workflowId, edit)
        setMemoryDraftIds([...memoryDraftsRef.current.keys()])
        setDraftEdit(edit)
        setDraftStorageError(persisted.ok ? null : persisted.error)
      }
    },
    draftRestored: Boolean(draftEdit),
    draftStorageError,
    memoryDraftIds,
    nodeStatuses: workspaceView.statuses,
    activeExecutionId,
    eventHistoryIncompleteId,
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
    historyError: historyErrorText(historyExecution.error),
    reloadHistory: () => void historyExecution.refetch(),
    breakpointNodes,
    breakpointNodeId,
    setBreakpointSelection,
    debugResult,
    versionDiff,
    closeVersionDiff: () => setVersionDiff(null),
    addWorkflow,
    deleteWorkflow: removeWorkflow,
    canEdit,
    saveDraft,
    saveWorkflowDraft: saveWorkflowDraftFor,
    discardWorkflowDraft,
    publish,
    execute,
    beginIterationDebugExecution: beginExecution,
    debugToBreakpoint,
    compareLatestVersions,
    replayNode,
    rerunFailedItems,
    creating: createMutation.isPending,
    deleting: deleteMutation.isPending,
    saving: saveMutation.isPending,
    publishing: publishMutation.isPending,
    executing: executeMutation.isPending,
    debugging: debugMutation.isPending,
    comparing: diffMutation.isPending,
    replaying: replayMutation.isPending,
    rerunningFailedItems: rerunFailedItemsMutation.isPending,
  }
}

function useExecutionSelection(projectId: string | null, executionId?: string) {
  const [workspaceMode, setWorkspaceMode] = useRouteScopedState<WorkflowWorkspaceMode>(
    projectId,
    executionId ?? null,
    executionId ? 'history' : 'draft',
  )
  const [historyExecutionId, setHistoryExecutionId] = useRouteScopedSelection(
    projectId,
    executionId ?? null,
  )
  return { workspaceMode, setWorkspaceMode, historyExecutionId, setHistoryExecutionId }
}

function historyErrorText(error: Error | null): string | null {
  return error ? apiErrorMessage(error) : null
}

function useSelectedWorkflow(
  projectId: string | null,
  workflowSelection: string | null,
  workflowSelectionCleared: boolean,
  workflows: Page<Workflow> | undefined,
  preserveExplicitSelection: boolean,
  catalogComplete: boolean,
) {
  const listed = workflows?.items
  const workflowId = preserveExplicitSelection
    ? workflowSelection
    : resolveSelectedWorkflowId(
        workflowSelection,
        workflowSelectionCleared,
        workflows,
        catalogComplete,
      )
  const listedWorkflow = listed?.find((item) => item.id === workflowId) ?? null
  const workflowDetail = useQuery({
    queryKey: ['workflow', projectId, workflowId],
    queryFn: () => getWorkflow(requiredId(projectId), requiredId(workflowId)),
    initialData: listedWorkflow ?? undefined,
    enabled: Boolean(workflows) && canLoadWorkflowDetail(projectId, workflowId, listedWorkflow),
  })
  return { workflowId, selectedWorkflow: listedWorkflow ?? workflowDetail.data ?? null }
}

function resolveSelectedWorkflowId(
  selection: string | null,
  cleared: boolean,
  workflows: Page<Workflow> | undefined,
  catalogComplete: boolean,
): string | null {
  if (cleared) return null
  if (!workflows) return selection
  const listed = workflows.items
  if (selection && (!catalogComplete || listed.some((workflow) => workflow.id === selection)))
    return selection
  return listed.at(0)?.id ?? null
}

function knownWorkflowItems(
  listed: Workflow[],
  selected: Workflow | null,
  deletedIds: string[],
): Workflow[] {
  const available = new Map(listed.map((workflow) => [workflow.id, workflow]))
  if (selected) available.set(selected.id, selected)
  for (const id of deletedIds) available.delete(id)
  return [...available.values()]
}

function workflowDraftIdentity(
  userId: string | undefined,
  projectId: string | null,
  workflowId: string | null,
) {
  if (!userId || !projectId || !workflowId) return null
  return workflowDraftKey(userId, projectId, workflowId)
}

function canLoadExecutionHistory(projectId: string | null, workflowId: string | null): boolean {
  return Boolean(projectId && workflowId)
}

function canLoadHistory(
  projectId: string | null,
  historyExecutionId: string | null,
  workspaceMode: WorkflowWorkspaceMode,
): boolean {
  return Boolean(projectId && historyExecutionId && workspaceMode === 'history')
}

function canLoadWorkflowDetail(
  projectId: string | null,
  workflowId: string | null,
  listedWorkflow: Workflow | null,
): boolean {
  return Boolean(projectId && workflowId && !listedWorkflow)
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
      definition: emptyDefinition(),
      execution: null,
      nodes: [],
      children: [],
      statuses: {},
      context: {},
    }
  }
  const nodes = detail.nodes
  return {
    definition: snapshotDefinition(detail.execution.snapshot) ?? emptyDefinition(),
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
    definition: input.executionDefinition ?? emptyDefinition(),
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

function orderedLiveNodes(
  definition: WorkflowDefinition | null,
  nodes: Record<string, WorkflowNodeExecution>,
): WorkflowNodeExecution[] {
  if (!definition) return Object.values(nodes)
  return definition.nodes.flatMap((node) => (nodes[node.id] ? [nodes[node.id]] : []))
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

function isNewerDraft(
  draft: WorkflowDraftEdit | undefined,
  version: number,
): draft is WorkflowDraftEdit {
  return Boolean(draft && draft.editVersion !== version)
}

function restoreWorkflowEdit(
  stored: ReturnType<typeof readWorkflowDraft>,
  workflowId: string,
): WorkflowDraftEdit | null {
  return stored
    ? {
        workflowId,
        definition: stored.content,
        baseRevision: stored.baseRevision,
        editVersion: stored.editVersion,
      }
    : null
}

function isCompleteWorkflowCatalog(search: string, page: Page<Workflow> | undefined): boolean {
  return search === '' && Boolean(page && page.items.length === page.total)
}
