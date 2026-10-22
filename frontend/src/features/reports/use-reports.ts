import { useCatalogQuery } from '../../lib/catalog-query'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useContext, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { UNSAFE_DataRouterContext, useLocation } from 'react-router-dom'

import { apiErrorWithTrace } from '../../lib/api'
import { useRouteScopedSelection } from '../../lib/use-route-scoped-state'
import { useReportScope } from './report-scope'
import { useProjectCapabilities } from '../projects/use-project-capabilities'
import { useProjectContext } from '../projects/use-project-context'
import {
  createNotificationWebhook,
  downloadArtifact,
  exportReportHtml,
  getReportExecution,
  getReportTrend,
  listNotificationDeliveries,
  listNotificationWebhooks,
  listReportExecutions,
  setNotificationWebhookEnabled,
  type CreateNotificationWebhookInput,
} from './report-service'

export function useReports(initialExecutionId?: string) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { projects, projectId, selectProject } = useProjectContext()
  const { permissions } = useProjectCapabilities()
  const canManageNotifications =
    permissions.isSuccess && permissions.data.capabilities.includes('manage_members')
  const isCurrent = useReportCommandContext(projectId)
  const creating = useRef(false)
  const [selectedExecutionId, setSelectedExecutionId] = useRouteScopedSelection(
    projectId,
    initialExecutionId ?? null,
  )
  const [webhookOpen, setWebhookOpen] = useState(false)
  const [revealedSecret, setRevealedSecret] = useState<string | null>(null)
  const reportScope = useReportScope(projectId, !selectedExecutionId)
  const { page, scope } = reportScope
  const reports = useQuery({
    queryKey: ['reports', projectId, page, scope],
    queryFn: () => listReportExecutions(required(projectId), page, 'all', scope!),
    enabled: Boolean(projectId && scope && !selectedExecutionId),
    refetchInterval: (query) =>
      query.state.data?.items.some((item) => ['queued', 'running'].includes(item.status))
        ? 1000
        : false,
  })
  const trend = useQuery({
    queryKey: ['report-trend', projectId, scope],
    queryFn: () => getReportTrend(required(projectId), scope!),
    enabled: Boolean(projectId && scope && !selectedExecutionId),
    refetchInterval: (query) => (query.state.data?.summary?.pending ? 1000 : false),
  })
  const detail = useQuery({
    queryKey: ['report-detail', projectId, selectedExecutionId],
    queryFn: () => getReportExecution(required(projectId), required(selectedExecutionId)),
    enabled: Boolean(projectId && selectedExecutionId),
    refetchInterval: (query) => (query.state.data?.summary.status === 'running' ? 1000 : false),
  })
  const webhooks = useQuery({
    queryKey: ['notification-webhooks', projectId],
    queryFn: () => listNotificationWebhooks(required(projectId)),
    enabled: Boolean(projectId),
  })
  const deliveries = useCatalogQuery(
    'notification-deliveries',
    projectId,
    (page) => listNotificationDeliveries(required(projectId), page, 20),
    Boolean(projectId),
    '',
    {},
  )
  const exportReport = useMutation({
    mutationFn: (input: { projectId: string; executionId: string }) =>
      exportReportHtml(input.projectId, input.executionId),
  })
  const createWebhook = useMutation({
    mutationFn: (input: { projectId: string; definition: CreateNotificationWebhookInput }) =>
      createNotificationWebhook(input.projectId, input.definition),
    onSuccess: async (_created, input) => {
      await queryClient.invalidateQueries({ queryKey: ['notification-webhooks', input.projectId] })
    },
  })
  const toggleWebhook = useMutation({
    mutationFn: (input: { projectId: string; id: string; enabled: boolean }) =>
      setNotificationWebhookEnabled(input.projectId, input.id, input.enabled),
    onSuccess: async (_updated, input) => {
      await queryClient.invalidateQueries({ queryKey: ['notification-webhooks', input.projectId] })
    },
  })

  async function exportHtml(executionId: string) {
    if (!projectId || !isCurrent()) return
    const project = projectId
    try {
      const artifact = await exportReport.mutateAsync({ projectId: project, executionId })
      if (!isCurrent()) return
      await downloadArtifact(project, artifact)
      if (isCurrent()) void message.success('HTML 报告已导出')
    } catch (error) {
      if (isCurrent()) void message.error(apiErrorWithTrace(error))
    }
  }

  async function addWebhook(input: CreateNotificationWebhookInput) {
    if (!projectId || !canManageNotifications || !isCurrent() || creating.current) return
    creating.current = true
    try {
      const created = await createWebhook.mutateAsync({ projectId, definition: input })
      if (!isCurrent()) return
      setWebhookOpen(false)
      setRevealedSecret(created.secret)
      void message.success('通知 Webhook 已创建')
    } catch (error) {
      if (isCurrent()) void message.error(apiErrorWithTrace(error))
    } finally {
      creating.current = false
    }
  }

  async function setWebhookEnabled(id: string, enabled: boolean) {
    if (!projectId || !canManageNotifications || !isCurrent()) return
    try {
      await toggleWebhook.mutateAsync({ projectId, id, enabled })
    } catch (error) {
      if (isCurrent()) void message.error(apiErrorWithTrace(error))
    }
  }

  return {
    projects,
    canManageNotifications,
    permissions,
    projectId,
    setProjectSelection: selectProject,
    reports,
    page,
    setPage: reportScope.setPage,
    reportScope,
    refreshReports: () => Promise.all([reports.refetch(), trend.refetch()]),
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

function useReportCommandContext(projectId: string | null) {
  const location = useLocation()
  const router = useContext(UNSAFE_DataRouterContext)
  const context = useMemo(() => ({ projectId, key: location.key }), [projectId, location.key])
  const active = useRef<typeof context | null>(context)
  useLayoutEffect(() => {
    active.current = context
    return () => {
      active.current = null
    }
  }, [context])
  return () =>
    active.current === context && (!router || router.router.state.location.key === location.key)
}

function required(value: string | null): string {
  if (!value) throw new Error('请选择项目')
  return value
}
