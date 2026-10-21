import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { UNSAFE_DataRouterContext, useLocation, useSearchParams } from 'react-router-dom'
import { useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { getV3FeatureFlags } from '../capabilities/capability-service'

import { apiErrorWithTrace, type Page } from '../../lib/api'
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
  getFlakyRecord,
  setFlakyQuarantine,
  type QualityGateInput,
  type ReleaseRiskInput,
  type ReleaseRiskSummary,
} from './quality-service'

export function useQualityCenter() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { projectId } = useProjectContext()
  const isCurrent = useQualityCommandContext(projectId)
  const activity = useQualityCommandActivity(projectId)
  const { canEdit: editAllowed, permissions } = useProjectCapabilities()
  const canEdit = editAllowed && permissions.isSuccess
  const [params, setParams] = useSearchParams()
  const linkedRecordId = params.get('record')
  const recordTargetType = params.get('target_type')
  const recordTargetId = params.get('target')
  const recordVersion = params.get('version')
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
  const flaky = useQualityCatalog(
    'flaky-tests',
    'flaky_page',
    projectId,
    (page) => listFlakyTests(required(projectId), page, 20),
    Boolean(projectId),
  )
  const latestRun = useQuery({
    queryKey: ['quality-runs', projectId, 'latest'],
    queryFn: () => listQualityRuns(required(projectId), 1, 1),
    enabled: Boolean(projectId),
  })
  const runs = useQualityCatalog(
    'quality-runs',
    'run_page',
    projectId,
    (page) => listQualityRuns(required(projectId), page, 20),
    Boolean(projectId),
  )
  const risks = useQualityCatalog(
    'release-risks',
    'risk_page',
    projectId,
    (page) => listReleaseRisks(required(projectId), page, 20),
    Boolean(projectId && riskEnabled),
  )
  const impactRuns = useQualityCatalog(
    'impact-runs',
    'impact_page',
    projectId,
    (page) => listImpactRuns(required(projectId), page, 20),
    Boolean(projectId && featureFlags.data?.impact_engine),
  )
  const { linkedRiskId, activeRiskId } = usePinnedRisk(riskEnabled && !activity.busy, risks.data)
  const risk = useQuery({
    queryKey: ['release-risk', projectId, activeRiskId],
    queryFn: () => getReleaseRisk(required(projectId), required(activeRiskId ?? null)),
    enabled: Boolean(projectId && activeRiskId && riskEnabled),
  })
  const record = useQuery({
    queryKey: [
      'flaky-record',
      projectId,
      linkedRecordId,
      recordTargetType,
      recordTargetId,
      recordVersion,
    ],
    queryFn: () =>
      getFlakyRecord(required(projectId), required(linkedRecordId), {
        targetType: recordTargetType,
        targetId: recordTargetId,
        version: recordVersion,
      }),
    enabled: Boolean(projectId && linkedRecordId),
  })
  function selectEvidence(key: 'risk' | 'record', id: string | null) {
    setParams((current) => {
      const next = new URLSearchParams(current)
      if (key === 'record') {
        next.delete('target_type')
        next.delete('target')
        next.delete('version')
      }
      if (id) next.set(key, id)
      else next.delete(key)
      return next
    })
  }
  const createGate = useMutation({
    mutationFn: (input: { projectId: string; payload: QualityGateInput }) =>
      createQualityGate(input.projectId, input.payload),
  })
  const quarantine = useMutation({
    mutationFn: ({
      projectId: targetProject,
      recordId,
      value,
    }: {
      projectId: string
      recordId: string
      value: boolean
    }) => setFlakyQuarantine(targetProject, recordId, value),
  })
  const analyzeRisk = useMutation({
    mutationFn: (input: { projectId: string; payload: ReleaseRiskInput }) =>
      createReleaseRisk(input.projectId, input.payload),
  })

  async function addRisk(input: ReleaseRiskInput) {
    if (!canEdit || !riskEnabled) return false
    activity.begin()
    try {
      const created = await analyzeRisk.mutateAsync({
        projectId: required(projectId),
        payload: input,
      })
      await queryClient.invalidateQueries({ queryKey: ['release-risks', projectId] })
      if (!isCurrent()) return false
      selectEvidence('risk', created.id)
      void message.success('发布风险分析已完成')
      return true
    } catch (error) {
      if (isCurrent()) void message.error(apiErrorWithTrace(error))
      return false
    } finally {
      activity.end()
    }
  }

  async function addGate(input: QualityGateInput) {
    if (!canEdit) return false
    activity.begin()
    try {
      await createGate.mutateAsync({ projectId: required(projectId), payload: input })
      await queryClient.invalidateQueries({ queryKey: ['quality-gates', projectId] })
      if (!isCurrent()) return false
      void message.success('质量门禁已创建')
      return true
    } catch (error) {
      if (isCurrent()) void message.error(apiErrorWithTrace(error))
      return false
    } finally {
      activity.end()
    }
  }

  async function toggleQuarantine(recordId: string, value: boolean) {
    if (!canEdit) return
    activity.begin()
    try {
      await quarantine.mutateAsync({ projectId: required(projectId), recordId, value })
      await queryClient.invalidateQueries({ queryKey: ['flaky-tests', projectId] })
      await queryClient.invalidateQueries({ queryKey: ['flaky-record', projectId, recordId] })
      if (!isCurrent()) return
      void message.success(value ? '已隔离 Flaky 资产' : '已恢复 Flaky 资产')
    } catch (error) {
      if (isCurrent()) void message.error(apiErrorWithTrace(error))
    } finally {
      activity.end()
    }
  }

  async function exportJunit(runId: string) {
    activity.begin()
    try {
      const blob = await downloadJunit(required(projectId), runId)
      if (!isCurrent()) return
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `flowtest-${runId}.xml`
      link.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      if (isCurrent()) void message.error(apiErrorWithTrace(error))
    } finally {
      activity.end()
    }
  }

  return {
    featureFlags,
    permissions,
    riskEnabled,
    canEdit,
    linkedRiskId,
    activeRiskId,
    linkedRecordId,
    record,
    selectEvidence,
    projectId,
    latestRun,
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

function usePinnedRisk(riskEnabled: boolean, risks: Page<ReleaseRiskSummary> | undefined) {
  const location = useLocation()
  const router = useContext(UNSAFE_DataRouterContext)
  const [params, setParams] = useSearchParams()
  const linkedRiskId = params.get('risk')
  const firstRiskId = risks?.items.at(0)?.id
  useEffect(() => {
    if (!riskEnabled || linkedRiskId || !firstRiskId) return
    if (router && router.router.state.location.key !== location.key) return
    setParams(
      (current) => {
        if (current.has('risk')) return current
        const next = new URLSearchParams(current)
        next.set('risk', firstRiskId)
        return next
      },
      { replace: true },
    )
  }, [riskEnabled, linkedRiskId, firstRiskId, setParams, router, location.key])
  const activeRiskId = linkedRiskId ?? firstRiskId
  return { linkedRiskId, activeRiskId }
}

function useQualityCatalog<T>(
  resource: string,
  pageKey: string,
  projectId: string | null,
  load: (page: number) => Promise<Page<T>>,
  enabled: boolean,
) {
  const [params, setParams] = useSearchParams()
  const raw = params.get(pageKey) ?? '1'
  const value = /^[1-9]\d*$/.test(raw) ? Number(raw) : 1
  const page = Number.isSafeInteger(value) ? value : 1
  const query = useQuery({
    queryKey: [resource, projectId, '', 'catalog', page],
    queryFn: () => load(page),
    enabled: Boolean(projectId && enabled),
  })
  function setPage(nextPage: number) {
    setParams((current) => {
      const next = new URLSearchParams(current)
      next.set(pageKey, String(nextPage))
      return next
    })
  }
  return { ...query, page, setPage }
}

function required(value: string | null): string {
  if (!value) throw new Error('请选择项目')
  return value
}

function useQualityCommandContext(projectId: string | null) {
  const location = useLocation()
  const dataRouter = useContext(UNSAFE_DataRouterContext)
  const context = useMemo(() => ({ projectId, key: location.key }), [projectId, location.key])
  const active = useRef<typeof context | null>(context)
  useLayoutEffect(() => {
    active.current = context
    return () => {
      active.current = null
    }
  }, [context])
  return () =>
    active.current === context &&
    (!dataRouter || dataRouter.router.state.location.key === location.key)
}

function useQualityCommandActivity(projectId: string | null) {
  const [activity, setActivity] = useState({ projectId, count: 0 })
  return {
    busy: activity.projectId === projectId && activity.count > 0,
    begin: () =>
      setActivity((current) => ({
        projectId,
        count: current.projectId === projectId ? current.count + 1 : 1,
      })),
    end: () =>
      setActivity((current) =>
        current.projectId === projectId
          ? { projectId, count: Math.max(0, current.count - 1) }
          : current,
      ),
  }
}
