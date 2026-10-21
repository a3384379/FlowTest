import { getV3FeatureFlags } from '../capabilities/capability-service'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useLayoutEffect, useMemo, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'

import { apiErrorWithTrace } from '../../lib/api'
import { useRouteScopedState } from '../../lib/use-route-scoped-state'
import { useAuthStore } from '../auth/auth-store'
import { useProjectCapabilities } from '../projects/use-project-capabilities'
import { useProjectContext } from '../projects/use-project-context'
import {
  cleanupEnvironment,
  createEnvironmentTemplateVersion,
  disableEnvironmentTemplate,
  getEnvironmentInstance,
  getInstanceTemplateVersion,
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
  const featureFlags = useQuery({
    queryKey: ['v3-feature-flags'],
    queryFn: getV3FeatureFlags,
    enabled: Boolean(projectId),
  })
  const featureEnabled = featureFlags.data?.environment_lab === true
  const isSystemAdmin = useAuthStore((state) => Boolean(state.user?.is_system_admin))
  const userId = useAuthStore((state) => state.user?.id)
  const [params, setParams] = useSearchParams()
  const instanceId = params.get('instance')
  const context = useMemo(() => ({ projectId, instanceId }), [projectId, instanceId])
  const activeContext = useRef<typeof context | null>(context)
  useLayoutEffect(() => {
    activeContext.current = context
    return () => {
      activeContext.current = null
    }
  }, [context])
  const isCurrent = () => activeContext.current === context
  const [templateSearch, setTemplateSearchValue] = useRouteScopedState(projectId, null, '')
  const [templatePage, setTemplatePage] = useRouteScopedState(projectId, null, 1)
  const [instancePage, setInstancePage] = useRouteScopedState(projectId, null, 1)
  const templates = useQuery({
    queryKey: ['environment-templates', userId, templateSearch, templatePage],
    queryFn: () => listEnvironmentTemplates(templatePage, { search: templateSearch }),
    enabled: Boolean(featureEnabled && projectId),
  })
  const instances = useQuery({
    queryKey: ['environment-instances', projectId, instancePage],
    queryFn: () => listEnvironmentInstances(required(projectId), instancePage),
    enabled: Boolean(featureEnabled && projectId),
    refetchInterval: (query) => (query.state.data?.items.some(instancePending) ? 2000 : false),
  })
  const instance = useQuery({
    queryKey: ['environment-instance', projectId, instanceId],
    queryFn: () => getEnvironmentInstance(required(projectId), required(instanceId)),
    enabled: isReadEnabled(featureEnabled, projectId, instanceId),
    refetchInterval: (query) =>
      query.state.data && instancePending(query.state.data) ? 2000 : false,
  })
  const boundTemplate = useQuery({
    queryKey: [
      'environment-instance-template',
      projectId,
      instanceId,
      instance.data?.template_version_id,
    ],
    queryFn: () => getInstanceTemplateVersion(required(projectId), instance.data!),
    enabled: isReadEnabled(featureEnabled && instance.isSuccess, projectId, instanceId),
  })
  const register = useMutation({
    mutationKey: ['register-environment-template', context],
    mutationFn: registerEnvironmentTemplate,
  })
  const version = useMutation({
    mutationKey: ['version-environment-template', context],
    mutationFn: (input: { templateId: string; manifest: EnvironmentTemplateManifest }) =>
      createEnvironmentTemplateVersion(input.templateId, input.manifest),
  })
  const disable = useMutation({
    mutationKey: ['disable-environment-template', context],
    mutationFn: disableEnvironmentTemplate,
  })
  const provision = useMutation({
    mutationKey: ['provision-environment', context],
    mutationFn: (input: { projectId: string; templateVersionId: string; ttlSeconds: number }) =>
      provisionEnvironment(
        input.projectId,
        input.templateVersionId,
        input.ttlSeconds,
        crypto.randomUUID(),
      ),
  })
  const cleanup = useMutation({
    mutationKey: ['cleanup-environment', context],
    mutationFn: (input: { projectId: string; instanceId: string }) =>
      cleanupEnvironment(input.projectId, input.instanceId),
  })

  function selectInstance(id: string) {
    setParams((current) => {
      const next = new URLSearchParams(current)
      next.set('instance', id)
      return next
    })
  }

  function setTemplateSearch(value: string) {
    setTemplateSearchValue(value)
    setTemplatePage(1)
  }

  async function registerTemplate(input: EnvironmentTemplateInput): Promise<boolean> {
    if (!featureEnabled || !isSystemAdmin) return false
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
    if (!featureEnabled || !isSystemAdmin) return false
    return mutateWithFeedback(
      () => version.mutateAsync({ templateId, manifest }),
      '环境模板新版本已签名',
      refreshTemplates,
    )
  }

  async function disableTemplate(templateId: string): Promise<void> {
    if (!featureEnabled || !isSystemAdmin) return
    await mutateWithFeedback(
      () => disable.mutateAsync(templateId),
      '环境模板已停用',
      refreshTemplates,
    )
  }

  async function startProvision(templateVersionId: string, ttlSeconds: number): Promise<boolean> {
    if (!featureEnabled || !permissions.isSuccess || !canEdit || !projectId) return false
    const targetProject = projectId
    return mutateWithFeedback(
      () => provision.mutateAsync({ projectId: targetProject, templateVersionId, ttlSeconds }),
      '环境 Provision 已进入独立 Runner 队列',
      () => refreshInstances(targetProject),
    )
  }

  async function startCleanup(targetInstanceId: string): Promise<void> {
    if (!featureEnabled || !permissions.isSuccess || !canEdit || !projectId) return
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
      if (!isCurrent()) return false
      void message.success(successText)
      return true
    } catch (error) {
      if (!isCurrent()) return false
      void message.error(apiErrorWithTrace(error))
      return false
    }
  }

  async function refreshTemplates(): Promise<void> {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['environment-templates'] }),
      queryClient.invalidateQueries({ queryKey: ['environment-template-version'] }),
      queryClient.invalidateQueries({ queryKey: ['environment-instance-template'] }),
    ])
  }

  async function refreshInstances(targetProject: string): Promise<void> {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['environment-instances', targetProject] }),
      queryClient.invalidateQueries({ queryKey: ['environment-instance', targetProject] }),
    ])
  }

  return {
    featureFlags,
    featureEnabled,
    projectId,
    isSystemAdmin: isSystemAdmin && featureEnabled,
    canEdit: canWriteEnvironment(canEdit, permissions.isSuccess, featureEnabled),
    canExecute,
    permissions,
    templates,
    instances,
    instance,
    instanceId,
    boundTemplate,
    templateSearch,
    setTemplateSearch,
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
    templateMutationPending: [register, version, disable].some((mutation) => mutation.isPending),
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

function isReadEnabled(
  enabled: boolean,
  projectId: string | null,
  objectId: string | null,
): boolean {
  return enabled && Boolean(projectId && objectId)
}
function canWriteEnvironment(permission: boolean, loaded: boolean, enabled: boolean): boolean {
  return permission && loaded && enabled
}
