import { apiClient, type ContractRun, type GeneratedContractCase, type Page } from '../../lib/api'

export async function listContractRuns(projectId: string): Promise<Page<ContractRun>> {
  const response = await apiClient.get<Page<ContractRun>>(`/projects/${projectId}/contract-runs`, {
    params: { page: 1, page_size: 100 },
  })
  return response.data
}

export async function createContractRun(
  projectId: string,
  file: File,
  baselineRunId: string | null,
): Promise<ContractRun> {
  const form = new FormData()
  form.append('document', file)
  form.append('source_name', file.name)
  if (baselineRunId) form.append('baseline_run_id', baselineRunId)
  const response = await apiClient.post<ContractRun>(`/projects/${projectId}/contract-runs`, form)
  return response.data
}

export async function listGeneratedContractCases(
  projectId: string,
  runId: string,
): Promise<Page<GeneratedContractCase>> {
  const response = await apiClient.get<Page<GeneratedContractCase>>(
    `/projects/${projectId}/contract-runs/${runId}/generated-cases`,
    { params: { page: 1, page_size: 100 } },
  )
  return response.data
}

export async function reviewGeneratedContractCase(
  projectId: string,
  runId: string,
  caseId: string,
  decision: 'accept' | 'reject',
  input: { name?: string; definition?: Record<string, unknown>; note: string },
): Promise<GeneratedContractCase> {
  const response = await apiClient.post<GeneratedContractCase>(
    `/projects/${projectId}/contract-runs/${runId}/generated-cases/${caseId}/${decision}`,
    input,
  )
  return response.data
}
