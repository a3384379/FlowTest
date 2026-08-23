import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useState } from 'react'

import { apiErrorMessage } from '../../lib/api'
import { useProjectContext } from '../projects/use-project-context'
import {
  addProjectKnownTestToCurrentPlan,
  approveChangeRegression,
  createChangeRegression,
  evaluateChangeRegressionRelease,
  executeChangeRegression,
  getChangeRegression,
  listChangeRegressionPlans,
  listChangeRegressionPolicies,
  listChangeRegressions,
  reviewMissingTest,
  waiveSemanticGap,
  type ChangeRegressionInput,
} from './change-regression-service'

export function useChangeRegression() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { projectId } = useProjectContext()
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const enabled = Boolean(projectId)
  const runs = useQuery({
    queryKey: ['change-regressions', projectId],
    queryFn: () => listChangeRegressions(required(projectId)),
    enabled,
    refetchInterval: 3000,
  })
  const plans = useQuery({
    queryKey: ['change-regression-plans', projectId],
    queryFn: () => listChangeRegressionPlans(required(projectId)),
    enabled,
  })
  const policies = useQuery({
    queryKey: ['change-regression-policies', projectId],
    queryFn: () => listChangeRegressionPolicies(required(projectId)),
    enabled,
  })
  const effectiveRunId = selectedRunId ?? runs.data?.items[0]?.id ?? null
  const detail = useQuery({
    queryKey: ['change-regression', projectId, effectiveRunId],
    queryFn: () => getChangeRegression(required(projectId), required(effectiveRunId)),
    enabled: enabled && Boolean(effectiveRunId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && ['queued', 'running'].includes(status) ? 1500 : false
    },
  })
  const create = useMutation({
    mutationFn: (input: ChangeRegressionInput) =>
      createChangeRegression(required(projectId), input),
  })
  const review = useMutation({
    mutationFn: (input: { runId: string; itemId: string; decision: 'accept' | 'reject' }) =>
      reviewMissingTest(
        required(projectId),
        input.runId,
        input.itemId,
        input.decision,
        '前端人工审核',
      ),
  })
  const approve = useMutation({
    mutationFn: (runId: string) =>
      approveChangeRegression(required(projectId), runId, '前端人工批准'),
  })
  const execute = useMutation({
    mutationFn: (runId: string) => executeChangeRegression(required(projectId), runId),
  })
  const release = useMutation({
    mutationFn: (runId: string) => evaluateChangeRegressionRelease(required(projectId), runId),
  })
  const addToPlan = useMutation({
    mutationFn: (input: {
      runId: string
      gapKey: string
      targetType: 'workflow' | 'test_case'
      targetId: string
      environmentId?: string
    }) =>
      addProjectKnownTestToCurrentPlan(required(projectId), input.runId, {
        gap_key: input.gapKey,
        item: planItemInput(input),
      }),
  })
  const waive = useMutation({
    mutationFn: (input: { runId: string; gapKey: string; reason: string; expiresAt?: string }) =>
      waiveSemanticGap(required(projectId), input.runId, waiverInput(input)),
  })

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['change-regressions', projectId] }),
      queryClient.invalidateQueries({ queryKey: ['change-regression', projectId] }),
    ])
  }

  async function createRun(input: ChangeRegressionInput): Promise<boolean> {
    try {
      const created = await create.mutateAsync(input)
      setSelectedRunId(created.id)
      await refresh()
      void message.success('变更回归链路已创建，等待审核')
      return true
    } catch (error) {
      void message.error(apiErrorMessage(error))
      return false
    }
  }

  async function reviewItem(input: {
    runId: string
    itemId: string
    decision: 'accept' | 'reject'
  }): Promise<boolean> {
    try {
      await review.mutateAsync(input)
      await refresh()
      void message.success(input.decision === 'accept' ? '缺失测试已接受' : '缺失测试已拒绝')
      return true
    } catch (error) {
      void message.error(apiErrorMessage(error))
      return false
    }
  }

  async function runAction(action: () => Promise<unknown>, success: string): Promise<boolean> {
    try {
      await action()
      await refresh()
      void message.success(success)
      return true
    } catch (error) {
      void message.error(apiErrorMessage(error))
      return false
    }
  }

  return {
    projectId,
    runs,
    plans,
    policies,
    detail,
    selectedRunId: effectiveRunId,
    setSelectedRunId,
    createRun,
    reviewItem,
    approve: (runId: string) => runAction(() => approve.mutateAsync(runId), '变更回归已批准'),
    execute: (runId: string) => runAction(() => execute.mutateAsync(runId), '回归执行已入队'),
    evaluateRelease: (runId: string) =>
      runAction(() => release.mutateAsync(runId), 'Release Gate 已评估'),
    addToPlan: (input: {
      runId: string
      gapKey: string
      targetType: 'workflow' | 'test_case'
      targetId: string
      environmentId?: string
    }) => runAction(() => addToPlan.mutateAsync(input), '已有测试已加入当前计划'),
    waiveGap: (input: { runId: string; gapKey: string; reason: string; expiresAt?: string }) =>
      runAction(() => waive.mutateAsync(input), '语义缺口已记录人工豁免'),
    creating: create.isPending,
    acting: mutationPending(review, approve, execute, release, addToPlan, waive),
  }
}

function required(value: string | null): string {
  if (!value) throw new Error('请选择项目')
  return value
}

function planItemInput(input: {
  targetType: 'workflow' | 'test_case'
  targetId: string
  environmentId?: string
}) {
  if (input.targetType === 'test_case') {
    return { target_type: 'case' as const, target_id: input.targetId }
  }
  return {
    target_type: 'workflow' as const,
    target_id: input.targetId,
    environment_id: input.environmentId,
  }
}

function waiverInput(input: { gapKey: string; reason: string; expiresAt?: string }) {
  if (input.expiresAt) {
    return { gap_key: input.gapKey, reason: input.reason, expires_at: input.expiresAt }
  }
  return { gap_key: input.gapKey, reason: input.reason }
}

function mutationPending(...mutations: Array<{ isPending: boolean }>): boolean {
  return mutations.some((mutation) => mutation.isPending)
}
