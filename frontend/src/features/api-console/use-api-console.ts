import { useEnvironmentSelection } from '../projects/environment-selection'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useEffect, useState } from 'react'

import {
  apiErrorMessage,
  type ApiDetail,
  type ExecutionDetail,
  type ImportRun,
} from '../../lib/api'
import { useProjectContext } from '../projects/use-project-context'
import { useRouteScopedSelection } from '../../lib/use-route-scoped-state'
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
  executeApi,
  exportApis,
  getApiDetail,
  listApis,
  listArtifacts,
  listEnvironments,
  listExecutions,
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

export function useApiConsole(initialApiId?: string) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { projects, projectId, selectProject: selectContextProject } = useProjectContext()
  const [apiSelection, setApiSelection] = useRouteScopedSelection(projectId, initialApiId ?? null)
  const [apiSearchInput, setApiSearchInput] = useState('')
  const [apiSearch, setApiSearch] = useState('')
  const [apiMethod, setApiMethod] = useState<HttpMethod | null>(null)
  const [apiPage, setApiPage] = useState(1)
  const [expectedStatus, setExpectedStatus] = useState(200)
  const [result, setResult] = useState<ExecutionDetail | null>(null)
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
    queryKey: ['apis', projectId, apiPage, apiSearch, apiMethod],
    queryFn: () =>
      listApis(requiredId(projectId), {
        page: apiPage,
        pageSize: 50,
        search: apiSearch,
        method: apiMethod ?? undefined,
      }),
    enabled: Boolean(projectId),
  })
  const apiId = apiSelection ?? apis.data?.items.at(0)?.id ?? null
  const apiDetail = useQuery({
    queryKey: ['api-detail', projectId, apiId],
    queryFn: () => getApiDetail(requiredId(projectId), requiredId(apiId)),
    enabled: Boolean(projectId && apiId),
  })
  const history = useQuery({
    queryKey: ['executions', projectId],
    queryFn: () => listExecutions(requiredId(projectId)),
    enabled: Boolean(projectId),
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
  const executionMutation = useMutation({
    mutationFn: () =>
      executeApi(
        requiredId(projectId),
        requiredId(apiId),
        requiredId(environmentId),
        expectedStatus,
        apiDetail.data?.version.assertions,
      ),
    onSuccess: async (value) => {
      setResult(value)
      await queryClient.invalidateQueries({ queryKey: ['executions', projectId] })
      void message.success(executionMessage(value))
    },
    onError: (error) => void message.error(apiErrorMessage(error)),
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
      ])
      void message.success('接口新版本已保存')
    },
    onError: (error) => void message.error(apiErrorMessage(error)),
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
      previewApi(requiredId(projectId), requiredId(apiId), requiredId(environmentId)),
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
    setResult(null)
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
      await queryClient.invalidateQueries({ queryKey: ['environments', projectId] })
      setEnvironmentSelection(environment.id)
    })
  }

  async function editEnvironment(environmentId: string, input: Partial<CreateEnvironmentInput>) {
    await withErrorMessage(message.error, async () => {
      await updateEnvironmentMutation.mutateAsync({ environmentId, input })
      await queryClient.invalidateQueries({ queryKey: ['environments', projectId] })
      void message.success('环境配置已更新')
    })
  }

  async function archiveEnvironment(targetEnvironmentId: string) {
    await withErrorMessage(message.error, async () => {
      await deleteEnvironmentMutation.mutateAsync(targetEnvironmentId)
      await queryClient.invalidateQueries({ queryKey: ['environments', projectId] })
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
    history,
    artifacts,
    redactionMode,
    expectedStatus,
    setExpectedStatus,
    result,
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
    execute: executionMutation.mutate,
    executing: executionMutation.isPending,
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

function useProjectRedactionMode(projectId: string | null): 'off' | 'on' {
  const policy = useQuery({
    queryKey: ['project-redaction-policy', projectId],
    queryFn: () => getProjectRedactionPolicy(requiredId(projectId)),
    enabled: Boolean(projectId),
  })
  return policy.data?.mode === 'on' ? 'on' : 'off'
}

export type ApiConsoleDetail = ApiDetail

function requiredId(value: string | null): string {
  if (!value) throw new Error('缺少必要的资源标识')
  return value
}

function executionMessage(result: ExecutionDetail): string {
  return result.execution.status === 'passed' ? '接口执行通过' : '接口执行完成'
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
