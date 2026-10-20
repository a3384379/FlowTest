export const apiDetailKey = (
  projectId: string | null,
  apiId: string | null,
  version: number | null = null,
) => ['api-detail', projectId, apiId, version] as const

export const apiDefinitionKey = (projectId: string, apiId: string) =>
  ['api-definition', projectId, apiId] as const
