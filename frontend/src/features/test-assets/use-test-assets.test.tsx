import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { TestCase, TestSuite, VersionDiff } from '../../lib/api'
import { listFolders } from '../projects/asset-service'
import { useProjectContext } from '../projects/use-project-context'
import { listEnvironments, listWorkflows } from '../workflows/workflow-service'
import {
  cloneTestCase,
  cloneTestSuite,
  createTestCase,
  createTestSuite,
  diffTestCaseVersions,
  diffTestSuiteVersions,
  listTestCases,
  listTestCaseVersions,
  listTestSuites,
  listTestSuiteVersions,
  moveTestCases,
  moveTestSuites,
  publishTestCase,
  publishTestSuite,
  updateTestCase,
  updateTestSuite,
} from './test-asset-service'
import { useTestAssets } from './use-test-assets'

vi.mock('../projects/use-project-context')
vi.mock('../projects/asset-service')
vi.mock('../workflows/workflow-service')
vi.mock('./test-asset-service')

const testCase = {
  id: 'case-1',
  name: '登录用例',
  current_version: 2,
} as TestCase
const testSuite = {
  id: 'suite-1',
  name: '冒烟套件',
  current_version: 2,
} as TestSuite
const diff: VersionDiff = {
  from_version: 1,
  to_version: 2,
  changes: [{ path: 'name', before: '旧', after: '新' }],
}

describe('useTestAssets', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(useProjectContext).mockReturnValue({ projectId: 'project-1' } as never)
    vi.mocked(listTestCases).mockResolvedValue(page([testCase]))
    vi.mocked(listTestSuites).mockResolvedValue(page([testSuite]))
    vi.mocked(listWorkflows).mockResolvedValue(page([]))
    vi.mocked(listEnvironments).mockResolvedValue([])
    vi.mocked(listFolders).mockResolvedValue([])
    vi.mocked(createTestCase).mockResolvedValue(testCase)
    vi.mocked(updateTestCase).mockResolvedValue(testCase)
    vi.mocked(createTestSuite).mockResolvedValue(testSuite)
    vi.mocked(updateTestSuite).mockResolvedValue(testSuite)
    vi.mocked(publishTestCase).mockResolvedValue({} as never)
    vi.mocked(publishTestSuite).mockResolvedValue({} as never)
    vi.mocked(cloneTestCase).mockResolvedValue(testCase)
    vi.mocked(cloneTestSuite).mockResolvedValue(testSuite)
    vi.mocked(moveTestCases).mockResolvedValue(1)
    vi.mocked(moveTestSuites).mockResolvedValue(1)
    vi.mocked(diffTestCaseVersions).mockResolvedValue(diff)
    vi.mocked(diffTestSuiteVersions).mockResolvedValue(diff)
  })

  it('loads project assets and forwards search and tag filters', async () => {
    const { result } = renderAssetsHook()
    await waitFor(() => expect(result.current.cases.isSuccess).toBe(true))

    act(() => {
      result.current.setSearch('登录')
      result.current.setTag('smoke')
    })
    await waitFor(() => expect(listTestCases).toHaveBeenCalledWith('project-1', '登录', 'smoke'))
    await waitFor(() => expect(result.current.cases.data?.items).toEqual([testCase]))
    await waitFor(() => expect(result.current.suites.data?.items).toEqual([testSuite]))
  })

  it('creates and updates case and suite drafts through one stable hook', async () => {
    const { result } = renderAssetsHook()
    await waitFor(() => expect(result.current.cases.isSuccess).toBe(true))
    const caseInput = {
      name: '用例',
      description: '',
      folderId: null,
      tags: [],
      isTemplate: false,
      definition: {
        workflow_id: 'workflow-1',
        workflow_version: null,
        environment_id: 'environment-1',
        runtime_variables: {},
        runtime_headers: {},
      },
    }
    const suiteInput = {
      name: '套件',
      description: '',
      folderId: null,
      tags: [],
      items: [{ test_case_id: 'case-1', test_case_version: 2 }],
    }

    await act(() => result.current.saveCase({ current: null, input: caseInput }))
    await act(() => result.current.saveCase({ current: testCase, input: caseInput }))
    await act(() => result.current.saveSuite({ current: null, input: suiteInput }))
    await act(() => result.current.saveSuite({ current: testSuite, input: suiteInput }))

    expect(createTestCase).toHaveBeenCalledWith('project-1', caseInput)
    expect(updateTestCase).toHaveBeenCalledWith('project-1', testCase.id, caseInput)
    expect(createTestSuite).toHaveBeenCalledWith('project-1', suiteInput)
    expect(updateTestSuite).toHaveBeenCalledWith('project-1', testSuite.id, suiteInput)
  })

  it('publishes, clones, moves, and compares immutable versions', async () => {
    const { result } = renderAssetsHook()
    await waitFor(() => expect(result.current.cases.isSuccess).toBe(true))
    vi.mocked(listTestCaseVersions)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([{ version: 2 }, { version: 1 }] as never)
    vi.mocked(listTestSuiteVersions)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([{ version: 3 }, { version: 2 }] as never)

    await act(() => result.current.publishCase(testCase.id))
    await act(() => result.current.publishSuite(testSuite.id))
    await act(() => result.current.cloneCase(testCase))
    await act(() => result.current.cloneSuite(testSuite))
    await act(() => result.current.moveCases({ ids: [testCase.id], folderId: null }))
    await act(() => result.current.moveSuites({ ids: [testSuite.id], folderId: 'folder-1' }))
    await act(() => result.current.loadCaseDiff(testCase))
    expect(result.current.diff).toBeNull()
    await act(() => result.current.loadCaseDiff(testCase))
    expect(result.current.diff).toEqual(diff)
    await act(() => result.current.loadSuiteDiff(testSuite))
    expect(result.current.diff).toBeNull()
    await act(() => result.current.loadSuiteDiff(testSuite))

    expect(publishTestCase).toHaveBeenCalledWith('project-1', testCase.id)
    expect(publishTestSuite).toHaveBeenCalledWith('project-1', testSuite.id)
    expect(cloneTestCase).toHaveBeenCalledWith('project-1', testCase.id, '登录用例 副本')
    expect(cloneTestSuite).toHaveBeenCalledWith('project-1', testSuite.id, '冒烟套件 副本')
    expect(moveTestCases).toHaveBeenCalledWith('project-1', [testCase.id], null)
    expect(moveTestSuites).toHaveBeenCalledWith('project-1', [testSuite.id], 'folder-1')
    expect(diffTestCaseVersions).toHaveBeenCalledWith('project-1', testCase.id, 1, 2)
    expect(diffTestSuiteVersions).toHaveBeenCalledWith('project-1', testSuite.id, 2, 3)
  })
})

function renderAssetsHook() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return renderHook(() => useTestAssets(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    ),
  })
}

function page<T>(items: T[]) {
  return { items, total: items.length, page: 1, page_size: 100 }
}
