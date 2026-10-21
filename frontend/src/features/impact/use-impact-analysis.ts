import { useCatalogQuery } from '../../lib/catalog-query'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { UNSAFE_DataRouterContext, useLocation, useSearchParams } from 'react-router-dom'
import { useContext, useLayoutEffect, useMemo, useRef } from 'react'

import { apiErrorWithTrace } from '../../lib/api'
import { useProjectContext } from '../projects/use-project-context'
import { useContractServiceContext } from '../services/use-contract-service-context'
import { useProjectCapabilities } from '../projects/use-project-capabilities'
import { getV3FeatureFlags } from '../capabilities/capability-service'
import {
  createImpactMapping,
  createImpactRun,
  deleteImpactMapping,
  getImpactCatalog,
  getImpactRun,
  listImpactMappings,
  listImpactRuns,
  type ImpactMapping,
  type ImpactRunInput,
} from './impact-service'

type MappingInput = Pick<
  ImpactMapping,
  'source_kind' | 'source_selector' | 'target_type' | 'target_id'
>

export function useImpactAnalysis() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { projectId } = useProjectContext()
  const isCurrent = useImpactCommandContext(projectId)
  const { canEdit: editAllowed, permissions } = useProjectCapabilities()
  const canEdit = editAllowed && permissions.isSuccess
  const flags = useQuery({ queryKey: ['v3-feature-flags'], queryFn: getV3FeatureFlags })
  const [params, setParams] = useSearchParams()
  const selectedRunId = params.get('run')
  function setSelectedRunId(id: string | null, clearService = false) {
    const next = new URLSearchParams(params)
    next.delete('change')
    next.delete('asset')
    if (id) next.set('run', id)
    else next.delete('run')
    if (clearService) {
      next.delete('contractServiceId')
      next.delete('service_id')
      if (next.get('focus')?.startsWith('contract_service:')) next.delete('focus')
    }
    setParams(next)
  }
  function selectEvidence(key: 'change' | 'asset', id: string | null) {
    setParams((current) => {
      const next = new URLSearchParams(current)
      if (effectiveRunId) next.set('run', effectiveRunId)
      if (id) next.set(key, id)
      else next.delete(key)
      if (key === 'change') next.delete('asset')
      return next
    })
  }
  const serviceContext = useContractServiceContext(projectId, impactEnabled(flags), true)
  const enabled = serviceContext.enabled
  const serviceId = serviceContext.selection.id ?? undefined
  const mappings = useCatalogQuery(
    'impact-mappings',
    projectId,
    (page) => listImpactMappings(required(projectId), page, 20),
    enabled,
    '',
    {},
  )
  const catalog = useQuery({
    queryKey: ['impact-catalog', projectId],
    queryFn: () => getImpactCatalog(required(projectId)),
    enabled,
  })
  const runs = useCatalogQuery(
    'impact-runs',
    projectId,
    (page) => listImpactRuns(required(projectId), page, 20, serviceId),
    serviceContext.ready,
    serviceId,
    {},
  )
  const effectiveRunId = selectedRunId ?? runs.data?.items[0]?.id ?? null
  const detail = useQuery({
    queryKey: impactRunKey(projectId, effectiveRunId, serviceId),
    queryFn: () => getImpactRun(required(projectId), required(effectiveRunId), serviceId),
    enabled: serviceContext.ready && Boolean(effectiveRunId),
  })
  const createMapping = useMutation({
    mutationFn: (input: { projectId: string; payload: MappingInput }) =>
      createImpactMapping(input.projectId, input.payload),
  })
  const removeMapping = useMutation({
    mutationFn: (input: { projectId: string; mappingId: string }) =>
      deleteImpactMapping(input.projectId, input.mappingId),
  })
  const createRun = useMutation({
    mutationFn: (input: { projectId: string; payload: ImpactRunInput }) =>
      createImpactRun(input.projectId, input.payload),
  })

  async function registerMapping(input: MappingInput): Promise<boolean> {
    if (!canEdit || !enabled) return false
    return withFeedback(async () => {
      await createMapping.mutateAsync({ projectId: required(projectId), payload: input })
      if (!isCurrent()) return false
      await invalidate('impact-mappings')
      return isCurrent()
    }, '影响资产映射已登记')
  }

  async function deleteMapping(mappingId: string): Promise<void> {
    if (!canEdit || !enabled) return
    await withFeedback(async () => {
      await removeMapping.mutateAsync({ projectId: required(projectId), mappingId })
      if (!isCurrent()) return false
      await invalidate('impact-mappings')
      return isCurrent()
    }, '影响资产映射已删除')
  }

  async function analyze(input: ImpactRunInput): Promise<boolean> {
    if (!canEdit || !enabled) return false
    return withFeedback(async () => {
      const created = await createRun.mutateAsync({
        projectId: required(projectId),
        payload: input,
      })
      if (!isCurrent()) return false
      const outsideService = Boolean(
        serviceId &&
        !created.changes.some(
          (change) => change.service_key === serviceContext.selected.data?.service_key,
        ),
      )
      queryClient.setQueryData(
        impactRunKey(projectId, created.id, outsideService ? undefined : serviceId),
        created,
      )
      await invalidate('impact-runs')
      if (!isCurrent()) return false
      setSelectedRunId(created.id, outsideService)
      return true
    }, '影响分析完成，推荐集合与覆盖证据已保存')
  }

  async function withFeedback(
    action: () => Promise<boolean>,
    successText: string,
  ): Promise<boolean> {
    try {
      const succeeded = await action()
      if (succeeded) void message.success(successText)
      return succeeded
    } catch (error) {
      if (isCurrent()) void message.error(apiErrorWithTrace(error))
      return false
    }
  }

  async function invalidate(key: string): Promise<void> {
    await queryClient.invalidateQueries({ queryKey: [key, projectId] })
  }

  return {
    canEdit: canEdit && enabled,
    flags,
    serviceContext,
    permissions,
    projectId,
    mappings,
    catalog,
    runs,
    detail,
    selectedRunId: effectiveRunId,
    selectedChangeKey: params.get('change'),
    selectedAssetKey: params.get('asset'),
    selectEvidence,
    setSelectedRunId,
    registerMapping,
    deleteMapping,
    analyze,
    mappingPending: createMapping.isPending || removeMapping.isPending,
    analyzing: createRun.isPending,
  }
}

function impactEnabled(flags: { isSuccess: boolean; data?: { impact_engine: boolean } }): boolean {
  return flags.isSuccess && flags.data?.impact_engine === true
}

function useImpactCommandContext(projectId: string | null) {
  const location = useLocation()
  const dataRouter = useContext(UNSAFE_DataRouterContext)
  const context = useMemo(
    () => ({ projectId, locationKey: location.key }),
    [projectId, location.key],
  )
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

function required(value: string | null): string {
  if (!value) throw new Error('请选择项目')
  return value
}

function impactRunKey(projectId: string | null, runId: string | null, serviceId?: string) {
  return serviceId ? ['impact-run', projectId, runId, serviceId] : ['impact-run', projectId, runId]
}
