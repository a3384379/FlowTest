import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useSearchParams } from 'react-router-dom'
import { useEffect, useRef } from 'react'
import { getV3FeatureFlags } from '../capabilities/capability-service'

import { apiErrorMessage } from '../../lib/api'
import { useProjectContext } from '../projects/use-project-context'
import { useProjectCapabilities } from '../projects/use-project-capabilities'
import { listImpactRuns } from '../impact/impact-service'
import {
  createQualityGate,
  createReleaseRisk,
  downloadJunit,
  listFlakyTests,
  listQualityGates,
  listQualityRuns,
  listReleaseRisks,
  getReleaseRisk,
  setFlakyQuarantine,
  type QualityGateInput,
  type ReleaseRiskInput,
} from './quality-service'

export function useQualityCenter() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { projectId } = useProjectContext()
  const currentProject = useRef(projectId)
  useEffect(() => {
    currentProject.current = projectId
  }, [projectId])
  const { canEdit } = useProjectCapabilities()
  const [params, setParams] = useSearchParams()
  const linkedRiskId = params.get('risk')
  const featureFlags = useQuery({
    queryKey: ['v3-feature-flags'],
    queryFn: getV3FeatureFlags,
    enabled: Boolean(projectId),
  })
  const riskEnabled = Boolean(featureFlags.data?.quality_intelligence)
  const gates = useQuery({
    queryKey: ['quality-gates', projectId],
    queryFn: () => listQualityGates(required(projectId)),
    enabled: Boolean(projectId),
  })
  const flaky = useQuery({
    queryKey: ['flaky-tests', projectId],
    queryFn: () => listFlakyTests(required(projectId)),
    enabled: Boolean(projectId),
  })
  const runs = useQuery({
    queryKey: ['quality-runs', projectId],
    queryFn: () => listQualityRuns(required(projectId)),
    enabled: Boolean(projectId),
  })
  const risks = useQuery({
    queryKey: ['release-risks', projectId],
    queryFn: () => listReleaseRisks(required(projectId)),
    enabled: Boolean(projectId && riskEnabled),
  })
  const impactRuns = useQuery({
    queryKey: ['impact-runs', projectId],
    queryFn: () => listImpactRuns(required(projectId)),
    enabled: Boolean(projectId && featureFlags.data?.impact_engine),
  })
  const activeRiskId = linkedRiskId ?? risks.data?.items.at(0)?.id
  const risk = useQuery({
    queryKey: ['release-risk', projectId, activeRiskId],
    queryFn: () => getReleaseRisk(required(projectId), required(activeRiskId ?? null)),
    enabled: Boolean(projectId && activeRiskId && riskEnabled),
  })
  const createGate = useMutation({
    mutationFn: (input: QualityGateInput) => createQualityGate(required(projectId), input),
  })
  const quarantine = useMutation({
    mutationFn: ({ recordId, value }: { recordId: string; value: boolean }) =>
      setFlakyQuarantine(required(projectId), recordId, value),
  })
  const analyzeRisk = useMutation({
    mutationFn: (input: ReleaseRiskInput) => createReleaseRisk(required(projectId), input),
  })

  async function addRisk(input: ReleaseRiskInput) {
    if (!canEdit || !riskEnabled) return false
    try {
      const created = await analyzeRisk.mutateAsync(input)
      const next = new URLSearchParams(params)
      next.set('risk', created.id)
      if (currentProject.current === projectId) setParams(next)
      await queryClient.invalidateQueries({ queryKey: ['release-risks', projectId] })
      void message.success('发布风险分析已完成')
      return true
    } catch (error) {
      void message.error(apiErrorMessage(error))
      return false
    }
  }

  async function addGate(input: QualityGateInput) {
    if (!canEdit) return false
    try {
      await createGate.mutateAsync(input)
      await queryClient.invalidateQueries({ queryKey: ['quality-gates', projectId] })
      void message.success('质量门禁已创建')
      return true
    } catch (error) {
      void message.error(apiErrorMessage(error))
      return false
    }
  }

  async function toggleQuarantine(recordId: string, value: boolean) {
    if (!canEdit) return
    try {
      await quarantine.mutateAsync({ recordId, value })
      await queryClient.invalidateQueries({ queryKey: ['flaky-tests', projectId] })
      void message.success(value ? '已隔离 Flaky 资产' : '已恢复 Flaky 资产')
    } catch (error) {
      void message.error(apiErrorMessage(error))
    }
  }

  async function exportJunit(runId: string) {
    try {
      const blob = await downloadJunit(required(projectId), runId)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `flowtest-${runId}.xml`
      link.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      void message.error(apiErrorMessage(error))
    }
  }

  return {
    featureFlags,
    riskEnabled,
    canEdit,
    linkedRiskId,
    projectId,
    gates,
    flaky,
    runs,
    risks,
    risk,
    impactRuns,
    addGate,
    toggleQuarantine,
    exportJunit,
    addRisk,
    creating: createGate.isPending,
    toggling: quarantine.isPending,
    analyzingRisk: analyzeRisk.isPending,
  }
}

function required(value: string | null): string {
  if (!value) throw new Error('请选择项目')
  return value
}
