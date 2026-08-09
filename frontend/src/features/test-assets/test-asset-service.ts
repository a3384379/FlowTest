import {
  apiClient,
  type Page,
  type TestCase,
  type TestCaseDefinition,
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
): Promise<Page<TestCase>> {
  const response = await apiClient.get<Page<TestCase>>(`/projects/${projectId}/test-cases`, {
    params: { page: 1, page_size: 100, search: search || undefined, tag: tag || undefined },
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
): Promise<Page<TestSuite>> {
  const response = await apiClient.get<Page<TestSuite>>(`/projects/${projectId}/test-suites`, {
    params: { page: 1, page_size: 100, search: search || undefined, tag: tag || undefined },
  })
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
