import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'

import { apiErrorMessage } from '../../lib/api'
import { useProjectContext } from '../projects/use-project-context'
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
    enabled: Boolean(projectId),
  })
  const impactRuns = useQuery({
    queryKey: ['impact-runs', projectId],
    queryFn: () => listImpactRuns(required(projectId)),
    enabled: Boolean(projectId),
  })
  const activeRiskId = risks.data?.items.at(0)?.id
  const risk = useQuery({
    queryKey: ['release-risk', projectId, activeRiskId],
    queryFn: () => getReleaseRisk(required(projectId), required(activeRiskId ?? null)),
    enabled: Boolean(projectId && activeRiskId),
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
    try {
      await analyzeRisk.mutateAsync(input)
      await queryClient.invalidateQueries({ queryKey: ['release-risks', projectId] })
      void message.success('发布风险分析已完成')
      return true
    } catch (error) {
      void message.error(apiErrorMessage(error))
      return false
    }
  }

  async function addGate(input: QualityGateInput) {
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
