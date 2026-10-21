import { useCatalogQuery } from '../../lib/catalog-query'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { UNSAFE_DataRouterContext, useLocation, useSearchParams } from 'react-router-dom'
import { useContext, useLayoutEffect, useMemo, useRef } from 'react'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'

import { getV3FeatureFlags, type V3FeatureFlags } from '../capabilities/capability-service'
import { listDeploymentChecks } from '../contracts/contract-hub-service'
import { listImpactRuns } from '../impact/impact-service'
import { listPerformanceRuns } from '../performance/performance-service'
import { useProjectContext } from '../projects/use-project-context'
import { useProjectCapabilities } from '../projects/use-project-capabilities'
import { listQualityGates, listQualityRuns, listReleaseRisks } from '../quality/quality-service'
import { apiErrorWithTrace } from '../../lib/api'
import {
  createReleaseDecision,
  createReleasePolicy,
  getReleaseDecision,
  listReleaseDecisions,
  listReleasePolicies,
  listReleaseRunnerEvidence,
  type ReleaseDecisionInput,
  type ReleasePolicyInput,
} from './release-gate-service'

export function useReleaseGate(loadEvidence = false) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { projectId } = useProjectContext()
  const access = useProjectCapabilities()
  const canEdit = access.canEdit && access.permissions.isSuccess
  const isCurrent = useReleaseCommandContext(projectId)
  const [performanceSearch, setPerformanceSearch] = useRouteScopedState(
    projectId,
    'performance-evidence',
    '',
  )
  const [runnerSearch, setRunnerSearch] = useRouteScopedState(projectId, 'runner-evidence', '')
  const [params, setParams] = useSearchParams()
  const decisionId = params.get('decision')
  const enabled = Boolean(projectId)
  const readEvidence = enabled && loadEvidence
  const featureFlags = useQuery({
    queryKey: ['v3-feature-flags'],
    queryFn: getV3FeatureFlags,
    enabled,
  })
  const policies = useQuery({
    queryKey: ['release-policies', projectId],
    queryFn: () => listReleasePolicies(required(projectId)),
    enabled,
  })
  const latestDecision = useQuery({
    queryKey: ['release-latest-decision', projectId],
    queryFn: () => listReleaseDecisions(required(projectId), 1, 1),
    enabled,
  })
  const decisions = useCatalogQuery(
    'release-decisions',
    projectId,
    (page) => listReleaseDecisions(required(projectId), page, 20),
    enabled,
    '',
    {},
  )
  const selectedDecision = useQuery({
    queryKey: ['release-decision', projectId, decisionId],
    queryFn: () => getReleaseDecision(required(projectId), required(decisionId)),
    enabled: Boolean(projectId && decisionId),
  })

  function selectDecision(id: string | null) {
    setParams((current) => {
      const next = new URLSearchParams(current)
      if (id) next.set('decision', id)
      else next.delete('decision')
      next.delete('source')
      return next
    })
  }
  const qualityGates = useQuery({
    queryKey: ['quality-gates', projectId],
    queryFn: () => listQualityGates(required(projectId)),
    enabled,
  })
  const qualityRuns = useCatalogQuery(
    'quality-runs',
    projectId,
    (page) => listQualityRuns(required(projectId), page, 20),
    readEvidence,
    '',
    {},
  )
  const deploymentChecks = useCatalogQuery(
    'deployment-checks',
    projectId,
    (page) => listDeploymentChecks(required(projectId), page, 20),
    readEvidence && v3FeatureEnabled(featureFlags, 'contract_hub'),
    '',
    {},
  )
  const impactRuns = useCatalogQuery(
    'impact-runs',
    projectId,
    (page) => listImpactRuns(required(projectId), page, 20),
    readEvidence && v3FeatureEnabled(featureFlags, 'impact_engine'),
    '',
    {},
  )
  const releaseRisks = useCatalogQuery(
    'release-risks',
    projectId,
    (page) => listReleaseRisks(required(projectId), page, 20),
    readEvidence && v3FeatureEnabled(featureFlags, 'quality_intelligence'),
    '',
    {},
  )
  const performanceRuns = useCatalogQuery(
    'release-performance-runs',
    projectId,
    (page) => listPerformanceRuns(required(projectId), page, 20, performanceSearch),
    readEvidence && v3FeatureEnabled(featureFlags, 'performance_lab'),
    performanceSearch,
    {},
  )
  const runnerTasks = useCatalogQuery(
    'release-runner-tasks',
    projectId,
    (page) => listReleaseRunnerEvidence(required(projectId), page, runnerSearch),
    readEvidence && v3FeatureEnabled(featureFlags, 'runner_fabric'),
    runnerSearch,
    {},
  )
  const createPolicy = useMutation({
    mutationFn: (input: { projectId: string; definition: ReleasePolicyInput }) =>
      createReleasePolicy(input.projectId, input.definition),
  })
  const createDecision = useMutation({
    mutationFn: (input: { projectId: string; definition: ReleaseDecisionInput }) =>
      createReleaseDecision(input.projectId, input.definition),
  })

  async function addPolicy(input: ReleasePolicyInput): Promise<boolean> {
    if (!canEdit || !isCurrent()) return false
    try {
      await createPolicy.mutateAsync({ projectId: required(projectId), definition: input })
      await queryClient.invalidateQueries({ queryKey: ['release-policies', projectId] })
      if (!isCurrent()) return false
      void message.success('发布策略已创建')
      return true
    } catch (error) {
      if (isCurrent()) void message.error(apiErrorWithTrace(error))
      return false
    }
  }

  async function evaluate(input: ReleaseDecisionInput): Promise<boolean> {
    if (!canEdit || !isCurrent()) return false
    try {
      const decision = await createDecision.mutateAsync({
        projectId: required(projectId),
        definition: input,
      })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['release-decisions', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['release-latest-decision', projectId] }),
      ])
      if (!isCurrent()) return false
      selectDecision(decision.id)
      void message.success(decision.status === 'pass' ? '发布判断：PASS' : '发布判断：BLOCK')
      return true
    } catch (error) {
      if (isCurrent()) void message.error(apiErrorWithTrace(error))
      return false
    }
  }

  return {
    canEdit,
    featureFlags,
    performanceSearch,
    setPerformanceSearch,
    runnerSearch,
    setRunnerSearch,
    decisionId,
    selectedDecision,
    selectDecision,
    projectId,
    policies,
    decisions,
    latestDecision,
    qualityGates,
    qualityRuns,
    deploymentChecks,
    impactRuns,
    releaseRisks,
    performanceRuns,
    runnerTasks,
    addPolicy,
    evaluate,
    creatingPolicy: createPolicy.isPending,
    evaluating: createDecision.isPending,
  }
}

function required(value: string | null): string {
  if (!value) throw new Error('请选择项目')
  return value
}

function v3FeatureEnabled(
  flags: { isSuccess: boolean; data?: V3FeatureFlags },
  feature: keyof V3FeatureFlags,
): boolean {
  return flags.isSuccess && flags.data?.[feature] === true
}

function useReleaseCommandContext(projectId: string | null) {
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
