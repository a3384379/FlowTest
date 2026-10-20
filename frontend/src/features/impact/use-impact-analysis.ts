import { useCatalogQuery } from '../../lib/catalog-query'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useSearchParams } from 'react-router-dom'
import { useEffect, useRef } from 'react'

import { apiErrorMessage } from '../../lib/api'
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
  const currentProject = useRef(projectId)
  useEffect(() => {
    currentProject.current = projectId
  }, [projectId])
  const { canEdit, permissions } = useProjectCapabilities()
  const flags = useQuery({ queryKey: ['v3-feature-flags'], queryFn: getV3FeatureFlags })
  const [params, setParams] = useSearchParams()
  const routeScope = params.toString()
  const currentScope = useRef(routeScope)
  useEffect(() => {
    currentScope.current = routeScope
  }, [routeScope])
  const selectedRunId = params.get('run')
  function setSelectedRunId(id: string | null, clearService = false) {
    const next = new URLSearchParams(params)
    if (id) next.set('run', id)
    else next.delete('run')
    if (clearService) {
      next.delete('contractServiceId')
      next.delete('service_id')
      if (next.get('focus')?.startsWith('contract_service:')) next.delete('focus')
    }
    setParams(next)
  }
  const serviceContext = useContractServiceContext(
    projectId,
    flags.data?.impact_engine === true,
    true,
  )
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
    mutationFn: (input: MappingInput) => createImpactMapping(required(projectId), input),
  })
  const removeMapping = useMutation({
    mutationFn: (mappingId: string) => deleteImpactMapping(required(projectId), mappingId),
  })
  const createRun = useMutation({
    mutationFn: (input: ImpactRunInput) => createImpactRun(required(projectId), input),
  })

  async function registerMapping(input: MappingInput): Promise<boolean> {
    if (!canEdit || !enabled) return false
    return withFeedback(async () => {
      await createMapping.mutateAsync(input)
      await invalidate('impact-mappings')
    }, '影响资产映射已登记')
  }

  async function deleteMapping(mappingId: string): Promise<void> {
    if (!canEdit || !enabled) return
    await withFeedback(async () => {
      await removeMapping.mutateAsync(mappingId)
      await invalidate('impact-mappings')
    }, '影响资产映射已删除')
  }

  async function analyze(input: ImpactRunInput): Promise<boolean> {
    if (!canEdit || !enabled) return false
    return withFeedback(async () => {
      const created = await createRun.mutateAsync(input)
      const outsideService = Boolean(
        serviceId &&
        !created.changes.some(
          (change) => change.service_key === serviceContext.selected.data?.service_key,
        ),
      )
      if (currentProject.current === projectId && currentScope.current === routeScope)
        setSelectedRunId(created.id, outsideService)
      queryClient.setQueryData(
        impactRunKey(projectId, created.id, outsideService ? undefined : serviceId),
        created,
      )
      await invalidate('impact-runs')
    }, '影响分析完成，推荐集合与覆盖证据已保存')
  }

  async function withFeedback(action: () => Promise<void>, successText: string): Promise<boolean> {
    try {
      await action()
      void message.success(successText)
      return true
    } catch (error) {
      void message.error(apiErrorMessage(error))
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
    setSelectedRunId,
    registerMapping,
    deleteMapping,
    analyze,
    mappingPending: createMapping.isPending || removeMapping.isPending,
    analyzing: createRun.isPending,
  }
}

function required(value: string | null): string {
  if (!value) throw new Error('请选择项目')
  return value
}

function impactRunKey(projectId: string | null, runId: string | null, serviceId?: string) {
  return serviceId ? ['impact-run', projectId, runId, serviceId] : ['impact-run', projectId, runId]
}
