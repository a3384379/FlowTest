import { apiClient, type DashboardSummary, type Page, type RecentExecution } from '../../lib/api'

export async function getDashboardSummary(projectId: string | null): Promise<DashboardSummary> {
  const response = await apiClient.get<DashboardSummary>('/dashboard/summary', {
    params: projectId ? { project_id: projectId } : undefined,
  })
  return response.data
}

export async function listRecentExecutions(
  projectId: string | null,
): Promise<Page<RecentExecution>> {
  const response = await apiClient.get<Page<RecentExecution>>('/dashboard/recent-executions', {
    params: { project_id: projectId ?? undefined, page: 1, page_size: 10 },
  })
  return response.data
}
