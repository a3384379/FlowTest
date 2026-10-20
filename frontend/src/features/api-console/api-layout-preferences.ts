export function apiWorkspaceKey(userId?: string, projectId?: string | null): string {
  return `flowtest:api-layout:v1:${[window.location.origin, userId ?? 'anonymous', projectId ?? 'none'].map(encodeURIComponent).join(':')}`
}
