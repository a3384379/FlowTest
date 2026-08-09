import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient, type TestCaseDefinition, type TestSuiteItem } from '../../lib/api'
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

const caseDefinition: TestCaseDefinition = {
  workflow_id: 'workflow-1',
  workflow_version: 2,
  environment_id: 'environment-1',
  runtime_variables: { region: 'cn' },
  runtime_headers: { 'X-Trace': 'test' },
}

const suiteItems: TestSuiteItem[] = [{ test_case_id: 'case-1', test_case_version: 2 }]

describe('test asset service', () => {
  afterEach(() => vi.restoreAllMocks())

  it('maps case operations to versioned project resources', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: [] })
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { updated: 2 } })
    const patch = vi.spyOn(apiClient, 'patch').mockResolvedValue({ data: {} })
    const draft = {
      name: '登录用例',
      description: '登录回归',
      folderId: 'folder-1',
      tags: ['smoke'],
      isTemplate: true,
      definition: caseDefinition,
    }

    await listTestCases('project-1', '登录', 'smoke')
    await listTestCases('project-1', '', '')
    await createTestCase('project-1', draft)
    await updateTestCase('project-1', 'case-1', draft)
    await publishTestCase('project-1', 'case-1')
    await cloneTestCase('project-1', 'case-1', '登录用例副本')
    expect(await moveTestCases('project-1', ['case-1', 'case-2'], 'folder-2')).toBe(2)
    await listTestCaseVersions('project-1', 'case-1')
    await diffTestCaseVersions('project-1', 'case-1', 1, 2)

    expect(get).toHaveBeenNthCalledWith(1, '/projects/project-1/test-cases', {
      params: { page: 1, page_size: 100, search: '登录', tag: 'smoke' },
    })
    expect(get).toHaveBeenNthCalledWith(2, '/projects/project-1/test-cases', {
      params: { page: 1, page_size: 100, search: undefined, tag: undefined },
    })
    expect(post).toHaveBeenCalledWith('/projects/project-1/test-cases', {
      name: draft.name,
      description: draft.description,
      folder_id: draft.folderId,
      tags: draft.tags,
      is_template: true,
      definition: caseDefinition,
    })
    expect(patch).toHaveBeenCalledWith('/projects/project-1/test-cases/case-1', expect.anything())
    expect(post).toHaveBeenCalledWith('/projects/project-1/test-cases/case-1/versions', {
      change_note: 'Web 发布',
    })
    expect(post).toHaveBeenCalledWith('/projects/project-1/test-cases/case-1/clone', {
      name: '登录用例副本',
    })
    expect(post).toHaveBeenCalledWith('/projects/project-1/test-cases/bulk-move', {
      asset_ids: ['case-1', 'case-2'],
      folder_id: 'folder-2',
    })
    expect(get).toHaveBeenCalledWith('/projects/project-1/test-cases/case-1/versions')
    expect(get).toHaveBeenCalledWith('/projects/project-1/test-cases/case-1/versions/1/diff/2')
  })

  it('maps suite operations and omits empty search filters', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: [] })
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { updated: 1 } })
    const patch = vi.spyOn(apiClient, 'patch').mockResolvedValue({ data: {} })
    const draft = {
      name: '冒烟套件',
      description: '核心路径',
      folderId: null,
      tags: ['critical'],
      items: suiteItems,
    }

    await listTestSuites('project-1', '', '')
    await createTestSuite('project-1', draft)
    await updateTestSuite('project-1', 'suite-1', draft)
    await publishTestSuite('project-1', 'suite-1')
    await cloneTestSuite('project-1', 'suite-1', '冒烟套件副本')
    expect(await moveTestSuites('project-1', ['suite-1'], null)).toBe(1)
    await listTestSuiteVersions('project-1', 'suite-1')
    await diffTestSuiteVersions('project-1', 'suite-1', 2, 3)

    expect(get).toHaveBeenNthCalledWith(1, '/projects/project-1/test-suites', {
      params: { page: 1, page_size: 100, search: undefined, tag: undefined },
    })
    expect(post).toHaveBeenCalledWith('/projects/project-1/test-suites', {
      name: draft.name,
      description: draft.description,
      folder_id: null,
      tags: draft.tags,
      definition: { items: suiteItems },
    })
    expect(patch).toHaveBeenCalledWith('/projects/project-1/test-suites/suite-1', {
      name: draft.name,
      description: draft.description,
      folder_id: null,
      tags: draft.tags,
      definition: { items: suiteItems },
    })
    expect(post).toHaveBeenCalledWith('/projects/project-1/test-suites/suite-1/versions', {
      change_note: 'Web 发布',
    })
    expect(post).toHaveBeenCalledWith('/projects/project-1/test-suites/suite-1/clone', {
      name: '冒烟套件副本',
    })
    expect(post).toHaveBeenCalledWith('/projects/project-1/test-suites/bulk-move', {
      asset_ids: ['suite-1'],
      folder_id: null,
    })
    expect(get).toHaveBeenCalledWith('/projects/project-1/test-suites/suite-1/versions')
    expect(get).toHaveBeenCalledWith('/projects/project-1/test-suites/suite-1/versions/2/diff/3')
  })
})
