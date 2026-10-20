import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { getContractService } from '../contracts/contract-hub-service'
import { contractServiceLocation } from './contract-service-location'

export function useContractServiceContext(
  projectId: string | null,
  enabled: boolean,
  legacyImpact = false,
) {
  const active = enabled && Boolean(projectId)
  const [params] = useSearchParams()
  const selection = contractServiceLocation(params, legacyImpact)
  const selected = useQuery({
    queryKey: ['contract-service', projectId, selection.id],
    queryFn: () => getContractService(projectId!, selection.id!),
    enabled: active && Boolean(selection.id),
  })
  return {
    selection,
    selected,
    enabled: active,
    ready: active && !selection.error && (!selection.id || selected.isSuccess),
  }
}
