import {
  CopyOutlined,
  DiffOutlined,
  EditOutlined,
  FolderOpenOutlined,
  MinusCircleOutlined,
  MoreOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  RocketOutlined,
} from '@ant-design/icons'
import {
  Alert,
  App,
  Button,
  Card,
  Dropdown,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Pagination,
  Radio,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { useProjectContext } from '../features/projects/use-project-context'
import { FolderManagementPanel } from '../features/projects/AssetManagementPanel'
import AssetDetailDrawer from '../features/test-assets/AssetDetailDrawer'
import AssetPlanDialog from '../features/test-assets/AssetPlanDialog'
import AssetDeletionDialog from '../features/test-assets/AssetDeletionDialog'
import AssetPackageToolbar from '../features/test-assets/AssetPackageToolbar'
import { AssetHistoryNotice } from '../features/test-assets/AssetRunEvidence'
import {
  PublishedCaseBinding,
  RecentAssetCell,
  type AssetTableWorkspace,
} from '../features/test-assets/AssetTableContext'
import type {
  AssetDirectoryCounts,
  AssetKind,
  PublishedAssetTarget,
} from '../features/test-assets/asset-workspace-service'
import { useAssetHistory } from '../features/test-assets/use-asset-history'
import {
  addCaseToPlan,
  getTestCase,
  listLatestTestCaseRuns,
  listTestCaseVersions,
  type RunCaseInput,
} from '../features/test-assets/test-asset-service'
import { listTestPlans } from '../features/task-plans/task-plan-service'
import { listWorkflowVersions } from '../features/workflows/workflow-service'
import { useTestAssets } from '../features/test-assets/use-test-assets'
import type {
  TestCaseDraftInput,
  TestSuiteDraftInput,
} from '../features/test-assets/test-asset-service'
import {
  caseInput,
  editorKey,
  entries,
  folderItems,
  pageItems,
  suiteInput,
  validateEntries,
  type CaseFormValues,
  type SuiteFormValues,
} from '../features/test-assets/test-asset-view-model'
import {
  apiErrorMessage,
  type Environment,
  type Folder,
  type TestCase,
  type TestCaseRun,
  type TestCaseVersion,
  type TestPlan,
  type TestSuite,
  type Workflow,
} from '../lib/api'

export default function TestAssetsPage() {
  const { projectId } = useProjectContext()
  return <TestAssetsWorkspace key={projectId} />
}

function TestAssetsWorkspace() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { message } = App.useApp()
  const [caseEditor, setCaseEditor] = useState<TestCase | null | undefined>(undefined)
  const [suiteEditor, setSuiteEditor] = useState<TestSuite | null | undefined>(undefined)
  const [runCase, setRunCase] = useState<TestCase | null>(null)
  const [planCase, setPlanCase] = useState<TestCase | null>(null)
  const [runVersion, setRunVersion] = useState<number>()
  const [planVersion, setPlanVersion] = useState<number>()
  const [recentRun, setRecentRun] = useState<TestCaseRun | null>(null)
  const [selectedCases, setSelectedCases] = useState<string[]>([])
  const [selectedSuites, setSelectedSuites] = useState<string[]>([])
  const [deletion, setDeletion] = useState<{ kind: AssetKind; ids: string[] } | null>(null)
  const [folderId, setFolderId] = useState<string | null>(null)
  const [folderManagementOpen, setFolderManagementOpen] = useState(false)
  const [casePage, setCasePage] = useState(1)
  const [suitePage, setSuitePage] = useState(1)
  const [plan, setPlan] = useState<{ targets: PublishedAssetTarget[]; execute: boolean } | null>(
    null,
  )
  const browseFolder = searchParams.get('folder') ?? 'all'
  const state = useTestAssets({
    folder: browseFolder,
    casePage,
    suitePage,
    loadCaseOptions: suiteEditor !== undefined,
  })
  const cases = pageItems(state.cases.data)
  const suites = pageItems(state.suites.data)
  const publishedCases = pageItems(state.caseOptions.data).filter((item) => item.current_version)
  const history = useAssetHistory(
    state.projectId,
    suites.map((suite) => suite.id),
  )
  function resetSelection() {
    setSelectedCases([])
    setSelectedSuites([])
    setCasePage(1)
    setSuitePage(1)
  }
  function browse(folder: string): void {
    resetSelection()
    const next = new URLSearchParams(searchParams)
    next.set('folder', folder)
    next.delete('focus')
    next.delete('version')
    setSearchParams(next)
  }
  const focusedId = searchParams.get('focus') ?? undefined
  const focusedType = searchParams.get('type')
  useEffect(() => {
    if (focusedType === 'contracts' && state.projectId) {
      navigate(`/projects/${state.projectId}/contracts?tab=automation`, { replace: true })
    }
  }, [focusedType, navigate, state.projectId])
  function focus(kind: AssetKind, id: string) {
    const next = new URLSearchParams(searchParams)
    next.set('focus', id)
    next.set('type', kind)
    next.delete('version')
    setSearchParams(next)
  }
  function setFocusVersion(version: number | 'draft') {
    const next = new URLSearchParams(searchParams)
    next.set('version', String(version))
    setSearchParams(next)
  }
  function closeDetail() {
    const next = new URLSearchParams(searchParams)
    next.delete('focus')
    next.delete('version')
    setSearchParams(next)
  }
  async function action(operation: () => Promise<unknown>) {
    try {
      await operation()
    } catch (error) {
      void message.error(apiErrorMessage(error))
    }
  }
  function changeTab(key: string) {
    resetSelection()
    const next = new URLSearchParams(searchParams)
    next.set('type', key === 'suites' ? 'suite' : 'case')
    next.delete('focus')
    next.delete('version')
    setSearchParams(next)
  }
  function openTarget(target: PublishedAssetTarget, execute: boolean) {
    if (target.kind === 'suite') return setPlan({ targets: [target], execute })
    void action(async () => {
      const item = await getTestCase(state.projectId!, target.id)
      if (execute) {
        setRunVersion(target.version)
        setRunCase(item)
      } else {
        setPlanVersion(target.version)
        setPlanCase(item)
      }
    })
  }
  const workspace: AssetTableWorkspace = {
    projectId: state.projectId ?? '',
    page: casePage,
    total: state.cases.data?.total,
    onPage: (page) => {
      setCasePage(page)
      setSelectedCases([])
    },
    onFocus: focus,
    onPlan: openTarget,
    onDelete: (kind, ids) => setDeletion({ kind, ids }),
    workflows: pageItems(state.workflows.data),
    history,
    canEdit: state.canEdit,
    canExecute: state.canExecute,
  }

  return (
    <div className="test-assets-page">
      <AssetHeading state={state} onFilter={() => resetSelection()} />
      <div className="test-asset-workspace">
        <AssetDirectory
          folders={folderItems(state)}
          selected={browseFolder}
          counts={state.directoryCounts.data}
          onBrowse={browse}
          canEdit={state.canEdit}
          onManage={() => setFolderManagementOpen(true)}
        />
        <div className="test-asset-main">
          <AssetCatalogScope state={state} />
          <AssetPackageToolbar
            projectId={state.projectId ?? ''}
            canEdit={state.canEdit}
            caseIds={selectedCases}
            suiteIds={selectedSuites}
            resources={{
              workflows: pageItems(state.workflows.data),
              environments: state.environments.data ?? [],
              folders: folderItems(state),
            }}
            onImported={resetSelection}
          />
          <AssetHistoryNotice history={history} />
          <AssetTabs
            state={state}
            cases={cases}
            suites={suites}
            publishedCases={publishedCases}
            selectedCases={selectedCases}
            selectedSuites={selectedSuites}
            folderId={folderId}
            setCaseEditor={setCaseEditor}
            setSuiteEditor={setSuiteEditor}
            setSelectedCases={setSelectedCases}
            setSelectedSuites={setSelectedSuites}
            setFolderId={setFolderId}
            focusedId={focusedId}
            focusedType={focusedType}
            workspace={workspace}
            suiteWorkspace={{
              ...workspace,
              page: suitePage,
              total: state.suites.data?.total,
              onPage: (page) => {
                setSuitePage(page)
                setSelectedSuites([])
              },
            }}
            onChangeTab={changeTab}
            onAction={action}
            onPlan={(targets) => setPlan({ targets, execute: false })}
            onRunCase={(item) => {
              setRunVersion(undefined)
              setRunCase(item)
            }}
            onPlanCase={(item) => {
              setPlanVersion(undefined)
              setPlanCase(item)
            }}
            onViewRun={(run) =>
              navigate(`/projects/${state.projectId}/reports?execution=${run.execution_id}`)
            }
          />
        </div>
      </div>
      <AssetDialogs
        state={state}
        caseEditor={caseEditor}
        suiteEditor={suiteEditor}
        publishedCases={publishedCases}
        setCaseEditor={setCaseEditor}
        setSuiteEditor={setSuiteEditor}
      />
      {state.diff && <DiffDialog diff={state.diff} onClose={() => state.setDiff(null)} />}
      <WorkspaceAssetDetail
        state={state}
        params={searchParams}
        history={history}
        onVersion={setFocusVersion}
        onClose={closeDetail}
        onEditCase={setCaseEditor}
        onEditSuite={setSuiteEditor}
        onPlan={openTarget}
      />
      <WorkspaceAssetPlan projectId={state.projectId} plan={plan} onClose={() => setPlan(null)} />
      <WorkspaceFolderManagement
        projectId={state.projectId}
        open={folderManagementOpen}
        canEdit={state.canEdit}
        onClose={() => setFolderManagementOpen(false)}
        onRemoved={(ids) => {
          if (ids.includes(browseFolder)) browse('unfiled')
        }}
      />
      <WorkspaceAssetDeletion
        state={state}
        selection={deletion}
        onClose={() => setDeletion(null)}
        onDeleted={() => {
          resetSelection()
          setDeletion(null)
        }}
      />
      <WorkspaceCaseDialogs
        state={state}
        runCase={runCase}
        runVersion={runVersion}
        planCase={planCase}
        planVersion={planVersion}
        recentRun={recentRun}
        setRunCase={setRunCase}
        setPlanCase={setPlanCase}
        setRecentRun={setRecentRun}
        onNewPlan={(target) => setPlan({ targets: [target], execute: false })}
      />
    </div>
  )
}

function WorkspaceFolderManagement({
  projectId,
  open,
  canEdit,
  onClose,
  onRemoved,
}: {
  projectId: string | null
  open: boolean
  canEdit: boolean
  onClose: () => void
  onRemoved: (ids: string[]) => void
}) {
  if (!projectId || !open) return null
  return (
    <Drawer open title="管理测试资产目录" size={640} onClose={onClose} destroyOnHidden>
      <FolderManagementPanel projectId={projectId} canEdit={canEdit} onRemoved={onRemoved} />
    </Drawer>
  )
}

function WorkspaceAssetDeletion({
  state,
  selection,
  onClose,
  onDeleted,
}: {
  state: AssetState
  selection: { kind: AssetKind; ids: string[] } | null
  onClose: () => void
  onDeleted: () => void
}) {
  if (!state.projectId || !selection) return null
  return (
    <AssetDeletionDialog
      key={`${selection.kind}:${selection.ids.join('|')}`}
      projectId={state.projectId}
      kind={selection.kind}
      ids={selection.ids}
      canEdit={state.canEdit}
      onClose={onClose}
      onDeleted={onDeleted}
    />
  )
}

function WorkspaceCaseDialogs({
  state,
  runCase,
  runVersion,
  planCase,
  planVersion,
  recentRun,
  setRunCase,
  setPlanCase,
  setRecentRun,
  onNewPlan,
}: {
  state: AssetState
  runCase: TestCase | null
  runVersion?: number
  planCase: TestCase | null
  planVersion?: number
  recentRun: TestCaseRun | null
  setRunCase: (value: TestCase | null) => void
  setPlanCase: (value: TestCase | null) => void
  setRecentRun: (value: TestCaseRun | null) => void
  onNewPlan: (target: PublishedAssetTarget) => void
}) {
  const navigate = useNavigate()
  return (
    <>
      {runCase && state.projectId && (
        <RunCaseDialog
          key={runCase.id}
          item={runCase}
          initialVersion={runVersion}
          projectId={state.projectId}
          workflow={pageItems(state.workflows.data).find(
            (workflow) => workflow.id === runCase.draft_definition.workflow_id,
          )}
          environment={state.environments.data?.find(
            (environment) => environment.id === runCase.draft_definition.environment_id,
          )}
          submitting={state.runningCase}
          onClose={() => setRunCase(null)}
          onRun={async (input) => {
            const run = await state.runCase({ caseId: runCase.id, input })
            setRecentRun(run)
            setRunCase(null)
          }}
        />
      )}
      {planCase && state.projectId && (
        <AddCaseToPlanDialog
          key={planCase.id}
          item={planCase}
          initialVersion={planVersion}
          projectId={state.projectId}
          onClose={() => setPlanCase(null)}
          onCreate={(version) => {
            onNewPlan({ kind: 'case', id: planCase.id, name: planCase.name, version })
            setPlanCase(null)
          }}
        />
      )}
      {recentRun && (
        <Modal
          title="运行已提交"
          open
          onCancel={() => setRecentRun(null)}
          onOk={() => {
            navigate(
              `/projects/${state.projectId}/workflows?focus=${recentRun.workflow_id}&execution=${recentRun.execution_id}`,
            )
            setRecentRun(null)
          }}
          okText="查看执行详情"
        >
          <Typography.Text>
            用例 v{recentRun.case_version} · 流程 v{recentRun.workflow_version} 已进入执行队列。
          </Typography.Text>
        </Modal>
      )}
    </>
  )
}

function AssetCatalogScope({ state }: { state: AssetState }) {
  const loading = state.cases.isPending || state.suites.isPending
  return (
    <Typography.Paragraph type="secondary" className="asset-loaded-scope">
      {loading
        ? '正在读取当前目录与当前页…'
        : `当前目录匹配 ${state.cases.data?.total ?? '—'} 个用例、${state.suites.data?.total ?? '—'} 个套件。`}
    </Typography.Paragraph>
  )
}

function WorkspaceAssetDetail(
  props: Pick<
    Parameters<typeof AssetDetailDrawer>[0],
    'history' | 'onVersion' | 'onClose' | 'onEditCase' | 'onEditSuite' | 'onPlan'
  > & {
    state: AssetState
    params: URLSearchParams
  },
) {
  const { state, params } = props
  const id = params.get('focus')
  const type = params.get('type')
  if (!state.projectId || !id || type === 'contracts') return null
  return (
    <AssetDetailDrawer
      {...props}
      key={`${type}:${id}`}
      projectId={state.projectId}
      kind={type === 'suite' ? 'suite' : 'case'}
      id={id}
      version={assetRouteVersion(params)}
      workflows={pageItems(state.workflows.data)}
      environments={state.environments.data ?? []}
      cases={state.caseOptions.data?.items ?? pageItems(state.cases.data)}
      canEdit={state.canEdit}
      canExecute={state.canExecute}
    />
  )
}

function WorkspaceAssetPlan({
  projectId,
  plan,
  onClose,
}: {
  projectId: string | null
  plan: { targets: PublishedAssetTarget[]; execute: boolean } | null
  onClose: () => void
}) {
  if (!projectId || !plan) return null
  return (
    <AssetPlanDialog
      projectId={projectId}
      targets={plan.targets}
      execute={plan.execute}
      onClose={onClose}
    />
  )
}

function assetRouteVersion(params: URLSearchParams): number | 'draft' | undefined {
  const raw = params.get('version')
  if (raw === 'draft') return raw
  if (!raw || !/^[1-9]\d*$/.test(raw)) return undefined
  const version = Number(raw)
  return Number.isSafeInteger(version) ? version : undefined
}

function AssetDirectory({
  folders,
  selected,
  counts,
  onBrowse,
  canEdit,
  onManage,
}: {
  folders: Folder[]
  selected: string
  counts?: AssetDirectoryCounts
  onBrowse: (folder: string) => void
  canEdit: boolean
  onManage: () => void
}) {
  const entries = [
    { id: 'all', name: '全部测试资产' },
    { id: 'unfiled', name: '未分类' },
    ...folders
      .map((folder) => ({ ...folder, name: directoryPath(folder, folders) }))
      .sort((a, b) => a.name.localeCompare(b.name, 'zh-CN')),
  ]
  return (
    <Card
      title="用例目录"
      className="test-asset-directory"
      extra={
        <Button size="small" disabled={!canEdit} onClick={onManage}>
          管理目录
        </Button>
      }
    >
      <nav aria-label="浏览测试资产目录">
        {entries.map((entry) => (
          <Button
            key={entry.id}
            type={selected === entry.id ? 'primary' : 'text'}
            aria-pressed={selected === entry.id}
            onClick={() => onBrowse(entry.id)}
          >
            <FolderOpenOutlined />
            <span>{entry.name}</span>
            <Tag>{assetDirectoryCount(counts, entry.id)}</Tag>
          </Button>
        ))}
      </nav>
      <Typography.Paragraph type="secondary">
        数量由服务端统计全部筛选结果；列表按目录分页读取。批量选择只影响当前页。
      </Typography.Paragraph>
    </Card>
  )
}

function assetDirectoryCount(counts: AssetDirectoryCounts | undefined, id: string): number | '—' {
  if (!counts) return '—'
  if (id === 'all') return counts.case_total + counts.suite_total
  if (id === 'unfiled') return counts.unfiled_cases + counts.unfiled_suites
  const row = counts.folders.find((item) => item.folder_id === id)
  return row ? row.cases + row.suites : 0
}

function directoryPath(folder: Folder, folders: Folder[]): string {
  const names = [folder.name]
  const visited = new Set([folder.id])
  let parentId = folder.parent_id
  while (parentId && !visited.has(parentId)) {
    visited.add(parentId)
    const parent = folders.find((item) => item.id === parentId)
    if (!parent) break
    names.unshift(parent.name)
    parentId = parent.parent_id
  }
  return names.join(' / ')
}

type AssetState = ReturnType<typeof useTestAssets>
type EditorSetter<T> = (value: T | null | undefined) => void

function AssetHeading({ state, onFilter }: { state: AssetState; onFilter: () => void }) {
  return (
    <div className="page-heading">
      <div>
        <Typography.Title level={2}>测试用例</Typography.Title>
        <Typography.Text type="secondary">
          将已编排流程绑定运行环境和测试数据，形成可重复执行的测试用例。可直接运行，也可加入定时或
          CI 测试计划。
        </Typography.Text>
      </div>
      <Space wrap>
        <Input.Search
          key={state.search}
          aria-label="搜索测试用例"
          allowClear
          placeholder="搜索名称或描述"
          onSearch={(value) => {
            onFilter()
            state.setSearch(value)
          }}
        />
        <Input
          aria-label="标签筛选"
          allowClear
          placeholder="标签筛选"
          value={state.tag}
          onChange={(event) => {
            onFilter()
            state.setTag(event.target.value)
          }}
        />
      </Space>
    </div>
  )
}

function AssetTabs(props: {
  state: AssetState
  cases: TestCase[]
  suites: TestSuite[]
  publishedCases: TestCase[]
  selectedCases: string[]
  selectedSuites: string[]
  folderId: string | null
  setCaseEditor: EditorSetter<TestCase>
  setSuiteEditor: EditorSetter<TestSuite>
  setSelectedCases: (ids: string[]) => void
  setSelectedSuites: (ids: string[]) => void
  setFolderId: (id: string | null) => void
  onRunCase: (item: TestCase) => void
  onPlanCase: (item: TestCase) => void
  onViewRun: (run: TestCaseRun) => void
  focusedId?: string
  focusedType: string | null
  workspace: AssetTableWorkspace
  suiteWorkspace: AssetTableWorkspace
  onChangeTab: (key: string) => void
  onAction: (operation: () => Promise<unknown>) => Promise<void>
  onPlan: (targets: PublishedAssetTarget[]) => void
}) {
  return (
    <Card>
      <AssetLoadErrors state={props.state} />
      <Tabs
        animated={false}
        activeKey={props.focusedType === 'suite' ? 'suites' : 'cases'}
        onChange={props.onChangeTab}
        items={[caseTab(props), suiteTab(props)]}
      />
    </Card>
  )
}

function AssetLoadErrors({ state }: { state: AssetState }) {
  const queries = [
    state.cases,
    state.suites,
    state.workflows,
    state.caseOptions,
    state.environments,
    state.folders,
    state.permissions,
    state.directoryCounts,
  ]
  const failed = queries.find((query) => query.error)
  if (!failed) return null
  return (
    <Alert
      type="error"
      showIcon
      title="资产数据读取失败"
      description={apiErrorMessage(failed.error)}
      action={
        <Button onClick={() => void Promise.all(queries.map((query) => query.refetch()))}>
          重新加载
        </Button>
      }
    />
  )
}

function caseTab(props: Parameters<typeof AssetTabs>[0]) {
  const { state, cases, selectedCases, folderId, setCaseEditor, setSelectedCases, setFolderId } =
    props
  return {
    key: 'cases',
    label: `测试用例 (${state.cases.data?.total ?? '—'})`,
    children: (
      <AssetPane
        title="测试用例"
        selected={selectedCases}
        folderId={folderId}
        folders={folderItems(state)}
        createDisabled={
          !state.canEdit ||
          !pageItems(state.workflows.data).some((workflow) => workflow.current_version !== null) ||
          !state.environments.data?.length
        }
        onFolderChange={setFolderId}
        onCreate={() => setCaseEditor(null)}
        onMove={() =>
          void props.onAction(async () => {
            await state.moveCases({ ids: selectedCases, folderId })
            setSelectedCases([])
          })
        }
        moveDisabled={!state.canEdit}
        onDelete={() => props.workspace.onDelete('case', selectedCases)}
        deleteDisabled={!state.canEdit}
        onPlan={() => props.onPlan(selectedTargets('case', cases, selectedCases))}
        planDisabled={!state.canEdit || !allPublished(cases, selectedCases)}
      >
        <WorkspaceCaseTable
          items={cases}
          workflows={pageItems(state.workflows.data)}
          environments={state.environments.data ?? []}
          focusedId={props.focusedId}
          loading={state.cases.isLoading}
          selected={selectedCases}
          onSelect={setSelectedCases}
          onEdit={setCaseEditor}
          onPublish={(item) => void props.onAction(() => state.publishCase(item.id))}
          onClone={(item) => void props.onAction(() => state.cloneCase(item))}
          onDiff={(item) => void props.onAction(() => state.loadCaseDiff(item))}
          workspace={props.workspace}
          onRun={props.onRunCase}
          onPlan={props.onPlanCase}
          onViewRun={props.onViewRun}
        />
      </AssetPane>
    ),
  }
}

function suiteTab(props: Parameters<typeof AssetTabs>[0]) {
  const {
    state,
    suites,
    selectedSuites,
    folderId,
    setSuiteEditor,
    setSelectedSuites,
    setFolderId,
  } = props
  return {
    key: 'suites',
    label: `测试套件 (${state.suites.data?.total ?? '—'})`,
    children: (
      <AssetPane
        title="测试套件"
        selected={selectedSuites}
        folderId={folderId}
        folders={folderItems(state)}
        createDisabled={!state.canEdit}
        onFolderChange={setFolderId}
        onCreate={() => setSuiteEditor(null)}
        onMove={() =>
          void props.onAction(async () => {
            await state.moveSuites({ ids: selectedSuites, folderId })
            setSelectedSuites([])
          })
        }
        moveDisabled={!state.canEdit}
        onDelete={() => props.suiteWorkspace.onDelete('suite', selectedSuites)}
        deleteDisabled={!state.canEdit}
        onPlan={() => props.onPlan(selectedTargets('suite', suites, selectedSuites))}
        planDisabled={!state.canEdit || !allPublished(suites, selectedSuites)}
      >
        <SuiteTable
          items={suites}
          focusedId={props.focusedId}
          loading={state.suites.isLoading}
          selected={selectedSuites}
          onSelect={setSelectedSuites}
          onEdit={setSuiteEditor}
          onPublish={(item) => void props.onAction(() => state.publishSuite(item.id))}
          onClone={(item) => void props.onAction(() => state.cloneSuite(item))}
          onDiff={(item) => void props.onAction(() => state.loadSuiteDiff(item))}
          workspace={props.suiteWorkspace}
        />
      </AssetPane>
    ),
  }
}

function allPublished(items: Array<TestCase | TestSuite>, ids: string[]): boolean {
  return (
    ids.length > 0 &&
    ids.every((id) => items.some((item) => item.id === id && item.current_version !== null))
  )
}

function selectedTargets(
  kind: AssetKind,
  items: Array<TestCase | TestSuite>,
  ids: string[],
): PublishedAssetTarget[] {
  return items
    .filter((item) => ids.includes(item.id) && item.current_version !== null)
    .map((item) => ({ kind, id: item.id, name: item.name, version: item.current_version! }))
}

function AssetDialogs({
  state,
  caseEditor,
  suiteEditor,
  publishedCases,
  setCaseEditor,
  setSuiteEditor,
}: {
  state: AssetState
  caseEditor: TestCase | null | undefined
  suiteEditor: TestSuite | null | undefined
  publishedCases: TestCase[]
  setCaseEditor: EditorSetter<TestCase>
  setSuiteEditor: EditorSetter<TestSuite>
}) {
  return (
    <>
      {caseEditor !== undefined && (
        <CaseDialog
          key={editorKey(caseEditor, 'new-case')}
          current={caseEditor}
          projectId={state.projectId ?? undefined}
          workflows={pageItems(state.workflows.data).filter(
            (workflow) => workflow.current_version !== null,
          )}
          environments={state.environments.data ?? []}
          folders={folderItems(state)}
          submitting={state.saving}
          onClose={() => setCaseEditor(undefined)}
          onSave={async (input) => {
            await state.saveCase({ current: caseEditor, input })
            setCaseEditor(undefined)
          }}
        />
      )}
      {suiteEditor !== undefined && (
        <SuiteDialog
          key={editorKey(suiteEditor, 'new-suite')}
          current={suiteEditor}
          cases={publishedCases}
          folders={folderItems(state)}
          submitting={state.saving}
          assetOptionsLoading={state.caseOptions.isFetching}
          assetOptionsError={state.caseOptions.error}
          onClose={() => setSuiteEditor(undefined)}
          onSave={async (input) => {
            await state.saveSuite({ current: suiteEditor, input })
            setSuiteEditor(undefined)
          }}
        />
      )}
    </>
  )
}

export function AssetPane({
  title,
  selected,
  folderId,
  folders,
  createDisabled = false,
  onFolderChange,
  onCreate,
  onMove,
  moveDisabled = false,
  onPlan,
  planDisabled = false,
  onDelete,
  deleteDisabled = false,
  children,
}: {
  title: string
  selected: string[]
  folderId: string | null
  folders: Folder[]
  createDisabled?: boolean
  onFolderChange: (value: string | null) => void
  onCreate: () => void
  onMove: () => void
  moveDisabled?: boolean
  onPlan?: () => void
  planDisabled?: boolean
  onDelete?: () => void
  deleteDisabled?: boolean
  children: React.ReactNode
}) {
  return (
    <>
      <Space wrap className="asset-toolbar">
        <Button type="primary" icon={<PlusOutlined />} disabled={createDisabled} onClick={onCreate}>
          新建{title}
        </Button>
        <Select
          aria-label={`${title}批量目录`}
          allowClear
          placeholder="移动到目录"
          value={folderId ?? undefined}
          options={folders.map((folder) => ({ value: folder.id, label: folder.name }))}
          onChange={(value?: string) => onFolderChange(value ?? null)}
        />
        <Button
          icon={<FolderOpenOutlined />}
          disabled={moveDisabled || !selected.length}
          onClick={onMove}
        >
          批量移动 ({selected.length})
        </Button>
        {onPlan && (
          <Button
            icon={<PlayCircleOutlined />}
            disabled={planDisabled || !selected.length}
            onClick={onPlan}
          >
            加入计划 ({selected.length})
          </Button>
        )}
        <AssetDeleteButton selected={selected} disabled={deleteDisabled} onDelete={onDelete} />
        <Typography.Text type="secondary">仅选择当前页</Typography.Text>
      </Space>
      {children}
    </>
  )
}

function AssetDeleteButton({
  selected,
  disabled,
  onDelete,
}: {
  selected: string[]
  disabled: boolean
  onDelete?: () => void
}) {
  if (!onDelete) return null
  return (
    <Button danger disabled={disabled || !selected.length} onClick={onDelete}>
      批量删除 ({selected.length})
    </Button>
  )
}

function WorkspaceCaseTable(props: Parameters<typeof CaseTable>[0]) {
  const workspace = props.workspace!
  const ids = props.items.map((item) => item.id)
  const latest = useQuery({
    queryKey: ['test-case-runs', workspace.projectId, ids.join('|')],
    queryFn: () => listLatestTestCaseRuns(workspace.projectId, ids),
    refetchInterval: (query) =>
      query.state.data?.some((run) => ['queued', 'running'].includes(run.status)) ? 2000 : false,
  })
  return (
    <CaseTable
      {...props}
      latestRuns={latest.data}
      latestLoading={latest.isPending}
      latestError={latest.isError}
    />
  )
}

export function CaseTable({
  items,
  workflows = [],
  environments = [],
  latestRuns,
  latestLoading = false,
  latestError = false,
  loading,
  selected,
  onSelect,
  onEdit,
  onRun,
  onPlan,
  onViewRun,
  onPublish,
  onClone,
  onDiff,
  focusedId,
  workspace,
}: {
  items: TestCase[]
  workflows?: Workflow[]
  environments?: Environment[]
  latestRuns?: TestCaseRun[]
  latestLoading?: boolean
  latestError?: boolean
  loading: boolean
  selected: string[]
  onSelect: (ids: string[]) => void
  onEdit: (item: TestCase) => void
  onRun?: (item: TestCase) => void
  onPlan?: (item: TestCase) => void
  onViewRun?: (run: TestCaseRun) => void
  onPublish: (item: TestCase) => void
  onClone: (item: TestCase) => void
  onDiff: (item: TestCase) => void
  focusedId?: string
  workspace?: AssetTableWorkspace
}) {
  return (
    <Table
      rowKey="id"
      size="small"
      loading={loading}
      pagination={assetPagination(workspace)}
      scroll={workspace ? { x: 920 } : undefined}
      dataSource={items}
      rowClassName={(item) => (item.id === focusedId ? 'selected-row' : '')}
      rowSelection={{ selectedRowKeys: selected, onChange: (keys) => onSelect(keys.map(String)) }}
      columns={[
        {
          title: '用例',
          dataIndex: 'name',
          render: (name: string, item) =>
            workspace ? (
              <Button
                type="link"
                className="asset-name-button"
                onClick={() => workspace.onFocus('case', item.id)}
              >
                {name}
              </Button>
            ) : (
              name
            ),
        },
        ...caseContextColumns(workspace),
        {
          title: '标签',
          dataIndex: 'tags',
          render: (tags: string[]) => tags.map((tag) => <Tag key={tag}>{tag}</Tag>),
        },
        {
          title: '类型',
          render: (_, item) => (item.is_template ? <Tag color="purple">模板</Tag> : '用例'),
        },
        ...(!workspace
          ? [
              {
                title: '关联流程',
                render: (_: unknown, item: TestCase) =>
                  workflows.find((workflow) => workflow.id === item.draft_definition.workflow_id)
                    ?.name ?? '流程不可用',
              },
            ]
          : []),
        {
          title: '运行环境',
          render: (_, item) =>
            environments.find(
              (environment) => environment.id === item.draft_definition.environment_id,
            )?.name ?? '环境不可用',
        },
        { title: '用例版本', render: (_, item) => versionLabel(item.current_version) },
        {
          title: '最近运行',
          render: (_, item) => {
            if (latestError) return '状态加载失败'
            if (latestLoading || !latestRuns) return '状态加载中'
            const run = latestRuns.find((entry) => entry.case_id === item.id)
            if (!run) return '未运行'
            return (
              <Space size={4}>
                <Button type="link" onClick={() => onViewRun?.(run)} disabled={!onViewRun}>
                  {runStatusLabel(run.status)} · 用例 v{run.case_version}
                </Button>
                <Typography.Text type="secondary">
                  {run.source === 'direct' ? '直接运行' : '测试计划'}
                </Typography.Text>
              </Space>
            )
          },
        },
        {
          title: '更新时间',
          render: (_, item) => new Date(item.updated_at).toLocaleString('zh-CN'),
        },
        {
          title: '操作',
          width: 180,
          render: (_, item) => (
            <CaseRowActions
              item={item}
              onRun={onRun}
              onEdit={onEdit}
              onPlan={onPlan}
              onPublish={onPublish}
              onClone={onClone}
              onDiff={onDiff}
              canEdit={workspace?.canEdit ?? true}
              canExecute={workspace?.canExecute ?? true}
              onDelete={workspace ? () => workspace.onDelete('case', [item.id]) : undefined}
            />
          ),
        },
      ]}
    />
  )
}

function CaseRowActions({
  item,
  onRun,
  onEdit,
  onPlan,
  onPublish,
  onClone,
  onDiff,
  canEdit,
  canExecute,
  onDelete,
}: {
  item: TestCase
  onRun?: (item: TestCase) => void
  onEdit: (item: TestCase) => void
  onPlan?: (item: TestCase) => void
  onPublish: (item: TestCase) => void
  onClone: (item: TestCase) => void
  onDiff: (item: TestCase) => void
  canEdit: boolean
  canExecute: boolean
  onDelete?: () => void
}) {
  return (
    <Space size={0}>
      <Button
        type="link"
        disabled={!canEdit || !canExecute || !onRun}
        onClick={() => onRun?.(item)}
      >
        运行
      </Button>
      <Button type="link" disabled={!canEdit} onClick={() => onEdit(item)}>
        编辑
      </Button>
      <Dropdown
        trigger={['click']}
        menu={{
          items: [
            {
              key: 'plan',
              label: '加入测试计划',
              disabled: !canEdit || !item.current_version || !onPlan,
            },
            { key: 'publish', label: '发布新版本', disabled: !canEdit },
            { key: 'clone', label: '克隆', disabled: !canEdit },
            {
              key: 'delete',
              label: '删除',
              danger: true,
              disabled: !canEdit || !onDelete,
              onClick: onDelete,
            },
            {
              key: 'diff',
              label: '版本对比',
              disabled: !item.current_version || item.current_version < 2,
            },
          ],
          onClick: ({ key }) => {
            if (key === 'plan') onPlan?.(item)
            if (key === 'publish') onPublish(item)
            if (key === 'clone') onClone(item)
            if (key === 'diff') onDiff(item)
          },
        }}
      >
        <Button type="link" icon={<MoreOutlined />}>
          更多
        </Button>
      </Dropdown>
    </Space>
  )
}

function runStatusLabel(status: TestCaseRun['status']): string {
  return {
    queued: '排队中',
    running: '运行中',
    passed: '通过',
    failed: '失败',
    cancelled: '已取消',
  }[status]
}

export function SuiteTable({
  items,
  loading,
  selected,
  onSelect,
  onEdit,
  onPublish,
  onClone,
  onDiff,
  focusedId,
  workspace,
}: {
  items: TestSuite[]
  loading: boolean
  selected: string[]
  onSelect: (ids: string[]) => void
  onEdit: (item: TestSuite) => void
  onPublish: (item: TestSuite) => void
  onClone: (item: TestSuite) => void
  onDiff: (item: TestSuite) => void
  focusedId?: string
  workspace?: AssetTableWorkspace
}) {
  return (
    <Table
      rowKey="id"
      size="small"
      loading={loading}
      pagination={assetPagination(workspace)}
      scroll={workspace ? { x: 800 } : undefined}
      dataSource={items}
      rowClassName={(item) => (item.id === focusedId ? 'selected-row' : '')}
      rowSelection={{ selectedRowKeys: selected, onChange: (keys) => onSelect(keys.map(String)) }}
      columns={[
        {
          title: '套件',
          dataIndex: 'name',
          render: (name: string, item) =>
            workspace ? (
              <Button
                type="link"
                className="asset-name-button"
                onClick={() => workspace.onFocus('suite', item.id)}
              >
                {name}
              </Button>
            ) : (
              name
            ),
        },
        ...suiteContextColumns(workspace),
        {
          title: '草稿用例数',
          render: (_, item) => item.draft_definition.items.length,
        },
        {
          title: '成员版本',
          render: (_, item) =>
            item.draft_definition.items.map((member) => (
              <Tag key={member.test_case_id}>
                {member.test_case_id.slice(0, 8)} ·{' '}
                {member.test_case_version ? `v${member.test_case_version}` : '发布时最新'}
              </Tag>
            )),
        },
        {
          title: '标签',
          dataIndex: 'tags',
          render: (tags: string[]) => tags.map((tag) => <Tag key={tag}>{tag}</Tag>),
        },
        { title: '版本', render: (_, item) => versionLabel(item.current_version) },
        {
          title: '操作',
          width: workspace ? 200 : 310,
          render: (_, item) => (
            <RowActions
              version={item.current_version}
              onEdit={() => onEdit(item)}
              onPublish={() => onPublish(item)}
              onClone={() => onClone(item)}
              onDiff={() => onDiff(item)}
              compact={Boolean(workspace)}
              canEdit={workspace?.canEdit ?? true}
              onDelete={workspace ? () => workspace.onDelete('suite', [item.id]) : undefined}
            />
          ),
        },
      ]}
    />
  )
}

function assetPagination(workspace: AssetTableWorkspace | undefined) {
  if (!workspace) return false as const
  return {
    current: workspace.page,
    total: workspace.total,
    pageSize: 20,
    showSizeChanger: false,
    onChange: workspace.onPage,
    showTotal: (total: number) => `共 ${total} 条`,
  }
}

function caseContextColumns(workspace: AssetTableWorkspace | undefined) {
  if (!workspace) return []
  return [
    {
      title: '已发布绑定流程',
      width: 220,
      render: (_: unknown, item: TestCase) => (
        <PublishedCaseBinding item={item} workspace={workspace} />
      ),
    },
  ]
}

function suiteContextColumns(workspace: AssetTableWorkspace | undefined) {
  if (!workspace) return []
  return [
    {
      title: '最近套件结果',
      width: 200,
      render: (_: unknown, item: TestSuite) => (
        <RecentAssetCell kind="suite" id={item.id} workspace={workspace} />
      ),
    },
  ]
}

function RowActions({
  version,
  onEdit,
  onPublish,
  onClone,
  onDiff,
  compact = false,
  canEdit = true,
  onDelete,
}: {
  version: number | null
  onEdit: () => void
  onPublish: () => void
  onClone: () => void
  onDiff: () => void
  compact?: boolean
  canEdit?: boolean
  onDelete?: () => void
}) {
  return (
    <Space size={0}>
      <Button type="link" icon={<EditOutlined />} disabled={!canEdit} onClick={onEdit}>
        编辑
      </Button>
      <Button type="link" icon={<RocketOutlined />} disabled={!canEdit} onClick={onPublish}>
        发布
      </Button>
      {compact ? (
        <Dropdown
          menu={{
            items: [
              {
                key: 'delete',
                label: '删除',
                danger: true,
                disabled: !canEdit || !onDelete,
                onClick: onDelete,
              },
              {
                key: 'clone',
                label: '克隆',
                icon: <CopyOutlined />,
                disabled: !canEdit,
                onClick: onClone,
              },
              {
                key: 'diff',
                label: '版本比较',
                icon: <DiffOutlined />,
                disabled: !version || version < 2,
                onClick: onDiff,
              },
            ],
          }}
          trigger={['click']}
        >
          <Button type="text" aria-label="更多资产操作" icon={<MoreOutlined />} />
        </Dropdown>
      ) : (
        <>
          <Button type="link" icon={<CopyOutlined />} disabled={!canEdit} onClick={onClone}>
            克隆
          </Button>
          <Button
            type="link"
            icon={<DiffOutlined />}
            disabled={!version || version < 2}
            onClick={onDiff}
          >
            Diff
          </Button>
        </>
      )}
    </Space>
  )
}

export function CaseDialog({
  current,
  projectId,
  workflows,
  environments,
  folders,
  submitting,
  onClose,
  onSave,
}: {
  current: TestCase | null
  projectId?: string
  workflows: Workflow[]
  environments: Environment[]
  folders: Folder[]
  submitting: boolean
  onClose: () => void
  onSave: (input: TestCaseDraftInput) => Promise<void>
}) {
  const [form] = Form.useForm<CaseFormValues>()
  const definition = current?.draft_definition
  const workflowId = Form.useWatch('workflowId', form) as string | undefined
  const [versions, setVersions] = useState<number[]>([])
  const [versionError, setVersionError] = useState<string | null>(null)
  useEffect(() => {
    if (!projectId || !workflowId) return
    let active = true
    void listWorkflowVersions(projectId, workflowId)
      .then((items) => {
        if (active) {
          setVersions(items.map((item) => item.version))
          setVersionError(null)
        }
      })
      .catch((reason: unknown) => {
        if (active) {
          setVersions([])
          setVersionError(apiErrorMessage(reason))
        }
      })
    return () => {
      active = false
    }
  }, [projectId, workflowId])
  const selectedWorkflow = workflows.find((item) => item.id === workflowId)
  const availableVersions = projectId
    ? versions
    : Array.from({ length: selectedWorkflow?.current_version ?? 0 }, (_, index) => index + 1)
  const close = () => {
    if (!form.isFieldsTouched()) return onClose()
    Modal.confirm({ title: '放弃未保存的修改？', onOk: onClose })
  }
  const [error, setError] = useState<string | null>(null)
  async function save() {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    setError(null)
    try {
      await onSave(caseInput(values, definition, current?.is_template ?? false))
    } catch (failure) {
      setError(apiErrorMessage(failure))
    }
  }
  return (
    <Modal
      title={caseDialogTitle(current)}
      open
      width={720}
      destroyOnHidden
      confirmLoading={submitting}
      onCancel={close}
      onOk={() => void save()}
    >
      <Form form={form} layout="vertical" initialValues={caseDialogDefaults(current)}>
        <Form.Item name="name" label="用例名称" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item name="description" label="说明">
          <Input.TextArea rows={2} />
        </Form.Item>
        <Form.Item name="workflowId" label="已发布工作流" rules={[{ required: true }]}>
          <Select
            showSearch
            optionFilterProp="label"
            options={workflows.map(option)}
            onChange={() => {
              form.setFieldValue('workflowVersion', null)
              setVersions([])
              setVersionError(null)
            }}
          />
        </Form.Item>
        <Form.Item
          name="workflowVersion"
          label="流程版本策略"
          extra="发布时使用最新版本会在发布用例时固定实际流程版本；指定版本始终使用所选版本。"
        >
          <Select
            options={[
              { value: null, label: '发布时使用当时最新已发布版本' },
              ...availableVersions.map((version) => ({
                value: version,
                label: `指定流程 v${version}`,
              })),
            ]}
          />
        </Form.Item>
        {versionError && (
          <Typography.Text type="danger">流程版本加载失败：{versionError}</Typography.Text>
        )}
        <Form.Item name="environmentId" label="运行环境" rules={[{ required: true }]}>
          <Select showSearch optionFilterProp="label" options={environments.map(option)} />
        </Form.Item>
        <Form.Item name="folderId" label="目录">
          <Select allowClear options={folders.map(option)} />
        </Form.Item>
        <Form.Item name="tags" label="标签">
          <Select mode="tags" tokenSeparators={[',']} />
        </Form.Item>
        <KeyValueEditor name="runtimeVariables" title="测试变量" addLabel="添加变量" />
        <KeyValueEditor name="runtimeHeaders" title="请求头覆盖" addLabel="添加请求头" headers />
      </Form>
      {error && <Alert type="error" showIcon title="保存用例失败" description={error} />}
    </Modal>
  )
}

function KeyValueEditor({
  name,
  title,
  addLabel,
  headers = false,
}: {
  name: 'runtimeVariables' | 'runtimeHeaders'
  title: string
  addLabel: string
  headers?: boolean
}) {
  return (
    <Form.List
      name={name}
      rules={[
        {
          validator: async (_, values = []) => {
            const error = validateEntries(values, headers)
            if (error) throw new Error(error)
          },
        },
      ]}
    >
      {(fields, { add, remove }, { errors }) => (
        <div>
          <Typography.Text strong>{title}</Typography.Text>
          {fields.map((field) => (
            <Space key={field.key} align="baseline" style={{ display: 'flex' }}>
              <Form.Item
                name={[field.name, 'name']}
                rules={[{ required: true, message: '请输入名称' }]}
              >
                <Input aria-label={`${title}名称${field.name + 1}`} placeholder="名称" />
              </Form.Item>
              <Form.Item name={[field.name, 'value']}>
                <Input aria-label={`${title}值${field.name + 1}`} placeholder="值（可为空）" />
              </Form.Item>
              <Button
                aria-label={`删除${title}${field.name + 1}`}
                icon={<MinusCircleOutlined />}
                onClick={() => remove(field.name)}
              />
            </Space>
          ))}
          <Form.ErrorList errors={errors} />
          <Button type="dashed" onClick={() => add({ name: '', value: '' })}>
            {addLabel}
          </Button>
        </div>
      )}
    </Form.List>
  )
}

export function RunCaseDialog({
  item,
  initialVersion,
  projectId,
  workflow,
  environment,
  submitting,
  onClose,
  onRun,
}: {
  item: TestCase
  initialVersion?: number
  projectId: string
  workflow?: Workflow
  environment?: Environment
  submitting: boolean
  onClose: () => void
  onRun: (input: RunCaseInput) => Promise<void>
}) {
  const { versions, loading, loadError } = useCaseVersions(projectId, item.id)
  const [source, setSource] = useState<RunCaseSource | undefined>(
    initialVersion ? 'published' : item.current_version ? undefined : 'draft',
  )
  const [version, setVersion] = useState(initialVersion ?? item.current_version ?? undefined)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const error = loadError ?? submitError
  const canRun = canRunCase(source, version, versions, item.draft_fingerprint, loading, error)
  const confirm = async () => {
    if (!source) return
    try {
      setSubmitError(null)
      await onRun(caseRunInput(source, version, item.draft_fingerprint))
    } catch (reason) {
      setSubmitError(apiErrorMessage(reason))
    }
  }
  return (
    <Modal
      title={`运行测试用例：${item.name}`}
      open
      onCancel={onClose}
      onOk={() => void confirm()}
      confirmLoading={submitting}
      okButtonProps={{ disabled: !canRun }}
      okText={source === 'draft' ? '发布并运行' : '运行已发布版本'}
    >
      <RunCaseDetails
        item={item}
        workflow={workflow}
        environment={environment}
        versions={versions}
        source={source}
        version={version}
        error={error}
        onSource={setSource}
        onVersion={setVersion}
      />
    </Modal>
  )
}

type RunCaseSource = 'published' | 'draft'

function useCaseVersions(projectId: string, caseId: string) {
  const [versions, setVersions] = useState<TestCaseVersion[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  useEffect(() => {
    let active = true
    void listTestCaseVersions(projectId, caseId)
      .then((items) => {
        if (active) {
          setVersions(items)
          setLoading(false)
        }
      })
      .catch((reason: unknown) => {
        if (active) {
          setLoadError(apiErrorMessage(reason))
          setLoading(false)
        }
      })
    return () => {
      active = false
    }
  }, [projectId, caseId])
  return { versions, loading, loadError }
}

function canRunCase(
  source: RunCaseSource | undefined,
  version: number | undefined,
  versions: TestCaseVersion[],
  fingerprint: string | undefined,
  loading: boolean,
  error: string | null,
): boolean {
  if (loading || error || !source) return false
  return source === 'published'
    ? versions.some((candidate) => candidate.version === version)
    : Boolean(fingerprint)
}

function caseRunInput(
  source: RunCaseSource,
  version: number | undefined,
  fingerprint: string | undefined,
): RunCaseInput {
  if (source === 'published') return { source, version }
  return { source, publish_draft: true, expected_draft_fingerprint: fingerprint }
}

function RunCaseDetails({
  item,
  workflow,
  environment,
  versions,
  source,
  version,
  error,
  onSource,
  onVersion,
}: {
  item: TestCase
  workflow?: Workflow
  environment?: Environment
  versions: TestCaseVersion[]
  source: RunCaseSource | undefined
  version: number | undefined
  error: string | null
  onSource: (source: RunCaseSource) => void
  onVersion: (version: number) => void
}) {
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <RunCaseContext
        item={item}
        workflow={workflow}
        environment={environment}
        versions={versions}
      />
      <Radio.Group value={source} onChange={(event) => onSource(event.target.value)}>
        {item.current_version && <Radio value="published">运行已发布用例版本</Radio>}
        <Radio value="draft">发布已保存草稿并运行</Radio>
      </Radio.Group>
      {source === 'published' && (
        <Select
          aria-label="运行用例版本"
          value={version}
          options={versions.map((candidate) => ({
            value: candidate.version,
            label: `用例 v${candidate.version} · 流程 v${candidate.definition.workflow_version}`,
          }))}
          onChange={onVersion}
        />
      )}
      {source === 'draft' && (
        <Typography.Text type="secondary">
          仅发布服务器中已保存的草稿；新版本将固定所选流程版本。
        </Typography.Text>
      )}
      {error && <Typography.Text type="danger">{error}</Typography.Text>}
    </Space>
  )
}

function RunCaseContext({
  item,
  workflow,
  environment,
  versions,
}: {
  item: TestCase
  workflow?: Workflow
  environment?: Environment
  versions: TestCaseVersion[]
}) {
  const current = versions.find((candidate) => candidate.version === item.current_version)
  const draftChanged = current ? hasDraftChanges(item, current, workflow) : true
  return (
    <>
      <Typography.Text>
        流程：{workflow?.name ?? '流程不可用'} · 环境：{environment?.name ?? '环境不可用'}
      </Typography.Text>
      {item.current_version && (
        <Typography.Text>
          当前已发布用例 v{item.current_version}；
          {draftChanged ? '草稿的执行定义有未发布修改' : '草稿执行定义与当前版本相同'}
        </Typography.Text>
      )}
    </>
  )
}

function hasDraftChanges(item: TestCase, current: TestCaseVersion, workflow?: Workflow): boolean {
  const draft = item.draft_definition
  const saved = current.definition
  const resolvedVersion = draft.workflow_version ?? workflow?.current_version
  const sorted = (value: Record<string, string>) =>
    JSON.stringify(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)))
  return (
    draft.workflow_id !== saved.workflow_id ||
    resolvedVersion !== saved.workflow_version ||
    draft.environment_id !== saved.environment_id ||
    sorted(draft.runtime_variables) !== sorted(saved.runtime_variables) ||
    sorted(draft.runtime_headers) !== sorted(saved.runtime_headers)
  )
}

export function AddCaseToPlanDialog({
  item,
  initialVersion,
  projectId,
  onClose,
  onCreate,
}: {
  item: TestCase
  initialVersion?: number
  projectId: string
  onClose: () => void
  onCreate?: (version: number) => void
}) {
  const client = useQueryClient()
  const { versions, loading, loadError } = useCaseVersions(projectId, item.id)
  const [version, setVersion] = useState(initialVersion ?? item.current_version ?? undefined)
  const selectedVersion = versions.find((candidate) => candidate.version === version)
  const [page, setPage] = useState(1)
  const [plans, setPlans] = useState<TestPlan[]>([])
  const [total, setTotal] = useState(0)
  const [planId, setPlanId] = useState<string>()
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    let active = true
    void listTestPlans(projectId, page, 20)
      .then((result) => {
        if (active) {
          setPlans(result.items)
          setTotal(result.total)
          setError(null)
        }
      })
      .catch((reason: unknown) => {
        if (active) setError(apiErrorMessage(reason))
      })
    return () => {
      active = false
    }
  }, [projectId, page])
  const submit = async () => {
    if (!selectedVersion || !planId) return
    setSaving(true)
    try {
      await addCaseToPlan(projectId, planId, item.id, selectedVersion.version)
      await client.invalidateQueries({ queryKey: ['test-plans', projectId] })
      await client.invalidateQueries({ queryKey: ['asset-plans', projectId] })
      onClose()
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setSaving(false)
    }
  }
  return (
    <Modal
      title="加入测试计划"
      open
      onCancel={onClose}
      onOk={() => void submit()}
      okButtonProps={{ disabled: !canJoinPlan(planId, selectedVersion, loading, loadError) }}
      confirmLoading={saving}
    >
      <Space direction="vertical" style={{ width: '100%' }}>
        <Typography.Text>
          {item.name} · 固定用例 v{version ?? '—'}。加入计划不会立即执行。
        </Typography.Text>
        <Select
          aria-label="加入计划的用例版本"
          value={version}
          loading={loading}
          disabled={saving}
          options={versions.map((candidate) => ({
            value: candidate.version,
            label: `用例 v${candidate.version}`,
          }))}
          onChange={setVersion}
        />
        {onCreate && (
          <Button
            disabled={!selectedVersion || saving || Boolean(loadError)}
            onClick={() => selectedVersion && onCreate(selectedVersion.version)}
          >
            新建计划
          </Button>
        )}
        <Select
          aria-label="选择测试计划"
          value={planId}
          options={plans.map((plan) => ({ value: plan.id, label: plan.name }))}
          onChange={setPlanId}
          placeholder="选择同项目已有计划"
        />
        <Pagination
          current={page}
          pageSize={20}
          total={total}
          onChange={(next) => {
            setPage(next)
            setPlanId(undefined)
          }}
        />
        {(loadError || error) && (
          <Typography.Text type="danger">{loadError ?? error}</Typography.Text>
        )}
      </Space>
    </Modal>
  )
}

function canJoinPlan(
  planId: string | undefined,
  version: TestCaseVersion | undefined,
  loading: boolean,
  error: string | null,
): boolean {
  return Boolean(planId && version && !loading && !error)
}

export function SuiteDialog({
  current,
  cases,
  folders,
  submitting,
  assetOptionsLoading = false,
  assetOptionsError = null,
  onClose,
  onSave,
}: {
  current: TestSuite | null
  cases: TestCase[]
  folders: Folder[]
  submitting: boolean
  assetOptionsLoading?: boolean
  assetOptionsError?: Error | null
  onClose: () => void
  onSave: (input: TestSuiteDraftInput) => Promise<void>
}) {
  const [form] = Form.useForm<SuiteFormValues>()
  const [error, setError] = useState<string | null>(null)
  async function save() {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    setError(null)
    try {
      await onSave(suiteInput(values, cases, current ?? undefined))
    } catch (failure) {
      setError(apiErrorMessage(failure))
    }
  }
  return (
    <Modal
      title={suiteDialogTitle(current)}
      open
      destroyOnHidden
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={() => void save()}
      okButtonProps={{
        disabled: assetOptionsLoading || Boolean(assetOptionsError) || !cases.length,
      }}
    >
      <SuiteAssetOptionsStatus
        loading={assetOptionsLoading}
        error={assetOptionsError}
        empty={!cases.length}
      />
      <Form form={form} layout="vertical" initialValues={suiteDialogDefaults(current)}>
        <Form.Item name="name" label="套件名称" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <SuiteCaseVersions form={form} cases={cases} current={current} />
        <Form.Item name="description" label="说明">
          <Input.TextArea rows={2} />
        </Form.Item>
        <Form.Item name="caseIds" label="已发布测试用例" rules={[{ required: true }]}>
          <Select mode="multiple" showSearch optionFilterProp="label" options={cases.map(option)} />
        </Form.Item>
        <Typography.Text type="secondary">
          套件成员独立运行；展示顺序不代表共享变量或响应。
        </Typography.Text>
        <Form.Item name="folderId" label="目录">
          <Select allowClear options={folders.map(option)} />
        </Form.Item>
        <Form.Item name="tags" label="标签">
          <Select mode="tags" tokenSeparators={[',']} />
        </Form.Item>
      </Form>
      {error && <Alert type="error" showIcon title="保存套件失败" description={error} />}
    </Modal>
  )
}

function SuiteAssetOptionsStatus({
  loading,
  error,
  empty,
}: {
  loading: boolean
  error: Error | null
  empty: boolean
}) {
  if (loading) return <Alert type="info" title="正在读取完整已发布用例列表…" />
  if (error) {
    return <Alert type="error" title="用例选择列表读取失败" description={apiErrorMessage(error)} />
  }
  if (empty) return <Alert type="info" title="尚无已发布用例，请先创建并发布用例" />
  return null
}

function SuiteCaseVersions({
  form,
  cases,
  current,
}: {
  form: ReturnType<typeof Form.useForm<SuiteFormValues>>[0]
  cases: TestCase[]
  current: TestSuite | null
}) {
  const ids: string[] = Form.useWatch('caseIds', form) ?? []
  return (
    <div className="suite-version-fields">
      {ids.map((id) => {
        const item = cases.find((candidate) => candidate.id === id)
        const pinned = current?.draft_definition.items.find(
          (candidate) => candidate.test_case_id === id,
        )
        return (
          <Form.Item
            key={id}
            name={['memberVersions', id]}
            label={`${item?.name ?? id}：用例版本`}
            initialValue={pinned ? pinned.test_case_version : item?.current_version}
            rules={[{ type: 'integer', min: 1 }]}
            extra="留空时在发布套件时固定最新已发布用例版本。"
          >
            <InputNumber
              min={1}
              max={item?.current_version ?? undefined}
              placeholder="发布时固定最新"
            />
          </Form.Item>
        )
      })}
    </div>
  )
}

export function DiffDialog({
  diff,
  onClose,
}: {
  diff: ReturnType<typeof useTestAssets>['diff']
  onClose: () => void
}) {
  return (
    <Modal
      title={diff ? `版本 Diff：v${diff.from_version} → v${diff.to_version}` : '版本 Diff'}
      open={Boolean(diff)}
      width={760}
      destroyOnHidden
      footer={null}
      onCancel={onClose}
    >
      <Table
        rowKey="path"
        size="small"
        pagination={false}
        dataSource={diff?.changes ?? []}
        columns={[
          { title: '字段', dataIndex: 'path', width: 220 },
          { title: '变更前', dataIndex: 'before', render: jsonValue },
          { title: '变更后', dataIndex: 'after', render: jsonValue },
        ]}
      />
    </Modal>
  )
}

function versionLabel(version: number | null) {
  return version ? <Tag color="green">v{version}</Tag> : <Tag>未发布</Tag>
}

function option(item: { id: string; name: string }) {
  return { value: item.id, label: item.name }
}

function jsonValue(value: unknown) {
  return <Typography.Text code>{JSON.stringify(value)}</Typography.Text>
}

function caseDialogTitle(current: TestCase | null) {
  return current ? '编辑测试用例草稿' : '新建测试用例'
}

function caseDialogDefaults(current: TestCase | null): Partial<CaseFormValues> {
  if (!current)
    return {
      description: '',
      tags: [],
      workflowVersion: null,
      runtimeVariables: [],
      runtimeHeaders: [],
    }
  return {
    name: current.name,
    description: current.description,
    folderId: current.folder_id ?? undefined,
    tags: current.tags,
    workflowId: current.draft_definition.workflow_id,
    workflowVersion: current.draft_definition.workflow_version,
    environmentId: current.draft_definition.environment_id,
    runtimeVariables: entries(current.draft_definition.runtime_variables),
    runtimeHeaders: entries(current.draft_definition.runtime_headers),
  }
}

function suiteDialogTitle(current: TestSuite | null) {
  return current ? '编辑测试套件草稿' : '新建测试套件'
}

function suiteDialogDefaults(current: TestSuite | null): Partial<SuiteFormValues> {
  if (!current) return { description: '', tags: [], caseIds: [], memberVersions: {} }
  return {
    name: current.name,
    description: current.description,
    folderId: current.folder_id ?? undefined,
    tags: current.tags,
    caseIds: current.draft_definition.items.map((item) => item.test_case_id),
    memberVersions: Object.fromEntries(
      current.draft_definition.items.map((item) => [item.test_case_id, item.test_case_version]),
    ),
  }
}
