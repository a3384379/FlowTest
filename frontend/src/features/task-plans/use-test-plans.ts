import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useState } from 'react'

import { apiErrorMessage } from '../../lib/api'
import {
  cancelTestPlanRun,
  createServiceToken,
  createTestPlan,
  listServiceTokens,
  listTaskEnvironments,
  listTaskProjects,
  listTaskWorkflows,
  listTestPlanRuns,
  listTestPlans,
  runTestPlan,
  type CreateTestPlanInput,
} from './task-plan-service'

export function useTestPlans() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [projectSelection, setProjectSelection] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [revealedSecret, setRevealedSecret] = useState<{
    title: string
    value: string
  } | null>(null)
  const projects = useQuery({ queryKey: ['projects'], queryFn: listTaskProjects })
  const projectId = projectSelection ?? projects.data?.items.at(0)?.id ?? null
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
  const plans = useQuery({
    queryKey: ['test-plans', projectId],
    queryFn: () => listTestPlans(required(projectId)),
    enabled: Boolean(projectId),
  })
  const runs = useQuery({
    queryKey: ['test-plan-runs', projectId],
    queryFn: () => listTestPlanRuns(required(projectId)),
    enabled: Boolean(projectId),
    refetchInterval: (query) =>
      query.state.data?.items.some((run) => ['queued', 'running'].includes(run.status))
        ? 1000
        : false,
  })
  const tokens = useQuery({
    queryKey: ['service-tokens', projectId],
    queryFn: () => listServiceTokens(required(projectId)),
    enabled: Boolean(projectId),
  })
  const createPlan = useMutation({
    mutationFn: (input: CreateTestPlanInput) => createTestPlan(required(projectId), input),
  })
  const runPlan = useMutation({
    mutationFn: (planId: string) => runTestPlan(required(projectId), planId),
  })
  const cancelRun = useMutation({
    mutationFn: (runId: string) => cancelTestPlanRun(required(projectId), runId),
  })
  const createToken = useMutation({
    mutationFn: () => createServiceToken(required(projectId)),
  })

  async function addPlan(input: CreateTestPlanInput) {
    try {
      const created = await createPlan.mutateAsync(input)
      setCreateOpen(false)
      setRevealedSecret({ title: 'Webhook Secret（仅显示一次）', value: created.webhook_secret })
      await refresh('test-plans')
      void message.success('测试计划已创建')
    } catch (error) {
      void message.error(apiErrorMessage(error))
    }
  }

  async function execute(planId: string) {
    try {
      await runPlan.mutateAsync(planId)
      await refresh('test-plan-runs')
      void message.success('测试计划已进入队列')
    } catch (error) {
      void message.error(apiErrorMessage(error))
    }
  }

  async function cancel(runId: string) {
    try {
      await cancelRun.mutateAsync(runId)
      await refresh('test-plan-runs')
      void message.success('已请求取消')
    } catch (error) {
      void message.error(apiErrorMessage(error))
    }
  }

  async function issueToken() {
    try {
      const created = await createToken.mutateAsync()
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
    setProjectSelection,
    workflows,
    environments,
    plans,
    runs,
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
