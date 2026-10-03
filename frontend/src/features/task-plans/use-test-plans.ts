import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'

import { apiErrorMessage } from '../../lib/api'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'
import { useProjectCapabilities } from '../projects/use-project-capabilities'
import { useProjectContext } from '../projects/use-project-context'
import {
  cancelTestPlanRun,
  createServiceToken,
  createTestPlan,
  listServiceTokens,
  listTaskEnvironments,
  listTaskTestCases,
  listTaskTestSuites,
  listTaskWorkflows,
  listTestPlanRuns,
  listTestPlans,
  runTestPlan,
  type CreateTestPlanInput,
} from './task-plan-service'

export function useTestPlans() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { projects, projectId, selectProject } = useProjectContext()
  const { canEdit, canManageTokens, permissions } = useProjectCapabilities()
  const [createOpen, setCreateOpen] = useRouteScopedState(projectId, null, false)
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
    mutationFn: ({ project, input }: { project: string; input: CreateTestPlanInput }) =>
      createTestPlan(project, input),
  })
  const runPlan = useMutation({
    mutationFn: ({ project, id }: { project: string; id: string }) => runTestPlan(project, id),
  })
  const cancelRun = useMutation({
    mutationFn: ({ project, id }: { project: string; id: string }) =>
      cancelTestPlanRun(project, id),
  })
  const createToken = useMutation({
    mutationFn: (project: string) => createServiceToken(project),
  })

  async function addPlan(input: CreateTestPlanInput) {
    if (!projectId || !canEdit) return
    try {
      const created = await createPlan.mutateAsync({ project: projectId, input })
      setCreateOpen(false)
      setRevealedSecret({ title: 'Webhook Secret（仅显示一次）', value: created.webhook_secret })
      await refresh('test-plans')
      void message.success('测试计划已创建')
    } catch (error) {
      void message.error(apiErrorMessage(error))
    }
  }

  async function execute(planId: string) {
    if (!projectId || !canEdit) return
    try {
      await runPlan.mutateAsync({ project: projectId, id: planId })
      await refresh('test-plan-runs')
      void message.success('测试计划已进入队列')
    } catch (error) {
      void message.error(apiErrorMessage(error))
    }
  }

  async function cancel(runId: string) {
    if (!projectId || !canEdit) return
    try {
      await cancelRun.mutateAsync({ project: projectId, id: runId })
      await refresh('test-plan-runs')
      void message.success('已请求取消')
    } catch (error) {
      void message.error(apiErrorMessage(error))
    }
  }

  async function issueToken() {
    if (!projectId || !canManageTokens) return
    try {
      const created = await createToken.mutateAsync(projectId)
      setRevealedSecret({ title: 'CI Token（仅显示一次）', value: created.token })
      await refresh('service-tokens')
    } catch (error) {
      void message.error(apiErrorMessage(error))
    }
  }

  async function refresh(resource: string) {
    await queryClient.invalidateQueries({ queryKey: [resource, projectId] })
  }

  return {
    projects,
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
