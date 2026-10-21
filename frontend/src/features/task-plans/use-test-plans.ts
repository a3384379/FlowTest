import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useContext, useLayoutEffect, useMemo, useRef } from 'react'
import { UNSAFE_DataRouterContext, useLocation, useSearchParams } from 'react-router-dom'

import { apiErrorMessage, type TestPlan } from '../../lib/api'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'
import { useProjectCapabilities } from '../projects/use-project-capabilities'
import { useProjectContext } from '../projects/use-project-context'
import {
  cancelTestPlanRun,
  createServiceToken,
  createTestPlan,
  getTestPlan,
  listServiceTokens,
  listTaskEnvironments,
  listTaskTestCases,
  listTaskTestSuites,
  listTaskWorkflows,
  listTestPlanRuns,
  listTestPlans,
  runTestPlan,
  updateTestPlan,
  revokeServiceToken,
  type UpdateTestPlanInput,
  type CreateTestPlanInput,
} from './task-plan-service'

export function useTestPlans() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { projects, projectId, selectProject } = useProjectContext()
  const {
    canEdit: editPermission,
    canManageTokens: tokenPermission,
    permissions,
  } = useProjectCapabilities()
  const canEdit = editPermission && permissions.isSuccess
  const canManageTokens = tokenPermission && permissions.isSuccess
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()
  const dataRouter = useContext(UNSAFE_DataRouterContext)
  const focusedId = searchParams.get('focus')
  const selectedRunId = searchParams.get('run')
  const context = useMemo(
    () => ({ projectId, focusedId, selectedRunId }),
    [projectId, focusedId, selectedRunId],
  )
  const activeContext = useRef<typeof context | null>(context)
  useLayoutEffect(() => {
    activeContext.current = context
    return () => {
      activeContext.current = null
    }
  }, [context])
  const isCurrent = () =>
    activeContext.current === context &&
    (!dataRouter || dataRouter.router.state.location.key === location.key)
  function setSelectedRunId(id: string | null) {
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      if (id) next.set('run', id)
      else next.delete('run')
      return next
    })
  }
  function setFocusedId(id: string | null) {
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      if (id) next.set('focus', id)
      else next.delete('focus')
      return next
    })
  }
  const focusedPlan = useQuery({
    queryKey: ['test-plan', projectId, focusedId, selectedRunId],
    queryFn: () => getTestPlan(required(projectId), required(focusedId)),
    enabled: Boolean(projectId && focusedId),
  })
  const [createOpen, setCreateOpen] = useRouteScopedState(projectId, null, false)
  const [editingPlan, setEditingPlan] = useRouteScopedState<TestPlan | null>(projectId, null, null)
  const [planPage, setPlanPage] = useRouteScopedState(projectId, null, 1)
  const [runPage, setRunPage] = useRouteScopedState(projectId, null, 1)
  const [revealedSecret, setRevealedSecret] = useRouteScopedState<{
    title: string
    value: string
  } | null>(projectId, null, null)
  const workflows = useQuery({
    queryKey: ['task-workflows', projectId],
    queryFn: () => listTaskWorkflows(required(projectId)),
    enabled: Boolean(projectId),
  })
  const environments = useQuery({
    queryKey: ['task-environments', projectId],
    queryFn: () => listTaskEnvironments(required(projectId)),
    enabled: Boolean(projectId),
  })
  const testCases = useQuery({
    queryKey: ['task-test-cases', projectId],
    queryFn: () => listTaskTestCases(required(projectId)),
    enabled: Boolean(projectId),
  })
  const testSuites = useQuery({
    queryKey: ['task-test-suites', projectId],
    queryFn: () => listTaskTestSuites(required(projectId)),
    enabled: Boolean(projectId),
  })
  const plans = useQuery({
    queryKey: ['test-plans', projectId, planPage],
    queryFn: () => listTestPlans(required(projectId), planPage, 20),
    enabled: Boolean(projectId),
  })
  const runs = useQuery({
    queryKey: ['test-plan-runs', projectId, runPage],
    queryFn: () => listTestPlanRuns(required(projectId), runPage),
    enabled: Boolean(projectId),
    refetchInterval: (query) =>
      query.state.data?.items.some((run) => ['queued', 'running'].includes(run.status))
        ? 1000
        : false,
  })
  const tokens = useQuery({
    queryKey: ['service-tokens', projectId],
    queryFn: () => listServiceTokens(required(projectId)),
    enabled: Boolean(projectId && canManageTokens),
  })
  const createPlan = useMutation({
    mutationKey: ['task-createPlan', projectId, focusedId, selectedRunId],
    mutationFn: ({ project, input }: { project: string; input: CreateTestPlanInput }) =>
      createTestPlan(project, input),
  })
  const runPlan = useMutation({
    mutationKey: ['task-runPlan', projectId, focusedId, selectedRunId],
    mutationFn: ({ project, id }: { project: string; id: string }) => runTestPlan(project, id),
  })
  const cancelRun = useMutation({
    mutationKey: ['task-cancelRun', projectId, focusedId, selectedRunId],
    mutationFn: ({ project, id }: { project: string; id: string }) =>
      cancelTestPlanRun(project, id),
  })
  const createToken = useMutation({
    mutationKey: ['task-createToken', projectId, focusedId, selectedRunId],
    mutationFn: (project: string) => createServiceToken(project),
  })
  const updatePlan = useMutation({
    mutationKey: ['task-updatePlan', projectId, focusedId, selectedRunId],
    mutationFn: ({
      project,
      id,
      input,
    }: {
      project: string
      id: string
      input: Partial<UpdateTestPlanInput>
    }) => updateTestPlan(project, id, input),
  })
  const revokeToken = useMutation({
    mutationKey: ['task-revokeToken', projectId, focusedId, selectedRunId],
    mutationFn: ({ project, id }: { project: string; id: string }) =>
      revokeServiceToken(project, id),
  })

  async function editPlan(input: UpdateTestPlanInput) {
    if (!projectId || !canEdit || !editingPlan) return
    try {
      await updatePlan.mutateAsync({ project: projectId, id: editingPlan.id, input })
      if (!isCurrent()) return
      setEditingPlan(null)
      await refresh('test-plans')
      if (!isCurrent()) return
      void message.success('测试计划已更新')
    } catch (error) {
      if (!isCurrent()) return
      void message.error(apiErrorMessage(error))
    }
  }

  async function togglePlan(plan: TestPlan) {
    if (!projectId || !canEdit) return
    try {
      await updatePlan.mutateAsync({
        project: projectId,
        id: plan.id,
        input: { enabled: !plan.enabled },
      })
      await refresh('test-plans')
    } catch (error) {
      if (!isCurrent()) return
      void message.error(apiErrorMessage(error))
    }
  }

  async function revoke(tokenId: string) {
    if (!projectId || !canManageTokens) return
    try {
      await revokeToken.mutateAsync({ project: projectId, id: tokenId })
      await refresh('service-tokens')
      if (!isCurrent()) return
      void message.success('CI Token 已撤销')
    } catch (error) {
      if (!isCurrent()) return
      void message.error(apiErrorMessage(error))
    }
  }

  async function addPlan(input: CreateTestPlanInput) {
    if (!projectId || !canEdit) return
    try {
      const created = await createPlan.mutateAsync({ project: projectId, input })
      if (!isCurrent()) return
      setCreateOpen(false)
      setRevealedSecret({ title: 'Webhook Secret（仅显示一次）', value: created.webhook_secret })
      await refresh('test-plans')
      if (!isCurrent()) return
      void message.success('测试计划已创建')
    } catch (error) {
      if (!isCurrent()) return
      void message.error(apiErrorMessage(error))
    }
  }

  async function execute(planId: string) {
    if (!projectId || !canEdit) return
    try {
      const run = await runPlan.mutateAsync({ project: projectId, id: planId })
      await refresh('test-plan-runs')
      if (!isCurrent()) return
      setSearchParams((current) => {
        const next = new URLSearchParams(current)
        next.set('focus', planId)
        next.set('run', run.id)
        return next
      })
      void message.success('测试计划已进入队列')
    } catch (error) {
      if (!isCurrent()) return
      void message.error(apiErrorMessage(error))
    }
  }

  async function cancel(runId: string) {
    if (!projectId || !canEdit) return
    try {
      await cancelRun.mutateAsync({ project: projectId, id: runId })
      await refresh('test-plan-runs')
      if (!isCurrent()) return
      void message.success('已请求取消')
    } catch (error) {
      if (!isCurrent()) return
      void message.error(apiErrorMessage(error))
    }
  }

  async function issueToken() {
    if (!projectId || !canManageTokens) return
    try {
      const created = await createToken.mutateAsync(projectId)
      if (!isCurrent()) return
      setRevealedSecret({ title: 'CI Token（仅显示一次）', value: created.token })
      await refresh('service-tokens')
    } catch (error) {
      if (!isCurrent()) return
      void message.error(apiErrorMessage(error))
    }
  }

  async function refresh(resource: string) {
    await queryClient.invalidateQueries({ queryKey: [resource, projectId] })
    if (resource === 'test-plans')
      await queryClient.invalidateQueries({ queryKey: ['test-plan', projectId] })
  }

  return {
    projects,
    focusedId,
    focusedPlan,
    setFocusedId,
    createError: createPlan.error,
    clearCreateError: () => createPlan.reset(),
    running: runPlan.isPending,
    editingPlan,
    setEditingPlan,
    editPlan,
    togglePlan,
    updatingPlan: updatePlan.isPending,
    revoke,
    revokingToken: revokeToken.isPending,
    selectedRunId,
    setSelectedRunId,
    projectId,
    canEdit,
    canManageTokens,
    permissions,
    setProjectSelection: selectProject,
    workflows,
    environments,
    testCases,
    testSuites,
    plans,
    planPage,
    setPlanPage,
    runs,
    runPage,
    setRunPage,
    tokens,
    createOpen,
    setCreateOpen,
    revealedSecret,
    dismissSecret: () => setRevealedSecret(null),
    addPlan,
    execute,
    cancel,
    issueToken,
    creating: createPlan.isPending,
  }
}

function required(value: string | null): string {
  if (!value) throw new Error('请选择项目')
  return value
}
