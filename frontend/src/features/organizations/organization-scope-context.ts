import { createContext, useContext } from 'react'
import type { Organization } from './organization-service'

export type OrganizationScope = {
  organizations: Organization[]
  organizationId: string | null
  selectOrganization: (organizationId: string | null) => void
}
export const OrganizationScopeContext = createContext<OrganizationScope | null>(null)

export function useOrganizationScope(): OrganizationScope {
  const scope = useContext(OrganizationScopeContext)
  if (!scope) throw new Error('缺少组织作用域')
  return scope
}
