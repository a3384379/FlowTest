import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'

import { apiErrorMessage } from '../../lib/api'
import { useProjectContext } from '../projects/use-project-context'
import {
  createContractService,
  getCompatibilityMatrix,
  getContractHubSummary,
  getServiceGraph,
  importPactContract,
  listContractServices,
  listDeploymentChecks,
  listPactContracts,
  runDeploymentCheck,
  verifyPactProvider,
  type PactImportInput,
} from './contract-hub-service'
import { createContractRun, listContractRuns } from './contract-service'

export function useContractHub(providerServiceId: string | null) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { projectId } = useProjectContext()
  const enabled = Boolean(projectId)
  const services = useQuery({
    queryKey: ['contract-services', projectId],
    queryFn: () => listContractServices(required(projectId)),
    enabled,
  })
  const pacts = useQuery({
    queryKey: ['pact-contracts', projectId],
    queryFn: () => listPactContracts(required(projectId)),
    enabled,
  })
  const openapiRuns = useQuery({
    queryKey: ['contract-runs', projectId],
    queryFn: () => listContractRuns(required(projectId)),
    enabled,
  })
  const summary = useQuery({
    queryKey: ['contract-hub-summary', projectId],
    queryFn: () => getContractHubSummary(required(projectId)),
    enabled,
  })
  const graph = useQuery({
    queryKey: ['contract-service-graph', projectId],
    queryFn: () => getServiceGraph(required(projectId)),
    enabled,
  })
  const matrix = useQuery({
    queryKey: ['contract-compatibility', projectId, providerServiceId],
    queryFn: () => getCompatibilityMatrix(required(projectId), required(providerServiceId)),
    enabled: enabled && Boolean(providerServiceId),
  })
  const checks = useQuery({
    queryKey: ['deployment-checks', projectId],
    queryFn: () => listDeploymentChecks(required(projectId)),
    enabled,
  })
  const createService = useMutation({
    mutationFn: (input: { service_key: string; display_name: string; description: string }) =>
      createContractService(required(projectId), input),
  })
  const importPact = useMutation({
    mutationFn: (input: PactImportInput) => importPactContract(required(projectId), input),
  })
  const importOpenapi = useMutation({
    mutationFn: (input: { file: File; providerServiceId: string; providerVersion: string }) =>
      createContractRun(required(projectId), input.file, null, {
        providerServiceId: input.providerServiceId,
        providerVersion: input.providerVersion,
      }),
  })
  const verify = useMutation({
    mutationFn: (input: { pactId: string; providerVersion: string; targetBaseUrl: string }) =>
      verifyPactProvider(required(projectId), input),
  })
  const check = useMutation({
    mutationFn: (input: { providerServiceId: string; providerVersion: string }) =>
      runDeploymentCheck(required(projectId), input),
  })

  async function withFeedback<T>(action: () => Promise<T>, successText: string): Promise<boolean> {
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

  async function refresh(): Promise<void> {
    await queryClient.invalidateQueries({ queryKey: ['contract-services', projectId] })
    await queryClient.invalidateQueries({ queryKey: ['pact-contracts', projectId] })
    await queryClient.invalidateQueries({ queryKey: ['contract-runs', projectId] })
    await queryClient.invalidateQueries({ queryKey: ['contract-hub-summary', projectId] })
    await queryClient.invalidateQueries({ queryKey: ['contract-service-graph', projectId] })
    await queryClient.invalidateQueries({ queryKey: ['contract-compatibility', projectId] })
    await queryClient.invalidateQueries({ queryKey: ['deployment-checks', projectId] })
  }

  return {
    projectId,
    services,
    pacts,
    openapiRuns,
    summary,
    graph,
    matrix,
    checks,
    createService: (input: { service_key: string; display_name: string; description: string }) =>
      withFeedback(() => createService.mutateAsync(input), '服务已登记'),
    importPact: (input: PactImportInput) =>
      withFeedback(() => importPact.mutateAsync(input), 'Pact 契约已导入'),
    importOpenapi: (input: { file: File; providerServiceId: string; providerVersion: string }) =>
      withFeedback(() => importOpenapi.mutateAsync(input), 'OpenAPI 契约已绑定提供方'),
    verifyProvider: (input: { pactId: string; providerVersion: string; targetBaseUrl: string }) =>
      withFeedback(() => verify.mutateAsync(input), '提供方验证已完成并保存证据'),
    runCheck: (input: { providerServiceId: string; providerVersion: string }) =>
      withFeedback(() => check.mutateAsync(input), '部署兼容判断已保存'),
    importing: importPact.isPending || importOpenapi.isPending,
    creatingService: createService.isPending,
    verifying: verify.isPending,
    checking: check.isPending,
  }
}

function required(value: string | null): string {
  if (!value) throw new Error('请选择项目')
  return value
}
