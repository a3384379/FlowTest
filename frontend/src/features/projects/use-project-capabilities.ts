import { useQuery } from '@tanstack/react-query'
import { useQueryInvalidated } from '../../lib/use-query-invalidated'

import { useAuthStore } from '../auth/auth-store'
import { getProjectPermission } from './project-service'
import { useProjectContext } from './use-project-context'

export function useProjectCapabilities() {
  const { projectId } = useProjectContext()
  const userId = useAuthStore((state) => state.user?.id)
  const invalidated = useQueryInvalidated(['project-permissions', projectId, userId])
  const permissions = useQuery({
    queryKey: ['project-permissions', projectId, userId],
    queryFn: () => getProjectPermission(projectId!),
    enabled: Boolean(projectId),
  })
  return {
    permissions,
    canEdit:
      !invalidated && permissions.isSuccess && permissions.data.capabilities.includes('edit'),
    canExecute:
      !invalidated && permissions.isSuccess && permissions.data.capabilities.includes('execute'),
    canManageSecurity:
      !invalidated &&
      permissions.isSuccess &&
      permissions.data.capabilities.includes('manage_security'),
    canManageTokens:
      !invalidated &&
      permissions.isSuccess &&
      permissions.data.capabilities.includes('manage_members'),
  }
}
