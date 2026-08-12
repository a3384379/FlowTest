import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'

import { apiErrorMessage } from '../../lib/api'
import { useAuthStore } from '../auth/auth-store'
import { useProjectContext } from '../projects/use-project-context'
import {
  cleanupEnvironment,
  createEnvironmentTemplateVersion,
  disableEnvironmentTemplate,
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
  const isSystemAdmin = useAuthStore((state) => Boolean(state.user?.is_system_admin))
  const templates = useQuery({
    queryKey: ['environment-templates'],
    queryFn: listEnvironmentTemplates,
    enabled: Boolean(projectId),
  })
  const instances = useQuery({
    queryKey: ['environment-instances', projectId],
    queryFn: () => listEnvironmentInstances(required(projectId)),
    enabled: Boolean(projectId),
    refetchInterval: (query) =>
      query.state.data?.items.some(
        (instance) =>
          ['queued', 'provisioning'].includes(instance.status) ||
          ['pending', 'running'].includes(instance.cleanup_status),
      )
        ? 2000
        : false,
  })
  const register = useMutation({ mutationFn: registerEnvironmentTemplate })
  const version = useMutation({
    mutationFn: (input: { templateId: string; manifest: EnvironmentTemplateManifest }) =>
      createEnvironmentTemplateVersion(input.templateId, input.manifest),
  })
  const disable = useMutation({ mutationFn: disableEnvironmentTemplate })
  const provision = useMutation({
    mutationFn: (input: { templateVersionId: string; ttlSeconds: number }) =>
      provisionEnvironment(
        required(projectId),
        input.templateVersionId,
        input.ttlSeconds,
        crypto.randomUUID(),
      ),
  })
  const cleanup = useMutation({
    mutationFn: (instanceId: string) => cleanupEnvironment(required(projectId), instanceId),
  })

  async function registerTemplate(input: EnvironmentTemplateInput): Promise<boolean> {
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
    return mutateWithFeedback(
      () => version.mutateAsync({ templateId, manifest }),
      '环境模板新版本已签名',
      refreshTemplates,
    )
  }

  async function disableTemplate(templateId: string): Promise<void> {
    await mutateWithFeedback(
      () => disable.mutateAsync(templateId),
      '环境模板已停用',
      refreshTemplates,
    )
  }

  async function startProvision(templateVersionId: string, ttlSeconds: number): Promise<boolean> {
    return mutateWithFeedback(
      () => provision.mutateAsync({ templateVersionId, ttlSeconds }),
      '环境 Provision 已进入独立 Runner 队列',
      refreshInstances,
    )
  }

  async function startCleanup(instanceId: string): Promise<void> {
    await mutateWithFeedback(
      () => cleanup.mutateAsync(instanceId),
      '环境清理任务已提交',
      refreshInstances,
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

  async function refreshInstances(): Promise<void> {
    await queryClient.invalidateQueries({ queryKey: ['environment-instances', projectId] })
  }

  return {
    projectId,
    isSystemAdmin,
    templates,
    instances,
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

function required(projectId: string | null): string {
  if (!projectId) throw new Error('请选择项目')
  return projectId
}
