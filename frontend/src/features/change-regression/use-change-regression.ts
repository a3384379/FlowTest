import { useCatalogQuery } from '../../lib/catalog-query'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'

import { apiErrorWithTrace } from '../../lib/api'
import { getV3FeatureFlags } from '../capabilities/capability-service'
import { getImpactCatalog } from '../impact/impact-service'
import { useContext, useLayoutEffect, useMemo, useRef } from 'react'
import { UNSAFE_DataRouterContext, useLocation, useSearchParams } from 'react-router-dom'
import { useProjectContext } from '../projects/use-project-context'
import { useProjectCapabilities } from '../projects/use-project-capabilities'
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
  selectChangeRegressionOperation,
  waiveSemanticGap,
  type ChangeRegressionInput,
  type MissingTestProposal,
} from './change-regression-service'

export function useChangeRegression(initialRunId?: string, loadSources = false) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { projectId } = useProjectContext()
  const { canEdit, permissions, flags, sourceCatalog } = useRegressionAccess(projectId, loadSources)
  const [params, setParams] = useSearchParams()
  const selectedRunId = params.get('run') ?? initialRunId ?? null
  const isCurrent = useRegressionCommandContext(projectId)
  function setSelectedRunId(value: string | null) {
    setParams((current) => {
      const next = new URLSearchParams(current)
      if (value) next.set('run', value)
      else next.delete('run')
      next.delete('sources')
      return next
    })
  }
  const enabled = Boolean(projectId)
  const runs = useCatalogQuery(
    'change-regressions',
    projectId,
    (page) => listChangeRegressions(required(projectId), page, 20),
    enabled,
    '',
    { refetchInterval: 3000 },
  )
  const plans = useCatalogQuery(
    'change-regression-plans',
    projectId,
    (page) => listChangeRegressionPlans(required(projectId), page, 20),
    enabled,
    '',
    {},
  )
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
    mutationFn: (input: { projectId: string; definition: ChangeRegressionInput }) =>
      createChangeRegression(input.projectId, input.definition),
  })
  const review = useMutation({
    mutationFn: (input: {
      projectId: string
      runId: string
      itemId: string
      decision: 'accept' | 'reject'
      expectedContent?: MissingTestProposal['proposed_content']
    }) =>
      reviewMissingTest(
        input.projectId,
        input.runId,
        input.itemId,
        input.decision,
        '前端人工审核',
        input.expectedContent,
      ),
  })
  const approve = useMutation({
    mutationFn: (input: { projectId: string; runId: string }) =>
      approveChangeRegression(input.projectId, input.runId, '前端人工批准'),
  })
  const execute = useMutation({
    mutationFn: (input: { projectId: string; runId: string }) =>
      executeChangeRegression(input.projectId, input.runId),
  })
  const release = useMutation({
    mutationFn: (input: { projectId: string; runId: string }) =>
      evaluateChangeRegressionRelease(input.projectId, input.runId),
  })
  const addToPlan = useMutation({
    mutationFn: (input: {
      projectId: string
      runId: string
      gapKey: string
      targetType: 'workflow' | 'test_case'
      targetId: string
      targetVersion: number
      workflowVersion: number
      environmentId?: string
    }) =>
      addProjectKnownTestToCurrentPlan(input.projectId, input.runId, {
        gap_key: input.gapKey,
        item: planItemInput(input),
      }),
  })
  const waive = useMutation({
    mutationFn: (input: {
      projectId: string
      runId: string
      gapKey: string
      reason: string
      expiresAt?: string
    }) => waiveSemanticGap(input.projectId, input.runId, waiverInput(input)),
  })
  const selectOperation = useMutation({
    mutationFn: (input: {
      projectId: string
      runId: string
      changeKey: string
      apiDefinitionId: string
      apiVersion: number
    }) =>
      selectChangeRegressionOperation(input.projectId, input.runId, {
        change_key: input.changeKey,
        api_definition_id: input.apiDefinitionId,
        api_version: input.apiVersion,
      }),
  })

  async function refresh(targetProjectId: string) {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['change-regressions', targetProjectId] }),
      queryClient.invalidateQueries({ queryKey: ['change-regression', targetProjectId] }),
    ])
  }

  async function createRun(input: ChangeRegressionInput): Promise<boolean> {
    if (!canEdit || !isCurrent()) return false
    try {
      const created = await create.mutateAsync({
        projectId: required(projectId),
        definition: input,
      })
      await refresh(required(projectId))
      if (!isCurrent()) return false
      setSelectedRunId(created.id)
      void message.success('变更回归链路已创建，等待审核')
      return true
    } catch (error) {
      if (isCurrent()) void message.error(apiErrorWithTrace(error))
      return false
    }
  }

  async function reviewItem(input: {
    runId: string
    itemId: string
    decision: 'accept' | 'reject'
    expectedContent?: MissingTestProposal['proposed_content']
  }): Promise<boolean> {
    if (!canEdit || !isCurrent()) return false
    try {
      await review.mutateAsync({ ...input, projectId: required(projectId) })
      await refresh(required(projectId))
      if (!isCurrent()) return false
      void message.success(input.decision === 'accept' ? '缺失测试已接受' : '缺失测试已拒绝')
      return true
    } catch (error) {
      if (isCurrent()) void message.error(apiErrorWithTrace(error))
      return false
    }
  }

  async function runAction(action: () => Promise<unknown>, success: string): Promise<boolean> {
    if (!canEdit || !isCurrent()) return false
    try {
      await action()
      await refresh(required(projectId))
      if (!isCurrent()) return false
      void message.success(success)
      return true
    } catch (error) {
      if (isCurrent()) void message.error(apiErrorWithTrace(error))
      return false
    }
  }

  return {
    projectId,
    flags,
    sourceCatalog,
    canEdit,
    permissions,
    runs,
    plans,
    policies,
    detail,
    selectedRunId: effectiveRunId,
    setSelectedRunId,
    createRun,
    reviewItem,
    approve: (runId: string) =>
      runAction(
        () => approve.mutateAsync({ projectId: required(projectId), runId }),
        '变更回归已批准',
      ),
    execute: (runId: string) =>
      runAction(
        () => execute.mutateAsync({ projectId: required(projectId), runId }),
        '回归执行已入队',
      ),
    evaluateRelease: (runId: string) =>
      runAction(
        () => release.mutateAsync({ projectId: required(projectId), runId }),
        'Release Gate 已评估',
      ),
    addToPlan: (input: {
      runId: string
      gapKey: string
      targetType: 'workflow' | 'test_case'
      targetId: string
      targetVersion: number
      workflowVersion: number
      environmentId?: string
    }) =>
      runAction(
        () => addToPlan.mutateAsync({ ...input, projectId: required(projectId) }),
        '当前计划的固定测试版本已更新',
      ),
    waiveGap: (input: { runId: string; gapKey: string; reason: string; expiresAt?: string }) =>
      runAction(
        () => waive.mutateAsync({ ...input, projectId: required(projectId) }),
        '语义缺口已记录人工豁免',
      ),
    selectOperation: (input: {
      runId: string
      changeKey: string
      apiDefinitionId: string
      apiVersion: number
    }) =>
      runAction(
        () => selectOperation.mutateAsync({ ...input, projectId: required(projectId) }),
        'Operation 已冻结，Proposal 已重新生成',
      ),
    creating: create.isPending,
    acting: mutationPending(review, approve, execute, release, addToPlan, waive, selectOperation),
  }
}

function useRegressionAccess(projectId: string | null, loadSources: boolean) {
  const { canEdit: editAllowed, permissions } = useProjectCapabilities()
  const flags = useQuery({
    queryKey: ['v3-feature-flags'],
    queryFn: getV3FeatureFlags,
    enabled: Boolean(projectId),
  })
  const enabledImpact = flags.isSuccess && flags.data?.impact_engine === true
  const canEdit = editAllowed && permissions.isSuccess && enabledImpact
  const sourceCatalog = useQuery({
    queryKey: ['impact-catalog', projectId],
    queryFn: () => getImpactCatalog(required(projectId)),
    enabled: Boolean(projectId && canEdit && loadSources),
  })
  return { canEdit, permissions, flags, sourceCatalog }
}

function required(value: string | null): string {
  if (!value) throw new Error('请选择项目')
  return value
}

function planItemInput(input: {
  targetType: 'workflow' | 'test_case'
  targetId: string
  targetVersion: number
  workflowVersion: number
  environmentId?: string
}) {
  if (input.targetType === 'test_case') {
    return {
      target_type: 'case' as const,
      target_id: input.targetId,
      target_version: input.targetVersion,
    }
  }
  return {
    target_type: 'workflow' as const,
    target_id: input.targetId,
    target_version: input.targetVersion,
    workflow_version: input.workflowVersion,
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

function useRegressionCommandContext(projectId: string | null) {
  const location = useLocation()
  const router = useContext(UNSAFE_DataRouterContext)
  const context = useMemo(() => ({ projectId, key: location.key }), [projectId, location.key])
  const active = useRef<typeof context | null>(context)
  useLayoutEffect(() => {
    active.current = context
    return () => {
      active.current = null
    }
  }, [context])
  return () =>
    active.current === context && (!router || router.router.state.location.key === location.key)
}
