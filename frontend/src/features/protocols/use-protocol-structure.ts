import { useQuery } from '@tanstack/react-query'
import { inspectProtocolStructure, type SchemaArtifact } from './protocol-service'

export function useProtocolStructure(
  asset: SchemaArtifact,
  node: string,
  page: number,
  enabled: boolean,
) {
  return useQuery({
    queryKey: [
      'protocol-structure',
      asset.project_id,
      asset.protocol,
      asset.id,
      asset.version,
      asset.content_sha256,
      node,
      page,
    ],
    queryFn: () => inspectProtocolStructure(asset, node, page),
    enabled,
    staleTime: Infinity,
    retry: false,
  })
}
