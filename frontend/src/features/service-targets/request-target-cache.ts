import type { QueryClient } from '@tanstack/react-query'

// All target editors must refresh both management catalogs and address previews.
export async function invalidateRequestTargets(client: QueryClient, projectId: string | null) {
  await client.cancelQueries({ queryKey: ['api-target-preview', projectId] })
  await Promise.all(
    [
      'environments',
      'request-target-environments',
      'request-services',
      'request-target-services',
      'flow-spec-target-services',
      'service-endpoints',
      'request-target-endpoints',
      'apis',
      'request-target-apis',
      'api-detail',
      'api-target-preview',
    ].map((resource) => client.invalidateQueries({ queryKey: [resource, projectId] })),
  )
}
