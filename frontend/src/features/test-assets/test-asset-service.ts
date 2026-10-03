import {
  apiClient,
  type Page,
  type TestCase,
  type TestCaseDefinition,
  type TestCaseRun,
  type TestCaseVersion,
  type TestSuite,
  type TestSuiteItem,
  type TestSuiteVersion,
  type VersionDiff,
} from '../../lib/api'

export type TestCaseDraftInput = {
  name: string
  description: string
  folderId: string | null
  tags: string[]
  isTemplate: boolean
  definition: TestCaseDefinition
}

export type TestSuiteDraftInput = {
  name: string
  description: string
  folderId: string | null
  tags: string[]
  items: TestSuiteItem[]
}

export async function listTestCases(
  projectId: string,
  search: string,
  tag: string,
  page = 1,
  pageSize = 20,
  folder?: string,
): Promise<Page<TestCase>> {
  const response = await apiClient.get<Page<TestCase>>(`/projects/${projectId}/test-cases`, {
    params: {
      page,
      page_size: pageSize,
      search: search || undefined,
      tag: tag || undefined,
      ...assetFolderFilter(folder),
    },
  })
  return response.data
}

export async function createTestCase(
  projectId: string,
  input: TestCaseDraftInput,
): Promise<TestCase> {
  const response = await apiClient.post<TestCase>(`/projects/${projectId}/test-cases`, {
    name: input.name,
    description: input.description,
    folder_id: input.folderId,
    tags: input.tags,
    is_template: input.isTemplate,
    definition: input.definition,
  })
  return response.data
}

export async function getTestCase(projectId: string, caseId: string): Promise<TestCase> {
  const response = await apiClient.get<TestCase>(`/projects/${projectId}/test-cases/${caseId}`)
  return response.data
}

export async function updateTestCase(
  projectId: string,
  caseId: string,
  input: TestCaseDraftInput,
): Promise<TestCase> {
  const response = await apiClient.patch<TestCase>(`/projects/${projectId}/test-cases/${caseId}`, {
    name: input.name,
    description: input.description,
    folder_id: input.folderId,
    tags: input.tags,
    is_template: input.isTemplate,
    definition: input.definition,
  })
  return response.data
}

export async function publishTestCase(projectId: string, caseId: string): Promise<TestCaseVersion> {
  const response = await apiClient.post<TestCaseVersion>(
    `/projects/${projectId}/test-cases/${caseId}/versions`,
    { change_note: 'Web 发布' },
  )
  return response.data
}

export async function cloneTestCase(
  projectId: string,
  caseId: string,
  name: string,
): Promise<TestCase> {
  const response = await apiClient.post<TestCase>(
    `/projects/${projectId}/test-cases/${caseId}/clone`,
    { name },
  )
  return response.data
}

export async function moveTestCases(
  projectId: string,
  caseIds: string[],
  folderId: string | null,
): Promise<number> {
  const response = await apiClient.post<{ updated: number }>(
    `/projects/${projectId}/test-cases/bulk-move`,
    { asset_ids: caseIds, folder_id: folderId },
  )
  return response.data.updated
}

export async function listTestCaseVersions(
  projectId: string,
  caseId: string,
): Promise<TestCaseVersion[]> {
  const response = await apiClient.get<TestCaseVersion[]>(
    `/projects/${projectId}/test-cases/${caseId}/versions`,
  )
  return response.data
}

export type RunCaseInput = {
  source: 'published' | 'draft'
  version?: number
  publish_draft?: boolean
  expected_draft_fingerprint?: string
  runtime_variables?: Record<string, string>
  runtime_headers?: Record<string, string>
}

export async function runTestCase(
  projectId: string,
  caseId: string,
  input: RunCaseInput,
): Promise<TestCaseRun> {
  const response = await apiClient.post<TestCaseRun>(
    `/projects/${projectId}/test-cases/${caseId}/runs`,
    input,
    { headers: { 'Idempotency-Key': crypto.randomUUID() } },
  )
  return response.data
}

export async function listLatestTestCaseRuns(
  projectId: string,
  caseIds: string[],
): Promise<TestCaseRun[]> {
  if (!caseIds.length) return []
  const params = new URLSearchParams()
  caseIds.forEach((id) => params.append('case_ids', id))
  const response = await apiClient.get<TestCaseRun[]>(
    `/projects/${projectId}/test-cases/runs/latest`,
    { params },
  )
  return response.data
}

export async function addCaseToPlan(
  projectId: string,
  planId: string,
  caseId: string,
  version: number,
): Promise<void> {
  await apiClient.post(`/projects/${projectId}/test-plans/${planId}/items`, {
    target_type: 'case',
    target_id: caseId,
    target_version: version,
  })
}

export async function diffTestCaseVersions(
  projectId: string,
  caseId: string,
  fromVersion: number,
  toVersion: number,
): Promise<VersionDiff> {
  const response = await apiClient.get<VersionDiff>(
    `/projects/${projectId}/test-cases/${caseId}/versions/${fromVersion}/diff/${toVersion}`,
  )
  return response.data
}

export async function listTestSuites(
  projectId: string,
  search: string,
  tag: string,
  page = 1,
  pageSize = 20,
  folder?: string,
): Promise<Page<TestSuite>> {
  const response = await apiClient.get<Page<TestSuite>>(`/projects/${projectId}/test-suites`, {
    params: {
      page,
      page_size: pageSize,
      search: search || undefined,
      tag: tag || undefined,
      ...assetFolderFilter(folder),
    },
  })
  return response.data
}

function assetFolderFilter(folder?: string): { folder_id?: string; unfiled?: boolean } {
  if (!folder || folder === 'all') return {}
  return folder === 'unfiled' ? { unfiled: true } : { folder_id: folder }
}

export async function getTestSuite(projectId: string, suiteId: string): Promise<TestSuite> {
  const response = await apiClient.get<TestSuite>(`/projects/${projectId}/test-suites/${suiteId}`)
  return response.data
}

export async function createTestSuite(
  projectId: string,
  input: TestSuiteDraftInput,
): Promise<TestSuite> {
  const response = await apiClient.post<TestSuite>(`/projects/${projectId}/test-suites`, {
    name: input.name,
    description: input.description,
    folder_id: input.folderId,
    tags: input.tags,
    definition: { items: input.items },
  })
  return response.data
}

export async function updateTestSuite(
  projectId: string,
  suiteId: string,
  input: TestSuiteDraftInput,
): Promise<TestSuite> {
  const response = await apiClient.patch<TestSuite>(
    `/projects/${projectId}/test-suites/${suiteId}`,
    {
      name: input.name,
      description: input.description,
      folder_id: input.folderId,
      tags: input.tags,
      definition: { items: input.items },
    },
  )
  return response.data
}

export async function publishTestSuite(
  projectId: string,
  suiteId: string,
): Promise<TestSuiteVersion> {
  const response = await apiClient.post<TestSuiteVersion>(
    `/projects/${projectId}/test-suites/${suiteId}/versions`,
    { change_note: 'Web 发布' },
  )
  return response.data
}

export async function cloneTestSuite(
  projectId: string,
  suiteId: string,
  name: string,
): Promise<TestSuite> {
  const response = await apiClient.post<TestSuite>(
    `/projects/${projectId}/test-suites/${suiteId}/clone`,
    { name },
  )
  return response.data
}

export async function moveTestSuites(
  projectId: string,
  suiteIds: string[],
  folderId: string | null,
): Promise<number> {
  const response = await apiClient.post<{ updated: number }>(
    `/projects/${projectId}/test-suites/bulk-move`,
    { asset_ids: suiteIds, folder_id: folderId },
  )
  return response.data.updated
}

export async function listTestSuiteVersions(
  projectId: string,
  suiteId: string,
): Promise<TestSuiteVersion[]> {
  const response = await apiClient.get<TestSuiteVersion[]>(
    `/projects/${projectId}/test-suites/${suiteId}/versions`,
  )
  return response.data
}

export async function diffTestSuiteVersions(
  projectId: string,
  suiteId: string,
  fromVersion: number,
  toVersion: number,
): Promise<VersionDiff> {
  const response = await apiClient.get<VersionDiff>(
    `/projects/${projectId}/test-suites/${suiteId}/versions/${fromVersion}/diff/${toVersion}`,
  )
  return response.data
}
