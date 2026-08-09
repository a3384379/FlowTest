import {
  apiClient,
  type AuditLog,
  type Page,
  type Project,
  type ProjectPermission,
  type ProjectSecurityPolicy,
} from '../../lib/api'

export async function listManagedProjects(): Promise<Page<Project>> {
  const response = await apiClient.get<Page<Project>>('/projects', {
    params: { page: 1, page_size: 100 },
  })
  return response.data
}

export async function getProjectPermission(projectId: string): Promise<ProjectPermission> {
  const response = await apiClient.get<ProjectPermission>(`/projects/${projectId}/permissions`)
  return response.data
}

export async function getProjectSecurityPolicy(projectId: string): Promise<ProjectSecurityPolicy> {
  const response = await apiClient.get<ProjectSecurityPolicy>(
    `/projects/${projectId}/security-policy`,
  )
  return response.data
}

export async function updateProjectSecurityPolicy(
  projectId: string,
  policy: ProjectSecurityPolicy,
): Promise<ProjectSecurityPolicy> {
  const response = await apiClient.put<ProjectSecurityPolicy>(
    `/projects/${projectId}/security-policy`,
    policy,
  )
  return response.data
}

export async function listProjectAuditLogs(projectId: string): Promise<Page<AuditLog>> {
  const response = await apiClient.get<Page<AuditLog>>(`/projects/${projectId}/audit-logs`, {
    params: { page: 1, page_size: 50 },
  })
  return response.data
}
