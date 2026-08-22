import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { useState } from 'react'

import {
  apiErrorMessage,
  type ApiDetail,
  type ExecutionDetail,
  type ImportRun,
} from '../../lib/api'
import { useProjectContext } from '../projects/use-project-context'
import {
  createApi,
  createApiVersion,
  createEnvironment,
  createProject,
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
  type ImportPreviewInput,
  type ApiVersionInput,
  type CreateApiInput,
  type CreateEnvironmentInput,
  type CreateProjectInput,
} from './api-service'

export function useApiConsole() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { projects, projectId, selectProject: selectContextProject } = useProjectContext()
  const [environmentSelection, setEnvironmentSelection] = useState<string | null>(null)
  const [apiSelection, setApiSelection] = useState<string | null>(null)
  const [expectedStatus, setExpectedStatus] = useState(200)
  const [result, setResult] = useState<ExecutionDetail | null>(null)
  const [lastImport, setLastImport] = useState<ImportRun | null>(null)

  const environments = useQuery({
    queryKey: ['environments', projectId],
    queryFn: () => listEnvironments(requiredId(projectId)),
    enabled: Boolean(projectId),
  })
  const environmentId = selectedOrFirst(environmentSelection, environments.data)
  const apis = useQuery({
    queryKey: ['apis', projectId],
    queryFn: () => listApis(requiredId(projectId)),
    enabled: Boolean(projectId),
  })
  const apiId = selectedOrFirst(apiSelection, apis.data?.items)
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

  const projectMutation = useMutation({ mutationFn: createProject })
  const environmentMutation = useMutation({
    mutationFn: (input: CreateEnvironmentInput) => createEnvironment(requiredId(projectId), input),
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

  function selectProject(value: string) {
    selectContextProject(value)
    setEnvironmentSelection(null)
    setApiSelection(null)
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
    setEnvironmentSelection,
    apis,
    apiId,
    apiDetail,
    setApiSelection,
    history,
    artifacts,
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

export type ApiConsoleDetail = ApiDetail

type Identified = { id: string }

function selectedOrFirst(selection: string | null, items?: Identified[]): string | null {
  if (selection) return selection
  return items?.at(0)?.id ?? null
}

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
