import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useSearchParams } from 'react-router-dom'
import { useEffect, useRef } from 'react'

import { apiErrorMessage } from '../../lib/api'
import { useProjectContext } from '../projects/use-project-context'
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
  const selectedRunId = params.get('run')
  function setSelectedRunId(id: string | null) {
    const next = new URLSearchParams(params)
    if (id) next.set('run', id)
    else next.delete('run')
    setParams(next)
  }
  const enabled = Boolean(projectId && flags.data?.impact_engine)
  const mappings = useQuery({
    queryKey: ['impact-mappings', projectId],
    queryFn: () => listImpactMappings(required(projectId)),
    enabled,
  })
  const catalog = useQuery({
    queryKey: ['impact-catalog', projectId],
    queryFn: () => getImpactCatalog(required(projectId)),
    enabled,
  })
  const runs = useQuery({
    queryKey: ['impact-runs', projectId],
    queryFn: () => listImpactRuns(required(projectId)),
    enabled,
  })
  const effectiveRunId = selectedRunId ?? runs.data?.items[0]?.id ?? null
  const detail = useQuery({
    queryKey: ['impact-run', projectId, effectiveRunId],
    queryFn: () => getImpactRun(required(projectId), required(effectiveRunId)),
    enabled: enabled && Boolean(effectiveRunId),
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
      if (currentProject.current === projectId) setSelectedRunId(created.id)
      queryClient.setQueryData(['impact-run', projectId, created.id], created)
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
