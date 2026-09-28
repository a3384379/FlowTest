import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { App as AntdApp } from 'antd'
import { describe, expect, it, vi } from 'vitest'

import type { Environment, Folder, TestCase, TestSuite, Workflow } from '../lib/api'
import * as assetService from '../features/test-assets/test-asset-service'
import {
  caseInput,
  editorKey,
  folderItems,
  pageItems,
  suiteInput,
  validateEntries,
} from '../features/test-assets/test-asset-view-model'
import {
  AssetPane,
  CaseDialog,
  CaseTable,
  DiffDialog,
  RunCaseDialog,
  SuiteDialog,
  SuiteTable,
} from './TestAssetsPage'

const workflow: Workflow = {
  id: 'workflow-1',
  project_id: 'project-1',
  folder_id: null,
  name: '登录工作流',
  description: '',
  draft_definition: {
    schema_version: '1.0',
    variables: {},
    nodes: [],
    edges: [],
    settings: { fail_fast: true, concurrency: 20, default_timeout_seconds: 30 },
  },
  draft_revision: 1,
  current_version: 2,
  created_at: '2026-08-10T00:00:00Z',
  updated_at: '2026-08-10T00:00:00Z',
}

const environment: Environment = {
  id: 'environment-1',
  project_id: 'project-1',
  name: '测试环境',
  base_url: 'https://api.example.com',
  variables: {},
  headers: {},
}

const folder: Folder = {
  id: 'folder-1',
  project_id: 'project-1',
  parent_id: null,
  name: '核心回归',
  created_by_id: 'user-1',
  created_at: '2026-08-10T00:00:00Z',
  updated_at: '2026-08-10T00:00:00Z',
}

const testCase: TestCase = {
  id: 'case-1',
  project_id: 'project-1',
  folder_id: null,
  name: '登录用例',
  description: '登录主路径',
  tags: ['smoke'],
  is_template: true,
  draft_definition: {
    workflow_id: workflow.id,
    workflow_version: 2,
    environment_id: environment.id,
    runtime_variables: {},
    runtime_headers: {},
  },
  current_version: 2,
  created_by_id: 'user-1',
  created_at: '2026-08-10T00:00:00Z',
  updated_at: '2026-08-10T00:00:00Z',
}

const testSuite: TestSuite = {
  id: 'suite-1',
  project_id: 'project-1',
  folder_id: null,
  name: '冒烟套件',
  description: '上线前检查',
  tags: ['release'],
  draft_definition: { items: [{ test_case_id: testCase.id, test_case_version: 2 }] },
  current_version: 2,
  created_by_id: 'user-1',
  created_at: '2026-08-10T00:00:00Z',
  updated_at: '2026-08-10T00:00:00Z',
}

describe('TestAssetsPage', () => {
  it('renders case inventory with version and template status', () => {
    render(
      <AntdApp>
        <CaseTable
          items={[testCase]}
          loading={false}
          selected={[]}
          onSelect={vi.fn()}
          onEdit={vi.fn()}
          onPublish={vi.fn()}
          onClone={vi.fn()}
          onDiff={vi.fn()}
        />
      </AntdApp>,
    )

    const caseRow = screen.getByRole('row', { name: /登录用例/ })
    expect(within(caseRow).getByText('模板')).toBeVisible()
    expect(within(caseRow).getByText('v2')).toBeVisible()
  })

  it('renders editable and unpublished asset variants', async () => {
    const draftCase = { ...testCase, is_template: false, current_version: null }
    const onEdit = vi.fn()
    const { unmount } = render(
      <AntdApp>
        <CaseTable
          items={[draftCase]}
          loading={false}
          selected={[]}
          onSelect={vi.fn()}
          onEdit={onEdit}
          onPublish={vi.fn()}
          onClone={vi.fn()}
          onDiff={vi.fn()}
        />
      </AntdApp>,
    )
    const row = screen.getByRole('row', { name: /登录用例/ })
    expect(within(row).getByText('用例')).toBeVisible()
    expect(within(row).getByText('未发布')).toBeVisible()
    fireEvent.click(within(row).getByRole('button', { name: /更多/ }))
    expect(await screen.findByRole('menuitem', { name: /版本对比/ })).toHaveAttribute(
      'aria-disabled',
      'true',
    )
    fireEvent.click(within(row).getByRole('button', { name: /编辑/ }))
    expect(onEdit).toHaveBeenCalledWith(draftCase)
    unmount()

    render(
      <AntdApp>
        <CaseDialog
          current={testCase}
          workflows={[workflow]}
          environments={[environment]}
          folders={[folder]}
          submitting={false}
          onClose={vi.fn()}
          onSave={vi.fn().mockResolvedValue(undefined)}
        />
      </AntdApp>,
    )
    expect(screen.getByText('编辑测试用例草稿')).toBeInTheDocument()
    expect(screen.getByDisplayValue(testCase.name)).toHaveValue(testCase.name)
  })

  it('creates a case with a fixed workflow and environment', async () => {
    const state = assetState()
    render(
      <AntdApp>
        <CaseDialog
          current={null}
          workflows={[workflow]}
          environments={[environment]}
          folders={[folder]}
          submitting={false}
          onClose={vi.fn()}
          onSave={state.saveCase}
        />
      </AntdApp>,
    )
    const dialog = screen.getByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('用例名称'), {
      target: { value: '支付用例' },
    })
    await chooseSelect(dialog, '已发布工作流', workflow.name)
    await chooseSelect(dialog, '运行环境', environment.name)
    expect(within(dialog).queryByText('设为用例模板')).not.toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: 'OK' }))

    await waitFor(() =>
      expect(state.saveCase).toHaveBeenCalledWith(
        expect.objectContaining({
          name: '支付用例',
          isTemplate: false,
          definition: expect.objectContaining({
            workflow_id: workflow.id,
            workflow_version: null,
            environment_id: environment.id,
          }),
        }),
      ),
    )
  })

  it('dispatches case publish, clone, diff, and bulk move actions', async () => {
    const state = assetState()
    const onSelect = vi.fn()
    render(
      <AntdApp>
        <AssetPane
          title="测试用例"
          selected={[testCase.id]}
          folderId={folder.id}
          folders={[folder]}
          onFolderChange={vi.fn()}
          onCreate={vi.fn()}
          onMove={() => state.moveCases({ ids: [testCase.id], folderId: folder.id })}
        >
          <CaseTable
            items={[testCase]}
            loading={false}
            selected={[]}
            onSelect={onSelect}
            onEdit={vi.fn()}
            onPublish={state.publishCase}
            onClone={state.cloneCase}
            onDiff={state.loadCaseDiff}
          />
        </AssetPane>
      </AntdApp>,
    )
    const row = screen.getByRole('row', { name: /登录用例/ })

    fireEvent.click(within(row).getByRole('button', { name: /更多/ }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '发布新版本' }))
    fireEvent.click(within(row).getByRole('button', { name: /更多/ }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '克隆' }))
    fireEvent.click(within(row).getByRole('button', { name: /更多/ }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '版本对比' }))
    fireEvent.click(within(row).getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: /批量移动 \(1\)/ }))

    expect(state.publishCase).toHaveBeenCalledWith(testCase)
    expect(state.cloneCase).toHaveBeenCalledWith(testCase)
    expect(state.loadCaseDiff).toHaveBeenCalledWith(testCase)
    expect(onSelect).toHaveBeenCalledWith([testCase.id])
    expect(state.moveCases).toHaveBeenCalledWith({ ids: [testCase.id], folderId: folder.id })
  })

  it('creates and manages a suite from published case versions', async () => {
    const state = assetState()
    render(
      <AntdApp>
        <SuiteDialog
          current={null}
          cases={[testCase]}
          folders={[folder]}
          submitting={false}
          onClose={vi.fn()}
          onSave={state.saveSuite}
        />
      </AntdApp>,
    )
    const dialog = screen.getByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('套件名称'), {
      target: { value: '发布回归' },
    })
    await chooseSelect(dialog, '已发布测试用例', testCase.name)
    fireEvent.click(within(dialog).getByRole('button', { name: 'OK' }))
    await waitFor(() =>
      expect(state.saveSuite).toHaveBeenCalledWith(
        expect.objectContaining({
          name: '发布回归',
          items: [{ test_case_id: testCase.id, test_case_version: 2 }],
        }),
      ),
    )
  })

  it('loads an existing suite draft for editing', () => {
    render(
      <AntdApp>
        <SuiteDialog
          current={testSuite}
          cases={[testCase]}
          folders={[folder]}
          submitting={false}
          onClose={vi.fn()}
          onSave={vi.fn().mockResolvedValue(undefined)}
        />
      </AntdApp>,
    )
    expect(screen.getByText('编辑测试套件草稿')).toBeInTheDocument()
    expect(screen.getByDisplayValue(testSuite.name)).toHaveValue(testSuite.name)
  })

  it('dispatches suite row actions and renders a structured version diff', async () => {
    const state = assetState()
    const diff = {
      from_version: 1,
      to_version: 2,
      changes: [{ path: 'definition.items[0]', before: 1, after: 2 }],
    }
    render(
      <AntdApp>
        <SuiteTable
          items={[testSuite]}
          loading={false}
          selected={[]}
          onSelect={vi.fn()}
          onEdit={vi.fn()}
          onPublish={state.publishSuite}
          onClone={state.cloneSuite}
          onDiff={state.loadSuiteDiff}
        />
        <DiffDialog diff={diff} onClose={state.setDiff} />
      </AntdApp>,
    )
    const row = screen.getByRole('row', { name: /冒烟套件/ })

    fireEvent.click(within(row).getByRole('button', { name: /发布/ }))
    fireEvent.click(within(row).getByRole('button', { name: /克隆/ }))
    fireEvent.click(within(row).getByRole('button', { name: /Diff/ }))

    expect(state.publishSuite).toHaveBeenCalledWith(testSuite)
    expect(state.cloneSuite).toHaveBeenCalledWith(testSuite)
    expect(state.loadSuiteDiff).toHaveBeenCalledWith(testSuite)
    expect(screen.getByText('版本 Diff：v1 → v2')).toBeInTheDocument()
    expect(screen.getByText('definition.items[0]')).toBeInTheDocument()
  })

  it('normalizes optional editor values without losing fixed versions', () => {
    expect(pageItems<{ id: string }>(undefined)).toEqual([])
    expect(pageItems({ items: [{ id: 'asset-1' }] })).toEqual([{ id: 'asset-1' }])
    expect(folderItems({ folders: { data: undefined } } as never)).toEqual([])
    expect(folderItems({ folders: { data: [folder] } } as never)).toEqual([folder])
    expect(editorKey(null, 'new')).toBe('new')
    expect(editorKey(testCase, 'new')).toBe(testCase.id)

    expect(
      caseInput(
        {
          name: testCase.name,
          description: testCase.description,
          tags: undefined as never,
          workflowId: workflow.id,
          environmentId: environment.id,
        },
        testCase.draft_definition,
      ),
    ).toMatchObject({
      tags: [],
      definition: { workflow_version: 2 },
    })
    expect(
      suiteInput(
        {
          name: '空引用套件',
          description: '',
          tags: undefined as never,
          caseIds: ['missing-case'],
        },
        [],
      ),
    ).toMatchObject({
      tags: [],
      items: [{ test_case_id: 'missing-case', test_case_version: null }],
    })
  })

  it('keeps legacy template status, values and fixed suite member versions', () => {
    const edited = caseInput(
      {
        name: testCase.name,
        description: testCase.description,
        tags: testCase.tags,
        workflowId: workflow.id,
        workflowVersion: 2,
        environmentId: environment.id,
        runtimeVariables: [
          { name: 'code', value: '001' },
          { name: 'empty', value: '' },
        ],
        runtimeHeaders: [{ name: 'X-Trace', value: 'raw' }],
      },
      testCase.draft_definition,
      testCase.is_template,
    )
    expect(edited.isTemplate).toBe(true)
    expect(edited.definition.runtime_variables).toEqual({ code: '001', empty: '' })
    expect(edited.definition.workflow_version).toBe(2)
    expect(
      suiteInput(
        { name: testSuite.name, description: '', tags: [], caseIds: [testCase.id] },
        [{ ...testCase, current_version: 3 }],
        testSuite,
      ).items,
    ).toEqual([{ test_case_id: testCase.id, test_case_version: 2 }])
    expect(
      suiteInput(
        {
          name: testSuite.name,
          description: '',
          tags: [],
          caseIds: [testCase.id],
          memberVersions: { [testCase.id]: 3 },
        },
        [{ ...testCase, current_version: 3 }],
        testSuite,
      ).items,
    ).toEqual([{ test_case_id: testCase.id, test_case_version: 3 }])
  })

  it('rejects duplicate and unsafe variable or header names', () => {
    expect(
      validateEntries(
        [
          { name: 'code', value: '' },
          { name: 'code', value: '1' },
        ],
        false,
      ),
    ).toBeTruthy()
    expect(validateEntries([{ name: '', value: '' }], false)).toBeTruthy()
    expect(
      validateEntries(
        [
          { name: 'Authorization', value: 'a' },
          { name: 'authorization', value: 'b' },
        ],
        true,
      ),
    ).toBeTruthy()
    expect(validateEntries([{ name: 'X-Trace', value: 'a\r\nb' }], true)).toBeTruthy()
    expect(validateEntries([{ name: 'X-Trace', value: '001' }], true)).toBeUndefined()
  })

  it('requires an explicit run source and submits the pinned case version', async () => {
    const versions = [
      {
        id: 'version-2',
        test_case_id: testCase.id,
        version: 2,
        definition: { ...testCase.draft_definition, workflow_version: 2 },
        fingerprint: 'f'.repeat(64),
        change_note: '',
        created_by_id: 'user-1',
        created_at: '2026-08-10T00:00:00Z',
      },
    ]
    const load = vi.spyOn(assetService, 'listTestCaseVersions').mockResolvedValue(versions)
    const onRun = vi.fn().mockResolvedValue(undefined)
    render(
      <AntdApp>
        <RunCaseDialog
          item={{ ...testCase, draft_fingerprint: 'a'.repeat(64) }}
          projectId="project-1"
          workflow={workflow}
          environment={environment}
          submitting={false}
          onClose={vi.fn()}
          onRun={onRun}
        />
      </AntdApp>,
    )
    const dialog = screen.getByRole('dialog')
    await waitFor(() => expect(load).toHaveBeenCalledWith('project-1', testCase.id))
    fireEvent.click(within(dialog).getByLabelText('运行已发布用例版本'))
    await waitFor(() =>
      expect(within(dialog).getByRole('button', { name: '运行已发布版本' })).toBeEnabled(),
    )
    fireEvent.click(within(dialog).getByRole('button', { name: '运行已发布版本' }))
    await waitFor(() => expect(onRun).toHaveBeenCalledWith({ source: 'published', version: 2 }))
    load.mockRestore()
  })
})

function assetState(overrides: Record<string, unknown> = {}) {
  return {
    projectId: 'project-1',
    search: '',
    tag: '',
    setSearch: vi.fn(),
    setTag: vi.fn(),
    cases: queryPage([testCase]),
    suites: queryPage([testSuite]),
    workflows: queryPage([workflow]),
    environments: queryData([environment]),
    folders: queryData([folder]),
    diff: null,
    setDiff: vi.fn(),
    saveCase: vi.fn().mockResolvedValue(testCase),
    saveSuite: vi.fn().mockResolvedValue(testSuite),
    publishCase: vi.fn().mockResolvedValue({}),
    publishSuite: vi.fn().mockResolvedValue({}),
    cloneCase: vi.fn().mockResolvedValue(testCase),
    cloneSuite: vi.fn().mockResolvedValue(testSuite),
    moveCases: vi.fn().mockResolvedValue(1),
    moveSuites: vi.fn().mockResolvedValue(1),
    loadCaseDiff: vi.fn().mockResolvedValue(undefined),
    loadSuiteDiff: vi.fn().mockResolvedValue(undefined),
    saving: false,
    ...overrides,
  }
}

function queryPage<T>(items: T[]) {
  return { data: { items, total: items.length, page: 1, page_size: 100 }, isLoading: false }
}

function queryData<T>(data: T[]) {
  return { data, isLoading: false }
}

async function chooseSelect(container: HTMLElement, label: string, option: string) {
  fireEvent.mouseDown(within(container).getByRole('combobox', { name: label }))
  fireEvent.click(await screen.findByText(option, { selector: '.ant-select-item-option-content' }))
}
