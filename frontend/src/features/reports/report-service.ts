import {
  apiClient,
  type Artifact,
  type CreatedNotificationWebhook,
  type NotificationDelivery,
  type NotificationEvent,
  type NotificationWebhook,
  type Page,
  type Project,
  type ReportExecution,
  type ReportExecutionDetail,
  type ReportTrend,
} from '../../lib/api'

export type CreateNotificationWebhookInput = {
  name: string
  url: string
  events: NotificationEvent[]
}

export async function listReportProjects(): Promise<Page<Project>> {
  const response = await apiClient.get<Page<Project>>('/projects', {
    params: { page: 1, page_size: 100 },
  })
  return response.data
}

export async function listReportExecutions(projectId: string): Promise<Page<ReportExecution>> {
  const response = await apiClient.get<Page<ReportExecution>>(
    `/projects/${projectId}/reports/executions`,
    { params: { page: 1, page_size: 50 } },
  )
  return response.data
}

export async function getReportExecution(
  projectId: string,
  executionId: string,
): Promise<ReportExecutionDetail> {
  const response = await apiClient.get<ReportExecutionDetail>(
    `/projects/${projectId}/reports/executions/${executionId}`,
  )
  return response.data
}

export async function getReportTrend(projectId: string): Promise<ReportTrend> {
  const response = await apiClient.get<ReportTrend>(`/projects/${projectId}/reports/trends`, {
    params: { days: 7 },
  })
  return response.data
}

export async function exportReportHtml(projectId: string, executionId: string): Promise<Artifact> {
  const response = await apiClient.post<Artifact>(
    `/projects/${projectId}/reports/executions/${executionId}/exports/html`,
  )
  return response.data
}

export async function downloadArtifact(projectId: string, artifact: Artifact): Promise<void> {
  const response = await apiClient.get<ArrayBuffer>(`/projects/${projectId}/files/${artifact.id}`, {
    responseType: 'arraybuffer',
  })
  const blob = new Blob([response.data], { type: artifact.content_type })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = artifact.filename
  link.click()
  URL.revokeObjectURL(url)
}

export async function listNotificationWebhooks(projectId: string): Promise<NotificationWebhook[]> {
  const response = await apiClient.get<NotificationWebhook[]>(
    `/projects/${projectId}/notification-webhooks`,
  )
  return response.data
}

export async function createNotificationWebhook(
  projectId: string,
  input: CreateNotificationWebhookInput,
): Promise<CreatedNotificationWebhook> {
  const response = await apiClient.post<CreatedNotificationWebhook>(
    `/projects/${projectId}/notification-webhooks`,
    input,
  )
  return response.data
}

export async function setNotificationWebhookEnabled(
  projectId: string,
  webhookId: string,
  enabled: boolean,
): Promise<NotificationWebhook> {
  const response = await apiClient.patch<NotificationWebhook>(
    `/projects/${projectId}/notification-webhooks/${webhookId}`,
    { enabled },
  )
  return response.data
}

export async function listNotificationDeliveries(
  projectId: string,
): Promise<Page<NotificationDelivery>> {
  const response = await apiClient.get<Page<NotificationDelivery>>(
    `/projects/${projectId}/notification-deliveries`,
    { params: { page: 1, page_size: 20 } },
  )
  return response.data
}
