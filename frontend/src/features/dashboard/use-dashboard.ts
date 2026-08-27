import { useQuery } from '@tanstack/react-query'

import { getV3FeatureFlags } from '../capabilities/capability-service'
import { listImpactRuns } from '../impact/impact-service'
import { useProjectContext } from '../projects/use-project-context'
import { listReleaseDecisions } from '../release-gate/release-gate-service'
import { getReleaseRisk, listFlakyTests, listReleaseRisks } from '../quality/quality-service'
import { getDashboardSummary, listRecentExecutions } from './dashboard-service'

export function useDashboard() {
  const { projects, projectId, currentProject } = useProjectContext()
  const summary = useQuery({
    queryKey: ['dashboard-summary', projectId],
    queryFn: () => getDashboardSummary(projectId),
  })
  const recent = useQuery({
    queryKey: ['dashboard-recent', projectId],
    queryFn: () => listRecentExecutions(projectId),
  })
  const evidence = useDashboardEvidence(projectId)
  return { projects, projectId, currentProject, summary, recent, ...evidence }
}

function useDashboardEvidence(projectId: string | null) {
  const hasProject = projectId !== null
  const flags = useQuery({
    queryKey: ['v3-feature-flags'],
    queryFn: getV3FeatureFlags,
    enabled: hasProject,
  })
  const qualityEnabled = flags.data?.quality_intelligence === true
  const impactEnabled = flags.data?.impact_engine === true
  const risks = useQuery({
    queryKey: ['release-risks', projectId],
    queryFn: () => listReleaseRisks(required(projectId)),
    enabled: qualityEnabled,
  })
  const latestRiskId = risks.data?.items.at(0)?.id
  const risk = useQuery({
    queryKey: ['release-risk', projectId, latestRiskId],
    queryFn: () => getReleaseRisk(required(projectId), required(latestRiskId ?? null)),
    enabled: latestRiskId !== undefined,
  })
  const impactRuns = useQuery({
    queryKey: ['impact-runs', projectId],
    queryFn: () => listImpactRuns(required(projectId)),
    enabled: impactEnabled,
  })
  const flaky = useQuery({
    queryKey: ['flaky-tests', projectId],
    queryFn: () => listFlakyTests(required(projectId)),
    enabled: hasProject,
  })
  const decisions = useQuery({
    queryKey: ['release-decisions', projectId],
    queryFn: () => listReleaseDecisions(required(projectId)),
    enabled: hasProject,
  })
  const insightError = firstError([
    flags.error,
    enabledError(qualityEnabled, risks.error),
    enabledError(qualityEnabled, risk.error),
    enabledError(impactEnabled, impactRuns.error),
    flaky.error,
    decisions.error,
  ])
  return {
    flags,
    risks,
    risk,
    impactRuns,
    flaky,
    decisions,
    insightError,
    qualityEnabled,
    impactEnabled,
  }
}

function firstError(errors: Array<Error | null>): Error | null {
  return errors.find((error) => error !== null) ?? null
}

function enabledError(enabled: boolean, error: Error | null): Error | null {
  return enabled ? error : null
}

function required(value: string | null): string {
  if (!value) throw new Error('请选择项目')
  return value
}
