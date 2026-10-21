import { useQuery } from '@tanstack/react-query'
import { getReleaseRisk } from '../quality/quality-service'
import type { ReleaseDecisionInput } from './release-gate-service'

export function useReleaseRiskAssociation(
  projectId: string | null,
  enabled: boolean,
  values?: ReleaseDecisionInput,
) {
  const riskId = values?.release_risk_id
  const impactId = values?.impact_run_id
  const selected = Boolean(riskId && impactId)
  const query = useQuery({
    queryKey: ['release-risk-reference', projectId, riskId],
    queryFn: () => getReleaseRisk(projectId!, riskId!),
    enabled: Boolean(projectId && enabled && selected),
  })
  const mismatch = query.isSuccess && selected && query.data.impact_run_id !== impactId
  const unresolved = enabled && selected && !query.isSuccess
  return { query, mismatch, unresolved }
}
