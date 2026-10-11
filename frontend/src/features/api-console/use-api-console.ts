import { useEnvironmentSelection } from '../projects/environment-selection'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useEffect, useState } from 'react'

import {
  apiErrorMessage,
  type ApiDetail,
  type ApiVersion,
  type Environment,
  type ImportRun,
  type Project,
} from '../../lib/api'
import { useProjectContext } from '../projects/use-project-context'
import { useRouteScopedSelection, useRouteScopedState } from '../../lib/use-route-scoped-state'
import {
  listRequestServices,
  listServiceEndpoints,
} from '../service-targets/service-target-service'
import {
  createApi,
  createApiVersion,
  createEnvironment,
  createProject,
  deleteEnvironment,
  discoverApiDocumentUrl,
  downloadArtifact,
  mergeApiImport,
  previewApiDocument,
  previewApiDocumentUrl,
  exportApis,
  getApiDetail,
  listApis,
  listApiVersions,
  listArtifacts,
  listEnvironments,
  uploadArtifact,
  previewApi,
  updateApiDefinition,
  updateEnvironment,
  type ImportPreviewInput,
  type ApiVersionInput,
  type CreateApiInput,
  type CreateEnvironmentInput,
  type CreateProjectInput,
  type HttpMethod,
} from './api-service'
import { getProjectRedactionPolicy } from '../projects/project-service'
import { useApiExecutions } from './use-api-executions'
import { invalidateRequestTargets } from '../service-targets/request-target-cache'
import { useAuthStore } from '../auth/auth-store'

export function useApiConsole(initialApiId?: string, initialExecutionId?: string) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const {
    projects,
    projectId,
    currentProject,
    selectProject: selectContextProject,
  } = useProjectContext()
  const systemAdmin = useAuthStore((state) => state.user?.is_system_admin === true)
  const canEdit = canEditApiProject(currentProject, systemAdmin)
  const [apiSelection, setApiSelection] = useRouteScopedSelection(projectId, initialApiId ?? null)
  const [apiSearchInput, setApiSearchInput] = useState('')
  const [apiSearch, setApiSearch] = useState('')
  const [apiMethod, setApiMethod] = useState<HttpMethod | null>(null)
  const [apiPage, setApiPage] = useState(1)
  const [apiFolder, setApiFolder] = useRouteScopedState(projectId, null, 'all')
  const [expectedStatus, setExpectedStatus] = useState(200)
  const [lastImport, setLastImport] = useState<ImportRun | null>(null)

  const environments = useQuery({
    queryKey: ['environments', projectId],
    queryFn: () => listEnvironments(requiredId(projectId)),
    enabled: Boolean(projectId),
  })
  const {
    environmentId,
    selectEnvironment: setEnvironmentSelection,
    selectionInvalid: environmentSelectionInvalid,
    environmentPlaceholder,
    environmentStatus,
  } = useEnvironmentSelection(projectId, environments.data)
  const apis = useQuery({
    queryKey: ['apis', projectId, apiPage, apiSearch, apiMethod, apiFolder],
    queryFn: () =>
      listApis(requiredId(projectId), {
        page: apiPage,
        pageSize: 50,
        search: apiSearch,
        method: apiMethod ?? undefined,
        folder: apiFolder,
      }),
    enabled: Boolean(projectId),
  })
  const apiId = apiSelection ?? apis.data?.items.at(0)?.id ?? null
  const [selectedVersion, setSelectedVersion] = useRouteScopedState<number | null>(
    projectId,
    apiId,
    null,
  )
  const { versions, apiDetail } = useApiVersionQueries(projectId, apiId, selectedVersion)
  const targetState = useApiRequestTarget(
    projectId,
    apiId,
    environmentId,
    apiDetail.data?.version,
    environments.data,
  )
  const executions = useApiExecutions({
    projectId,
    apiId,
    executionId: initialExecutionId,
    environmentId,
    expectedStatus,
    assertions: apiDetail.data?.version.assertions,
    target: targetState.executionOptions,
  })
  const artifacts = useQuery({
    queryKey: ['artifacts', projectId],
    queryFn: () => listArtifacts(requiredId(projectId)),
    enabled: Boolean(projectId),
  })
  const redactionMode = useProjectRedactionMode(projectId)

  const projectMutation = useMutation({ mutationFn: createProject })
  const environmentMutation = useMutation({
    mutationFn: (input: CreateEnvironmentInput) => createEnvironment(requiredId(projectId), input),
  })
  const updateEnvironmentMutation = useMutation({
    mutationFn: ({
      environmentId,
      input,
    }: {
      environmentId: string
      input: Partial<CreateEnvironmentInput>
    }) => updateEnvironment(requiredId(projectId), environmentId, input),
  })
  const deleteEnvironmentMutation = useMutation({
    mutationFn: (environmentId: string) => deleteEnvironment(requiredId(projectId), environmentId),
  })
  const apiMutation = useMutation({
    mutationFn: (input: CreateApiInput) => createApi(requiredId(projectId), input),
  })
  const previewImportMutation = useMutation({
    mutationFn: (input: ImportPreviewInput) =>
      input.kind === 'file'
        ? previewApiDocument(requiredId(projectId), input.file, input.sourceType)
        : previewApiDocumentUrl(
            requiredId(projectId),
            input.url,
            input.sourceType,
            input.documentId,
          ),
    onSuccess: (value) => {
      setLastImport(value)
      void message.success('导入差异已生成，请选择需要合并的接口')
    },
    onError: (error) => void message.error(apiErrorMessage(error)),
  })
  const discoverImportMutation = useMutation({
    mutationFn: (url: string) => discoverApiDocumentUrl(requiredId(projectId), url),
    onError: (error) => void message.error(apiErrorMessage(error)),
  })
  const mergeImportMutation = useMutation({
    mutationFn: (selectedKeys: string[]) =>
      mergeApiImport(requiredId(projectId), requiredId(lastImport?.id ?? null), selectedKeys),
    onSuccess: async (value) => {
      setLastImport(value)
      await queryClient.invalidateQueries({ queryKey: ['apis', projectId] })
      void message.success('所选接口已合并')
    },
    onError: (error) => void message.error(apiErrorMessage(error)),
  })
  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadArtifact(requiredId(projectId), file),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['artifacts', projectId] })
      void message.success('文件上传成功')
    },
    onError: (error) => void message.error(apiErrorMessage(error)),
  })
  const versionMutation = useMutation({
    mutationFn: (input: ApiVersionInput) =>
      createApiVersion(requiredId(projectId), requiredId(apiId), input),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['apis', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['api-detail', projectId, apiId] }),
        queryClient.invalidateQueries({ queryKey: ['api-versions', projectId, apiId] }),
      ])
      void message.success('接口新版本已保存')
    },
    onError: (error) => {
      void queryClient.invalidateQueries({ queryKey: ['api-detail', projectId, apiId] })
      void message.error(apiErrorMessage(error))
    },
  })
  const renameMutation = useMutation({
    mutationFn: ({ apiId: targetApiId, name }: { apiId: string; name: string }) =>
      updateApiDefinition(requiredId(projectId), targetApiId, { name }),
    onSuccess: async (_definition, variables) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['apis', projectId] }),
        queryClient.invalidateQueries({
          queryKey: ['api-detail', projectId, variables.apiId],
        }),
        queryClient.invalidateQueries({ queryKey: ['global-search'] }),
      ])
      void message.success('接口名称已更新')
    },
    onError: (error) => void message.error(apiErrorMessage(error)),
  })
  const previewMutation = useMutation({
    mutationFn: () =>
      previewApi(requiredId(projectId), requiredId(apiId), requiredId(environmentId), {
        ...targetState.executionOptions,
      }),
    onError: (error) => void message.error(apiErrorMessage(error)),
  })
  const exportMutation = useMutation({
    mutationFn: (format: 'har' | 'curl' | 'bruno' | 'excel') =>
      exportApis(requiredId(projectId), format),
    onSuccess: () => void message.success('接口资产已导出'),
    onError: (error) => void message.error(apiErrorMessage(error)),
  })

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setApiSearch(apiSearchInput.trim())
      setApiPage(1)
    }, 280)
    return () => window.clearTimeout(timer)
  }, [apiSearchInput])

  function selectProject(value: string) {
    selectContextProject(value)
    setApiSelection(null)
    setApiSearchInput('')
    setApiSearch('')
    setApiMethod(null)
    setApiPage(1)
  }

  async function addProject(input: CreateProjectInput) {
    await withErrorMessage(message.error, async () => {
      const project = await projectMutation.mutateAsync(input)
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
      selectProject(project.id)
    })
  }

  async function addEnvironment(input: CreateEnvironmentInput) {
    await withErrorMessage(message.error, async () => {
      const environment = await environmentMutation.mutateAsync(input)
      await invalidateRequestTargets(queryClient, projectId)
      setEnvironmentSelection(environment.id)
    })
  }

  async function editEnvironment(environmentId: string, input: Partial<CreateEnvironmentInput>) {
    await withErrorMessage(message.error, async () => {
      await updateEnvironmentMutation.mutateAsync({ environmentId, input })
      await invalidateRequestTargets(queryClient, projectId)
      void message.success('环境配置已更新')
    })
  }

  async function archiveEnvironment(targetEnvironmentId: string) {
    await withErrorMessage(message.error, async () => {
      await deleteEnvironmentMutation.mutateAsync(targetEnvironmentId)
      await invalidateRequestTargets(queryClient, projectId)
      if (targetEnvironmentId === environmentId) setEnvironmentSelection(null)
      void message.success('环境已删除，历史记录仍会保留')
    })
  }

  async function addApi(input: CreateApiInput) {
    await withErrorMessage(message.error, async () => {
      const definition = await apiMutation.mutateAsync(input)
      await queryClient.invalidateQueries({ queryKey: ['apis', projectId] })
      setApiSelection(definition.id)
    })
  }

  async function downloadFile(artifactId: string) {
    const artifact = artifacts.data?.items.find((item) => item.id === artifactId)
    if (!artifact) return
    await withErrorMessage(message.error, () => downloadArtifact(requiredId(projectId), artifact))
  }

  return {
    projects,
    projectId,
    canEdit,
    selectProject,
    environments,
    environmentId,
    environmentSelectionInvalid,
    environmentPlaceholder,
    environmentStatus,
    setEnvironmentSelection,
    apis,
    apiId,
    apiDetail,
    apiFolder,
    setApiFolder: (folder: string) => {
      setApiFolder(folder)
      setApiPage(1)
      setApiSelection(null)
    },
    selectedVersion,
    setSelectedVersion,
    ...targetState,
    versions,
    setApiSelection,
    apiSearchInput,
    setApiSearchInput,
    apiMethod,
    setApiMethod: (value: HttpMethod | null) => {
      setApiMethod(value)
      setApiPage(1)
    },
    apiPage,
    setApiPage,
    ...executions,
    artifacts,
    redactionMode,
    expectedStatus,
    setExpectedStatus,
    lastImport,
    clearImportResult: () => setLastImport(null),
    discoverImport: discoverImportMutation.mutateAsync,
    previewImport: previewImportMutation.mutateAsync,
    mergeImport: mergeImportMutation.mutateAsync,
    importing:
      discoverImportMutation.isPending ||
      previewImportMutation.isPending ||
      mergeImportMutation.isPending,
    uploadFile: uploadMutation.mutateAsync,
    uploading: uploadMutation.isPending,
    downloadFile,
    addProject,
    addEnvironment,
    editEnvironment,
    archiveEnvironment,
    updatingEnvironment: updateEnvironmentMutation.isPending,
    deletingEnvironment: deleteEnvironmentMutation.isPending,
    addApi,
    saveVersion: versionMutation.mutateAsync,
    savingVersion: versionMutation.isPending,
    renameApi: (targetApiId: string, name: string) =>
      renameMutation.mutateAsync({ apiId: targetApiId, name }),
    renamingApi: renameMutation.isPending,
    previewRequest: previewMutation.mutateAsync,
    previewing: previewMutation.isPending,
    exportApis: exportMutation.mutate,
    exporting: exportMutation.isPending,
    submitting: [
      projectMutation.isPending,
      environmentMutation.isPending,
      apiMutation.isPending,
      discoverImportMutation.isPending,
      previewImportMutation.isPending,
      mergeImportMutation.isPending,
      uploadMutation.isPending,
      versionMutation.isPending,
    ].some(Boolean),
  }
}

function useApiVersionQueries(
  projectId: string | null,
  apiId: string | null,
  selectedVersion: number | null,
) {
  const versions = useQuery({
    queryKey: ['api-versions', projectId, apiId],
    queryFn: () => listApiVersions(requiredId(projectId), requiredId(apiId)),
    enabled: Boolean(projectId && apiId),
  })
  const apiDetail = useQuery({
    queryKey: ['api-detail', projectId, apiId, selectedVersion],
    queryFn: () =>
      getApiDetail(requiredId(projectId), requiredId(apiId), selectedVersion ?? undefined),
    enabled: Boolean(projectId && apiId),
  })
  return { versions, apiDetail }
}

function useApiRequestTarget(
  projectId: string | null,
  apiId: string | null,
  environmentId: string | null,
  version: ApiVersion | undefined,
  environments: Environment[] | undefined,
) {
  const [serviceOverride, setServiceOverride] = useRouteScopedState<string | undefined>(
    projectId,
    apiId,
    undefined,
  )
  const inheritedService = useResolvedApiService(projectId, apiId, version)
  const [endpointVariant, setEndpointVariant] = useRouteScopedState<string | undefined>(
    projectId,
    endpointSelectionScope(apiId, environmentId, serviceOverride, inheritedService, environments),
    undefined,
  )
  const services = useQuery({
    queryKey: ['request-services', projectId],
    queryFn: () => listRequestServices(requiredId(projectId)),
    enabled: Boolean(projectId),
  })
  const endpoints = useQuery({
    queryKey: ['service-endpoints', projectId, environmentId],
    queryFn: () => listServiceEndpoints(requiredId(projectId), requiredId(environmentId)),
    enabled: Boolean(projectId && environmentId),
  })
  const targetPreview = useQuery({
    queryKey: [
      'api-target-preview',
      projectId,
      apiId,
      environmentId,
      version?.id,
      serviceOverride,
      endpointVariant,
    ],
    queryFn: () =>
      previewApi(requiredId(projectId), requiredId(apiId), requiredId(environmentId), {
        version: version?.version,
        serviceOverride,
        endpointVariant,
      }),
    enabled: Boolean(projectId && apiId && environmentId && version),
  })
  return {
    services,
    endpoints,
    serviceOverride,
    setServiceOverride,
    endpointVariant,
    setEndpointVariant,
    targetPreview,
    executionOptions: { version: version?.version, serviceOverride, endpointVariant },
  }
}

function useResolvedApiService(
  projectId: string | null,
  apiId: string | null,
  version: ApiVersion | undefined,
): ApiVersion['service_id'] {
  const [resolved, setResolved] = useState({ projectId, apiId, serviceId: version?.service_id })
  const isCurrentApi = resolved.projectId === projectId && resolved.apiId === apiId
  const serviceId = version ? version.service_id : isCurrentApi ? resolved.serviceId : undefined
  if (!isCurrentApi || resolved.serviceId !== serviceId) {
    setResolved({ projectId, apiId, serviceId })
  }
  return serviceId
}

function endpointSelectionScope(
  apiId: string | null,
  environmentId: string | null,
  serviceOverride: string | undefined,
  inheritedService: ApiVersion['service_id'],
  environments: Environment[] | undefined,
): string {
  const environment = environments?.find((item) => item.id === environmentId)
  const service = serviceOverride ?? inheritedService ?? environment?.default_service_id
  return JSON.stringify([apiId, environmentId, Boolean(serviceOverride), service])
}

function useProjectRedactionMode(projectId: string | null): 'off' | 'on' {
  const policy = useQuery({
    queryKey: ['project-redaction-policy', projectId],
    queryFn: () => getProjectRedactionPolicy(requiredId(projectId)),
    enabled: Boolean(projectId),
  })
  return policy.data?.mode === 'on' ? 'on' : 'off'
}

export type ApiConsoleDetail = ApiDetail

function canEditApiProject(project: Project | null, systemAdmin: boolean): boolean {
  if (!project) return false
  return systemAdmin || project.role === 'owner' || project.role === 'editor'
}

function requiredId(value: string | null): string {
  if (!value) throw new Error('缺少必要的资源标识')
  return value
}

async function withErrorMessage(
  showError: (content: string) => unknown,
  operation: () => Promise<void>,
) {
  try {
    await operation()
  } catch (error) {
    showError(apiErrorMessage(error))
    throw error
  }
}
