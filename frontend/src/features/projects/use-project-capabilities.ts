import { useQuery } from '@tanstack/react-query'

import { useAuthStore } from '../auth/auth-store'
import { getProjectPermission } from './project-service'
import { useProjectContext } from './use-project-context'

export function useProjectCapabilities() {
  const { projectId } = useProjectContext()
  const userId = useAuthStore((state) => state.user?.id)
  const permissions = useQuery({
    queryKey: ['project-permissions', projectId, userId],
    queryFn: () => getProjectPermission(projectId!),
    enabled: Boolean(projectId),
  })
  return {
    permissions,
    canEdit: permissions.data?.capabilities.includes('edit') ?? false,
    canExecute: permissions.data?.capabilities.includes('execute') ?? false,
    canManageSecurity: permissions.data?.capabilities.includes('manage_security') ?? false,
    canManageTokens: permissions.data?.capabilities.includes('manage_members') ?? false,
  }
}
