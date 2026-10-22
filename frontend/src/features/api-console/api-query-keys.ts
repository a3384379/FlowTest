export const apiDetailKey = (
  projectId: string | null,
  apiId: string | null,
  version: number | null = null,
) => ['api-detail', projectId, apiId, version] as const

export const apiDefinitionKey = (projectId: string, apiId: string) =>
  ['api-definition', projectId, apiId] as const

export const apiDefinitionRecoveryPrefix = ['api-definition-recovery'] as const

export const apiDefinitionRecoveryKey = (projectId: string, apiId: string) =>
  [...apiDefinitionRecoveryPrefix, projectId, apiId] as const

export type ApiDefinitionRecoveryScope = {
  epoch: number
  userId: string | null
  organizationId: string | null
}
