import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useAssetCatalogScope } from './asset-catalog-scope'

import { listFolders } from '../projects/asset-service'
import { listEnvironments } from '../workflows/workflow-service'
import { useProjectContext } from '../projects/use-project-context'
import { getProjectPermission } from '../projects/project-service'
import type { TestCase, TestSuite, VersionDiff } from '../../lib/api'
import {
  cloneTestCase,
  cloneTestSuite,
  createTestCase,
  createTestSuite,
  diffTestCaseVersions,
  diffTestSuiteVersions,
  listTestCaseVersions,
  listTestCases,
  listTestSuiteVersions,
  listTestSuites,
  moveTestCases,
  moveTestSuites,
  publishTestCase,
  publishTestSuite,
  runTestCase,
  type RunCaseInput,
  type TestCaseDraftInput,
  type TestSuiteDraftInput,
  updateTestCase,
  updateTestSuite,
} from './test-asset-service'
import {
  listAssetWorkflows,
  listCaseCatalog,
  listAssetDirectoryCounts,
} from './asset-workspace-service'

type AssetBrowseOptions = {
  folder?: string
  loadCaseOptions?: boolean
}

function resolveBrowseOptions({ folder = 'all', loadCaseOptions = true }: AssetBrowseOptions) {
  return { folder, loadCaseOptions }
}

export function useTestAssets(options: AssetBrowseOptions = {}) {
  const { folder, loadCaseOptions } = resolveBrowseOptions(options)
  const queryClient = useQueryClient()
  const { projectId } = useProjectContext()
  const catalogScope = useAssetCatalogScope()
  const { casePage, suitePage, scope } = catalogScope
  const search = catalogScope.filters.search
  const tag = catalogScope.filters.tag
  const [diff, setDiff] = useState<VersionDiff | null>(null)
  const enabled = Boolean(projectId)
  const catalogEnabled = enabled && Boolean(scope)
  const cases = useQuery({
    queryKey: ['test-cases', projectId, search, tag, folder, casePage, scope],
    queryFn: () => listTestCases(projectId!, search, tag, casePage, 20, folder, scope!),
    enabled: catalogEnabled,
    refetchInterval: (query) =>
      query.state.data?.items.some((item) => activeResult(item.latest_run?.status)) ? 2000 : false,
  })
  const suites = useQuery({
    queryKey: ['test-suites', projectId, search, tag, folder, suitePage, scope],
    queryFn: () => listTestSuites(projectId!, search, tag, suitePage, 20, folder, scope!),
    enabled: catalogEnabled,
    refetchInterval: (query) =>
      activeResult(scope?.latest_result) && query.state.data?.items.length ? 2000 : false,
  })
  const active = catalogIsActive(cases.data, suites.data, scope)
  useCatalogCompletionRefresh(
    projectId,
    JSON.stringify([projectId, folder, casePage, suitePage, catalogScope.selectionKey]),
    active,
  )
  const workflows = useQuery({
    queryKey: ['workflows', projectId, 'asset-options'],
    queryFn: () => listAssetWorkflows(projectId!),
    enabled,
  })
  const environments = useQuery({
    queryKey: ['environments', projectId, 'asset-options'],
    queryFn: () => listEnvironments(projectId!),
    enabled,
  })
  const folders = useQuery({
    queryKey: ['folders', projectId, 'asset-options'],
    queryFn: () => listFolders(projectId!),
    enabled,
  })
  const caseOptions = useQuery({
    queryKey: ['test-case-options', projectId],
    queryFn: () => listCaseCatalog(projectId!, '', ''),
    enabled: enabled && loadCaseOptions,
  })
  const directoryCounts = useQuery({
    queryKey: ['asset-directory-counts', projectId, search, tag, scope],
    queryFn: () => listAssetDirectoryCounts(projectId!, search, tag, scope!),
    enabled: catalogEnabled,
    refetchInterval: active ? 2000 : false,
  })
  const permissions = useQuery({
    queryKey: ['project-permission', projectId],
    queryFn: () => getProjectPermission(projectId!),
    enabled,
  })

  async function invalidateAssets() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['test-cases', projectId] }),
      queryClient.invalidateQueries({ queryKey: ['test-suites', projectId] }),
      queryClient.invalidateQueries({ queryKey: ['test-asset', projectId] }),
      queryClient.invalidateQueries({ queryKey: ['test-case-versions', projectId] }),
      queryClient.invalidateQueries({ queryKey: ['test-suite-versions', projectId] }),
      queryClient.invalidateQueries({ queryKey: ['test-case-options', projectId] }),
      queryClient.invalidateQueries({ queryKey: ['asset-directory-counts', projectId] }),
      queryClient.invalidateQueries({ queryKey: ['asset-environment-options', projectId] }),
      queryClient.invalidateQueries({ queryKey: ['asset-environment-selected', projectId] }),
    ])
  }

  const saveCaseMutation = useMutation({
    mutationFn: ({ current, input }: { current: TestCase | null; input: TestCaseDraftInput }) =>
      current ? updateTestCase(projectId!, current.id, input) : createTestCase(projectId!, input),
    onSuccess: invalidateAssets,
  })
  const saveSuiteMutation = useMutation({
    mutationFn: ({ current, input }: { current: TestSuite | null; input: TestSuiteDraftInput }) =>
      current ? updateTestSuite(projectId!, current.id, input) : createTestSuite(projectId!, input),
    onSuccess: invalidateAssets,
  })
  const publishCaseMutation = useMutation({
    mutationFn: (caseId: string) => publishTestCase(projectId!, caseId),
    onSuccess: invalidateAssets,
  })
  const runCaseMutation = useMutation({
    mutationFn: ({ caseId, input }: { caseId: string; input: RunCaseInput }) =>
      runTestCase(projectId!, caseId, input),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ['test-case-runs', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['asset-run-history', projectId] }),
        invalidateAssets(),
      ]),
  })
  const publishSuiteMutation = useMutation({
    mutationFn: (suiteId: string) => publishTestSuite(projectId!, suiteId),
    onSuccess: invalidateAssets,
  })
  const cloneCaseMutation = useMutation({
    mutationFn: (item: TestCase) => cloneTestCase(projectId!, item.id, `${item.name} 副本`),
    onSuccess: invalidateAssets,
  })
  const cloneSuiteMutation = useMutation({
    mutationFn: (item: TestSuite) => cloneTestSuite(projectId!, item.id, `${item.name} 副本`),
    onSuccess: invalidateAssets,
  })
  const moveCasesMutation = useMutation({
    mutationFn: ({ ids, folderId }: { ids: string[]; folderId: string | null }) =>
      moveTestCases(projectId!, ids, folderId),
    onSuccess: invalidateAssets,
  })
  const moveSuitesMutation = useMutation({
    mutationFn: ({ ids, folderId }: { ids: string[]; folderId: string | null }) =>
      moveTestSuites(projectId!, ids, folderId),
    onSuccess: invalidateAssets,
  })

  async function loadCaseDiff(item: TestCase) {
    const versions = await listTestCaseVersions(projectId!, item.id)
    if (versions.length < 2) return setDiff(null)
    setDiff(
      await diffTestCaseVersions(projectId!, item.id, versions[1].version, versions[0].version),
    )
  }

  async function loadSuiteDiff(item: TestSuite) {
    const versions = await listTestSuiteVersions(projectId!, item.id)
    if (versions.length < 2) return setDiff(null)
    setDiff(
      await diffTestSuiteVersions(projectId!, item.id, versions[1].version, versions[0].version),
    )
  }

  return {
    projectId,
    search,
    tag,
    setSearch: (value: string) => catalogScope.setFilter('search', value),
    setTag: (value: string) => catalogScope.setFilter('tag', value),
    catalogScope,
    cases,
    suites,
    workflows,
    environments,
    folders,
    caseOptions,
    directoryCounts,
    refreshCatalog: () =>
      Promise.all([cases.refetch(), suites.refetch(), directoryCounts.refetch()]),
    permissions,
    canEdit: permissions.isSuccess && permissions.data.capabilities.includes('edit'),
    canExecute: permissions.isSuccess && permissions.data.capabilities.includes('execute'),
    diff,
    setDiff,
    saveCase: saveCaseMutation.mutateAsync,
    saveSuite: saveSuiteMutation.mutateAsync,
    publishCase: publishCaseMutation.mutateAsync,
    runCase: runCaseMutation.mutateAsync,
    runningCase: runCaseMutation.isPending,
    publishSuite: publishSuiteMutation.mutateAsync,
    cloneCase: cloneCaseMutation.mutateAsync,
    cloneSuite: cloneSuiteMutation.mutateAsync,
    moveCases: moveCasesMutation.mutateAsync,
    moveSuites: moveSuitesMutation.mutateAsync,
    loadCaseDiff,
    loadSuiteDiff,
    saving: saveCaseMutation.isPending || saveSuiteMutation.isPending,
  }
}

function activeResult(status?: string): boolean {
  return status === 'queued' || status === 'running'
}

function useCatalogCompletionRefresh(projectId: string | null, key: string, active: boolean) {
  const client = useQueryClient()
  const previous = useRef({ key, active })
  useEffect(() => {
    const completed = previous.current.key === key && previous.current.active && !active
    previous.current = { key, active }
    if (!completed) return
    for (const resource of ['test-cases', 'test-suites', 'asset-directory-counts']) {
      void client.invalidateQueries({ queryKey: [resource, projectId] })
    }
  }, [client, projectId, key, active])
}

function catalogIsActive(
  cases: { items: TestCase[] } | undefined,
  suites: { items: TestSuite[] } | undefined,
  scope: ReturnType<typeof useAssetCatalogScope>['scope'],
): boolean {
  return Boolean(
    cases?.items.some((item) => activeResult(item.latest_run?.status)) ||
    (activeResult(scope?.latest_result) && suites?.items.length),
  )
}
