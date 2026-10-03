import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useSearchParams } from 'react-router-dom'

import { apiErrorMessage } from '../../lib/api'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'
import { useAuthStore } from '../auth/auth-store'
import { useProjectCapabilities } from '../projects/use-project-capabilities'
import { useProjectContext } from '../projects/use-project-context'
import {
  cleanupEnvironment,
  createEnvironmentTemplateVersion,
  disableEnvironmentTemplate,
  getEnvironmentInstance,
  listEnvironmentInstances,
  listEnvironmentTemplates,
  provisionEnvironment,
  registerEnvironmentTemplate,
  type EnvironmentTemplateInput,
  type EnvironmentTemplateManifest,
} from './environment-service'

export function useEnvironmentLab() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { projectId } = useProjectContext()
  const { canEdit, canExecute, permissions } = useProjectCapabilities()
  const isSystemAdmin = useAuthStore((state) => Boolean(state.user?.is_system_admin))
  const userId = useAuthStore((state) => state.user?.id)
  const [params, setParams] = useSearchParams()
  const instanceId = params.get('instance')
  const [templatePage, setTemplatePage] = useRouteScopedState(projectId, null, 1)
  const [instancePage, setInstancePage] = useRouteScopedState(projectId, null, 1)
  const templates = useQuery({
    queryKey: ['environment-templates', userId, templatePage],
    queryFn: () => listEnvironmentTemplates(templatePage),
    enabled: Boolean(projectId),
  })
  const instances = useQuery({
    queryKey: ['environment-instances', projectId, instancePage],
    queryFn: () => listEnvironmentInstances(required(projectId), instancePage),
    enabled: Boolean(projectId),
    refetchInterval: (query) => (query.state.data?.items.some(instancePending) ? 2000 : false),
  })
  const instance = useQuery({
    queryKey: ['environment-instance', projectId, instanceId],
    queryFn: () => getEnvironmentInstance(required(projectId), required(instanceId)),
    enabled: Boolean(projectId && instanceId),
    refetchInterval: (query) =>
      query.state.data && instancePending(query.state.data) ? 2000 : false,
  })
  const register = useMutation({ mutationFn: registerEnvironmentTemplate })
  const version = useMutation({
    mutationFn: (input: { templateId: string; manifest: EnvironmentTemplateManifest }) =>
      createEnvironmentTemplateVersion(input.templateId, input.manifest),
  })
  const disable = useMutation({ mutationFn: disableEnvironmentTemplate })
  const provision = useMutation({
    mutationFn: (input: { projectId: string; templateVersionId: string; ttlSeconds: number }) =>
      provisionEnvironment(
        input.projectId,
        input.templateVersionId,
        input.ttlSeconds,
        crypto.randomUUID(),
      ),
  })
  const cleanup = useMutation({
    mutationFn: (input: { projectId: string; instanceId: string }) =>
      cleanupEnvironment(input.projectId, input.instanceId),
  })

  function selectInstance(id: string) {
    const next = new URLSearchParams(params)
    next.set('instance', id)
    setParams(next)
  }

  async function registerTemplate(input: EnvironmentTemplateInput): Promise<boolean> {
    if (!isSystemAdmin) return false
    return mutateWithFeedback(
      () => register.mutateAsync(input),
      '环境模板已签名注册',
      refreshTemplates,
    )
  }

  async function addVersion(
    templateId: string,
    manifest: EnvironmentTemplateManifest,
  ): Promise<boolean> {
    if (!isSystemAdmin) return false
    return mutateWithFeedback(
      () => version.mutateAsync({ templateId, manifest }),
      '环境模板新版本已签名',
      refreshTemplates,
    )
  }

  async function disableTemplate(templateId: string): Promise<void> {
    if (!isSystemAdmin) return
    await mutateWithFeedback(
      () => disable.mutateAsync(templateId),
      '环境模板已停用',
      refreshTemplates,
    )
  }

  async function startProvision(templateVersionId: string, ttlSeconds: number): Promise<boolean> {
    if (!canEdit || !projectId) return false
    const targetProject = projectId
    return mutateWithFeedback(
      () => provision.mutateAsync({ projectId: targetProject, templateVersionId, ttlSeconds }),
      '环境 Provision 已进入独立 Runner 队列',
      () => refreshInstances(targetProject),
    )
  }

  async function startCleanup(targetInstanceId: string): Promise<void> {
    if (!canEdit || !projectId) return
    const targetProject = projectId
    await mutateWithFeedback(
      () => cleanup.mutateAsync({ projectId: targetProject, instanceId: targetInstanceId }),
      '环境清理任务已提交',
      () => refreshInstances(targetProject),
    )
  }

  async function mutateWithFeedback<T>(
    action: () => Promise<T>,
    successText: string,
    refresh: () => Promise<void>,
  ): Promise<boolean> {
    try {
      await action()
      await refresh()
      void message.success(successText)
      return true
    } catch (error) {
      void message.error(apiErrorMessage(error))
      return false
    }
  }

  async function refreshTemplates(): Promise<void> {
    await queryClient.invalidateQueries({ queryKey: ['environment-templates'] })
  }

  async function refreshInstances(targetProject: string): Promise<void> {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['environment-instances', targetProject] }),
      queryClient.invalidateQueries({ queryKey: ['environment-instance', targetProject] }),
    ])
  }

  return {
    projectId,
    isSystemAdmin,
    canEdit,
    canExecute,
    permissions,
    templates,
    instances,
    instance,
    instanceId,
    selectInstance,
    templatePage,
    setTemplatePage,
    instancePage,
    setInstancePage,
    registerTemplate,
    addVersion,
    disableTemplate,
    startProvision,
    startCleanup,
    templateMutationPending: register.isPending || version.isPending || disable.isPending,
    provisioning: provision.isPending,
    cleaning: cleanup.isPending,
  }
}

function instancePending(instance: { status: string; cleanup_status: string }) {
  return (
    ['queued', 'provisioning'].includes(instance.status) ||
    ['pending', 'running'].includes(instance.cleanup_status)
  )
}

function required(projectId: string | null): string {
  if (!projectId) throw new Error('请选择项目或实例')
  return projectId
}
