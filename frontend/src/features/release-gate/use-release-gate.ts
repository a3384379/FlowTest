import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'

import { getV3FeatureFlags, type V3FeatureFlags } from '../capabilities/capability-service'
import { listDeploymentChecks } from '../contracts/contract-hub-service'
import { listFabricTasks } from '../execution-fabric/execution-fabric-service'
import { listImpactRuns } from '../impact/impact-service'
import { listPerformanceRuns } from '../performance/performance-service'
import { useProjectContext } from '../projects/use-project-context'
import { listQualityGates, listQualityRuns, listReleaseRisks } from '../quality/quality-service'
import { apiErrorMessage } from '../../lib/api'
import {
  createReleaseDecision,
  createReleasePolicy,
  listReleaseDecisions,
  listReleasePolicies,
  type ReleaseDecisionInput,
  type ReleasePolicyInput,
} from './release-gate-service'

export function useReleaseGate() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { projectId } = useProjectContext()
  const enabled = Boolean(projectId)
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
  const decisions = useQuery({
    queryKey: ['release-decisions', projectId],
    queryFn: () => listReleaseDecisions(required(projectId)),
    enabled,
  })
  const qualityGates = useQuery({
    queryKey: ['quality-gates', projectId],
    queryFn: () => listQualityGates(required(projectId)),
    enabled,
  })
  const qualityRuns = useQuery({
    queryKey: ['quality-runs', projectId],
    queryFn: () => listQualityRuns(required(projectId)),
    enabled,
  })
  const deploymentChecks = useQuery({
    queryKey: ['deployment-checks', projectId],
    queryFn: () => listDeploymentChecks(required(projectId)),
    enabled: enabled && v3FeatureEnabled(featureFlags.data, 'contract_hub'),
  })
  const impactRuns = useQuery({
    queryKey: ['impact-runs', projectId],
    queryFn: () => listImpactRuns(required(projectId)),
    enabled: enabled && v3FeatureEnabled(featureFlags.data, 'impact_engine'),
  })
  const releaseRisks = useQuery({
    queryKey: ['release-risks', projectId],
    queryFn: () => listReleaseRisks(required(projectId)),
    enabled: enabled && v3FeatureEnabled(featureFlags.data, 'quality_intelligence'),
  })
  const performanceRuns = useQuery({
    queryKey: ['performance-runs', projectId],
    queryFn: () => listPerformanceRuns(required(projectId)),
    enabled: enabled && v3FeatureEnabled(featureFlags.data, 'performance_lab'),
  })
  const runnerTasks = useQuery({
    queryKey: ['release-runner-tasks', projectId],
    queryFn: listFabricTasks,
    enabled: enabled && v3FeatureEnabled(featureFlags.data, 'runner_fabric'),
  })
  const createPolicy = useMutation({
    mutationFn: (input: ReleasePolicyInput) => createReleasePolicy(required(projectId), input),
  })
  const createDecision = useMutation({
    mutationFn: (input: ReleaseDecisionInput) => createReleaseDecision(required(projectId), input),
  })

  async function addPolicy(input: ReleasePolicyInput): Promise<boolean> {
    try {
      await createPolicy.mutateAsync(input)
      await queryClient.invalidateQueries({ queryKey: ['release-policies', projectId] })
      void message.success('发布策略已创建')
      return true
    } catch (error) {
      void message.error(apiErrorMessage(error))
      return false
    }
  }

  async function evaluate(input: ReleaseDecisionInput): Promise<boolean> {
    try {
      const decision = await createDecision.mutateAsync(input)
      await queryClient.invalidateQueries({ queryKey: ['release-decisions', projectId] })
      void message.success(decision.status === 'pass' ? '发布判断：PASS' : '发布判断：BLOCK')
      return true
    } catch (error) {
      void message.error(apiErrorMessage(error))
      return false
    }
  }

  return {
    projectId,
    policies,
    decisions,
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
  flags: V3FeatureFlags | undefined,
  feature: keyof V3FeatureFlags,
): boolean {
  return Boolean(flags?.[feature])
}
