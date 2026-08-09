import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useState } from 'react'

import { apiErrorMessage } from '../../lib/api'
import {
  createNotificationWebhook,
  downloadArtifact,
  exportReportHtml,
  getReportExecution,
  getReportTrend,
  listNotificationDeliveries,
  listNotificationWebhooks,
  listReportExecutions,
  listReportProjects,
  setNotificationWebhookEnabled,
  type CreateNotificationWebhookInput,
} from './report-service'

export function useReports() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [projectSelection, setProjectSelection] = useState<string | null>(null)
  const [selectedExecutionId, setSelectedExecutionId] = useState<string | null>(null)
  const [webhookOpen, setWebhookOpen] = useState(false)
  const [revealedSecret, setRevealedSecret] = useState<string | null>(null)
  const projects = useQuery({ queryKey: ['projects'], queryFn: listReportProjects })
  const projectId = projectSelection ?? projects.data?.items.at(0)?.id ?? null
  const reports = useQuery({
    queryKey: ['reports', projectId],
    queryFn: () => listReportExecutions(required(projectId)),
    enabled: Boolean(projectId),
    refetchInterval: (query) =>
      query.state.data?.items.some((item) => item.status === 'running') ? 1000 : false,
  })
  const trend = useQuery({
    queryKey: ['report-trend', projectId],
    queryFn: () => getReportTrend(required(projectId)),
    enabled: Boolean(projectId),
  })
  const detail = useQuery({
    queryKey: ['report-detail', projectId, selectedExecutionId],
    queryFn: () => getReportExecution(required(projectId), required(selectedExecutionId)),
    enabled: Boolean(projectId && selectedExecutionId),
  })
  const webhooks = useQuery({
    queryKey: ['notification-webhooks', projectId],
    queryFn: () => listNotificationWebhooks(required(projectId)),
    enabled: Boolean(projectId),
  })
  const deliveries = useQuery({
    queryKey: ['notification-deliveries', projectId],
    queryFn: () => listNotificationDeliveries(required(projectId)),
    enabled: Boolean(projectId),
  })
  const exportReport = useMutation({
    mutationFn: (executionId: string) => exportReportHtml(required(projectId), executionId),
  })
  const createWebhook = useMutation({
    mutationFn: (input: CreateNotificationWebhookInput) =>
      createNotificationWebhook(required(projectId), input),
  })
  const toggleWebhook = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      setNotificationWebhookEnabled(required(projectId), id, enabled),
  })

  async function exportHtml(executionId: string) {
    try {
      const artifact = await exportReport.mutateAsync(executionId)
      await downloadArtifact(required(projectId), artifact)
      void message.success('HTML 报告已导出')
    } catch (error) {
      void message.error(apiErrorMessage(error))
    }
  }

  async function addWebhook(input: CreateNotificationWebhookInput) {
    try {
      const created = await createWebhook.mutateAsync(input)
      setWebhookOpen(false)
      setRevealedSecret(created.secret)
      await refresh('notification-webhooks')
      void message.success('通知 Webhook 已创建')
    } catch (error) {
      void message.error(apiErrorMessage(error))
    }
  }

  async function setWebhookEnabled(id: string, enabled: boolean) {
    try {
      await toggleWebhook.mutateAsync({ id, enabled })
      await refresh('notification-webhooks')
    } catch (error) {
      void message.error(apiErrorMessage(error))
    }
  }

  async function refresh(resource: string) {
    await queryClient.invalidateQueries({ queryKey: [resource, projectId] })
  }

  return {
    projects,
    projectId,
    setProjectSelection,
    reports,
    trend,
    detail,
    selectedExecutionId,
    selectExecution: setSelectedExecutionId,
    webhooks,
    deliveries,
    webhookOpen,
    setWebhookOpen,
    revealedSecret,
    dismissSecret: () => setRevealedSecret(null),
    exportHtml,
    addWebhook,
    setWebhookEnabled,
    creatingWebhook: createWebhook.isPending,
  }
}

function required(value: string | null): string {
  if (!value) throw new Error('请选择项目')
  return value
}
