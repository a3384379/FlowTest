import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { listFolders } from '../projects/asset-service'
import { listEnvironments, listWorkflows } from '../workflows/workflow-service'
import { useProjectContext } from '../projects/use-project-context'
import type { TestCase, TestSuite, VersionDiff } from '../../lib/api'
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
  type TestCaseDraftInput,
  type TestSuiteDraftInput,
  updateTestCase,
  updateTestSuite,
} from './test-asset-service'

export function useTestAssets() {
  const queryClient = useQueryClient()
  const { projectId } = useProjectContext()
  const [search, setSearch] = useState('')
  const [tag, setTag] = useState('')
  const [diff, setDiff] = useState<VersionDiff | null>(null)
  const enabled = Boolean(projectId)
  const cases = useQuery({
    queryKey: ['test-cases', projectId, search, tag],
    queryFn: () => listTestCases(projectId!, search, tag),
    enabled,
  })
  const suites = useQuery({
    queryKey: ['test-suites', projectId, search, tag],
    queryFn: () => listTestSuites(projectId!, search, tag),
    enabled,
  })
  const workflows = useQuery({
    queryKey: ['workflows', projectId, 'asset-options'],
    queryFn: () => listWorkflows(projectId!),
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

  async function invalidateAssets() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['test-cases', projectId] }),
      queryClient.invalidateQueries({ queryKey: ['test-suites', projectId] }),
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
    setSearch,
    setTag,
    cases,
    suites,
    workflows,
    environments,
    folders,
    diff,
    setDiff,
    saveCase: saveCaseMutation.mutateAsync,
    saveSuite: saveSuiteMutation.mutateAsync,
    publishCase: publishCaseMutation.mutateAsync,
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
