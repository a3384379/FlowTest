import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useEffect, useRef } from 'react'
import { useServiceCatalogScope } from './service-catalog-scope'
import { useContractServiceContext } from './use-contract-service-context'

import { getV3FeatureFlags } from '../capabilities/capability-service'
import {
  createContractService,
  getContractHubSummary,
  getServiceGraph,
  listContractServices,
} from '../contracts/contract-hub-service'
import { useProjectContext } from '../projects/use-project-context'
import { apiErrorMessage } from '../../lib/api'

export type ServiceCatalogInput = {
  service_key: string
  display_name: string
  description: string
}

export function useServiceCatalog() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  const { projectId, currentProject } = useProjectContext()
  const catalogScope = useServiceCatalogScope()
  const { search, page, scopeError } = catalogScope
  const hasProject = Boolean(projectId)
  const canEdit = currentProject !== null && currentProject.role !== 'viewer'
  const featureFlags = useQuery({
    queryKey: ['v3-feature-flags'],
    queryFn: getV3FeatureFlags,
    enabled: hasProject,
  })
  const featureEnabled = featureFlags.data?.contract_hub === true
  const services = useQuery({
    queryKey: ['contract-services', projectId, search, page],
    queryFn: () => listContractServices(required(projectId), page, 20, search),
    enabled: hasProject && featureEnabled && !scopeError,
  })
  const { selected } = useContractServiceContext(projectId, hasProject && featureEnabled)
  const summary = useQuery({
    queryKey: ['contract-hub-summary', projectId],
    queryFn: () => getContractHubSummary(required(projectId)),
    enabled: hasProject && featureEnabled,
  })
  const graph = useQuery({
    queryKey: ['contract-service-graph', projectId],
    queryFn: () => getServiceGraph(required(projectId)),
    enabled: hasProject && featureEnabled,
  })
  const createService = useMutation({
    mutationFn: (input: ServiceCatalogInput) => createContractService(required(projectId), input),
  })

  async function addService(input: ServiceCatalogInput): Promise<boolean> {
    try {
      await createService.mutateAsync(input)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['contract-services', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['contract-hub-summary', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['contract-service-graph', projectId] }),
      ])
      if (mounted.current) void message.success('服务已登记')
      return true
    } catch (error) {
      if (mounted.current) void message.error(apiErrorMessage(error))
      return false
    }
  }

  return {
    projectId,
    canEdit,
    ...catalogScope,
    selected,
    featureFlags,
    featureEnabled,
    services,
    summary,
    graph,
    addService,
    creating: createService.isPending,
  }
}

function required(value: string | null): string {
  if (!value) throw new Error('请选择项目')
  return value
}
