import {
  CopyOutlined,
  DiffOutlined,
  EditOutlined,
  FolderOpenOutlined,
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
  Checkbox,
  Dropdown,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import ContractAutomationPanel from '../features/contracts/ContractAutomationPanel'
import { useProjectContext } from '../features/projects/use-project-context'
import AssetDetailDrawer from '../features/test-assets/AssetDetailDrawer'
import AssetPlanDialog from '../features/test-assets/AssetPlanDialog'
import { AssetHistoryNotice } from '../features/test-assets/AssetRunEvidence'
import {
  PublishedCaseBinding,
  RecentAssetCell,
  type AssetTableWorkspace,
} from '../features/test-assets/AssetTableContext'
import type {
  AssetKind,
  PublishedAssetTarget,
} from '../features/test-assets/asset-workspace-service'
import { useAssetHistory } from '../features/test-assets/use-asset-history'
import { useTestAssets } from '../features/test-assets/use-test-assets'
import type {
  TestCaseDraftInput,
  TestSuiteDraftInput,
} from '../features/test-assets/test-asset-service'
import {
  caseInput,
  editorKey,
  folderItems,
  pageItems,
  suiteInput,
  type CaseFormValues,
  type SuiteFormValues,
} from '../features/test-assets/test-asset-view-model'
import {
  apiErrorMessage,
  type Environment,
  type Folder,
  type TestCase,
  type TestSuite,
  type Workflow,
} from '../lib/api'

export default function TestAssetsPage() {
  const { projectId } = useProjectContext()
  return <TestAssetsWorkspace key={projectId} />
}

function TestAssetsWorkspace() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { message } = App.useApp()
  const state = useTestAssets()
  const history = useAssetHistory(state.projectId)
  const [caseEditor, setCaseEditor] = useState<TestCase | null | undefined>(undefined)
  const [suiteEditor, setSuiteEditor] = useState<TestSuite | null | undefined>(undefined)
  const [selectedCases, setSelectedCases] = useState<string[]>([])
  const [selectedSuites, setSelectedSuites] = useState<string[]>([])
  const [folderId, setFolderId] = useState<string | null>(null)
  const [casePage, setCasePage] = useState(1)
  const [suitePage, setSuitePage] = useState(1)
  const [plan, setPlan] = useState<{ targets: PublishedAssetTarget[]; execute: boolean } | null>(
    null,
  )
  const cases = pageItems(state.cases.data)
  const suites = pageItems(state.suites.data)
  const publishedCases = pageItems(state.caseOptions.data).filter((item) => item.current_version)
  const browseFolder = searchParams.get('folder') ?? 'all'
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
    next.set('type', key === 'suites' ? 'suite' : key === 'contracts' ? 'contracts' : 'case')
    next.delete('focus')
    next.delete('version')
    setSearchParams(next)
  }
  const workspace: AssetTableWorkspace = {
    projectId: state.projectId ?? '',
    page: casePage,
    onPage: (page) => {
      setCasePage(page)
      setSelectedCases([])
    },
    onFocus: focus,
    onPlan: (target, execute) => setPlan({ targets: [target], execute }),
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
          cases={cases}
          suites={suites}
          loaded={Boolean(state.cases.data && state.suites.data)}
          onBrowse={browse}
        />
        <div className="test-asset-main">
          <AssetCatalogScope state={state} />
          <AssetHistoryNotice history={history} />
          <AssetTabs
            state={state}
            cases={filterLoadedAssets(cases, browseFolder)}
            suites={filterLoadedAssets(suites, browseFolder)}
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
              onPage: (page) => {
                setSuitePage(page)
                setSelectedSuites([])
              },
            }}
            onChangeTab={changeTab}
            onAction={action}
            onPlan={(targets) => setPlan({ targets, execute: false })}
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
        onPlan={(target, execute) => setPlan({ targets: [target], execute })}
      />
      <WorkspaceAssetPlan projectId={state.projectId} plan={plan} onClose={() => setPlan(null)} />
    </div>
  )
}

function AssetCatalogScope({ state }: { state: AssetState }) {
  const loading = state.cases.isPending || state.suites.isPending
  return (
    <Typography.Paragraph type="secondary" className="asset-loaded-scope">
      {loading
        ? '正在分页读取完整资产目录…'
        : `筛选命中 ${state.cases.data?.total ?? '—'} 个用例、${state.suites.data?.total ?? '—'} 个套件。`}
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
      cases={pageItems(state.caseOptions.data)}
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

function filterLoadedAssets<T extends { folder_id: string | null }>(
  items: T[],
  folder: string,
): T[] {
  if (folder === 'all') return items
  return items.filter((item) => item.folder_id === (folder === 'unfiled' ? null : folder))
}

function AssetDirectory({
  folders,
  selected,
  cases,
  suites,
  loaded,
  onBrowse,
}: {
  folders: Folder[]
  selected: string
  cases: TestCase[]
  suites: TestSuite[]
  loaded: boolean
  onBrowse: (folder: string) => void
}) {
  const entries = [
    { id: 'all', name: '全部测试资产' },
    { id: 'unfiled', name: '未分类' },
    ...folders
      .map((folder) => ({ ...folder, name: directoryPath(folder, folders) }))
      .sort((a, b) => a.name.localeCompare(b.name, 'zh-CN')),
  ]
  return (
    <Card title="用例目录" className="test-asset-directory">
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
            <Tag>
              {loaded
                ? filterLoadedAssets(cases, entry.id).length +
                  filterLoadedAssets(suites, entry.id).length
                : '—'}
            </Tag>
          </Button>
        ))}
      </nav>
      <Typography.Paragraph type="secondary">
        数量覆盖全部筛选结果。批量移动目标在列表工具栏选择。
      </Typography.Paragraph>
    </Card>
  )
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
        <Typography.Title level={2}>测试资产</Typography.Title>
        <Typography.Text type="secondary">
          管理可复用的用例、模板与套件；发布版本不可变，计划运行固定展开快照。
        </Typography.Text>
      </div>
      <Space wrap>
        <Input.Search
          aria-label="搜索测试资产"
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
        activeKey={
          props.focusedType === 'suite'
            ? 'suites'
            : props.focusedType === 'contracts'
              ? 'contracts'
              : 'cases'
        }
        onChange={props.onChangeTab}
        items={[
          caseTab(props),
          suiteTab(props),
          { key: 'contracts', label: '契约自动化', children: <ContractAutomationPanel /> },
        ]}
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
    label: `测试用例 (${cases.length})`,
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
        onPlan={() => props.onPlan(selectedTargets('case', cases, selectedCases))}
        planDisabled={!state.canEdit || !allPublished(cases, selectedCases)}
      >
        <CaseTable
          items={cases}
          focusedId={props.focusedId}
          loading={state.cases.isLoading}
          selected={selectedCases}
          onSelect={setSelectedCases}
          onEdit={setCaseEditor}
          onPublish={(item) => void props.onAction(() => state.publishCase(item.id))}
          onClone={(item) => void props.onAction(() => state.cloneCase(item))}
          onDiff={(item) => void props.onAction(() => state.loadCaseDiff(item))}
          workspace={props.workspace}
        />
      </AssetPane>
    ),
  }
}

function suiteTab(props: Parameters<typeof AssetTabs>[0]) {
  const {
    state,
    suites,
    publishedCases,
    selectedSuites,
    folderId,
    setSuiteEditor,
    setSelectedSuites,
    setFolderId,
  } = props
  return {
    key: 'suites',
    label: `测试套件 (${suites.length})`,
    children: (
      <AssetPane
        title="测试套件"
        selected={selectedSuites}
        folderId={folderId}
        folders={folderItems(state)}
        createDisabled={!state.canEdit || !publishedCases.length}
        onFolderChange={setFolderId}
        onCreate={() => setSuiteEditor(null)}
        onMove={() =>
          void props.onAction(async () => {
            await state.moveSuites({ ids: selectedSuites, folderId })
            setSelectedSuites([])
          })
        }
        moveDisabled={!state.canEdit}
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
        <Typography.Text type="secondary">仅选择当前页</Typography.Text>
      </Space>
      {children}
    </>
  )
}

export function CaseTable({
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
  items: TestCase[]
  loading: boolean
  selected: string[]
  onSelect: (ids: string[]) => void
  onEdit: (item: TestCase) => void
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
            />
          ),
        },
      ]}
    />
  )
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
    {
      title: '最近结果（近 20 次计划运行）',
      width: 200,
      render: (_: unknown, item: TestCase) => (
        <RecentAssetCell kind="case" id={item.id} workspace={workspace} />
      ),
    },
  ]
}

function suiteContextColumns(workspace: AssetTableWorkspace | undefined) {
  if (!workspace) return []
  return [
    {
      title: '最近结果（近 20 次计划运行）',
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
}: {
  version: number | null
  onEdit: () => void
  onPublish: () => void
  onClone: () => void
  onDiff: () => void
  compact?: boolean
  canEdit?: boolean
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
  workflows,
  environments,
  folders,
  submitting,
  onClose,
  onSave,
}: {
  current: TestCase | null
  workflows: Workflow[]
  environments: Environment[]
  folders: Folder[]
  submitting: boolean
  onClose: () => void
  onSave: (input: TestCaseDraftInput) => Promise<void>
}) {
  const [form] = Form.useForm<CaseFormValues>()
  const definition = current?.draft_definition
  const [error, setError] = useState<string | null>(null)
  async function save() {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    setError(null)
    try {
      await onSave(caseInput(values, definition))
    } catch (failure) {
      setError(apiErrorMessage(failure))
    }
  }
  return (
    <Modal
      title={caseDialogTitle(current)}
      open
      destroyOnHidden
      confirmLoading={submitting}
      onCancel={onClose}
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
            onChange={() => form.setFieldValue('workflowVersion', null)}
          />
        </Form.Item>
        <CaseWorkflowVersion form={form} workflows={workflows} />
        <Form.Item name="environmentId" label="运行环境" rules={[{ required: true }]}>
          <Select showSearch optionFilterProp="label" options={environments.map(option)} />
        </Form.Item>
        <Form.Item name="folderId" label="目录">
          <Select allowClear options={folders.map(option)} />
        </Form.Item>
        <Form.Item name="tags" label="标签">
          <Select mode="tags" tokenSeparators={[',']} />
        </Form.Item>
        <Form.Item name="isTemplate" valuePropName="checked">
          <Checkbox>设为用例模板</Checkbox>
        </Form.Item>
      </Form>
      {error && <Alert type="error" showIcon title="保存用例失败" description={error} />}
    </Modal>
  )
}

export function SuiteDialog({
  current,
  cases,
  folders,
  submitting,
  onClose,
  onSave,
}: {
  current: TestSuite | null
  cases: TestCase[]
  folders: Folder[]
  submitting: boolean
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
      await onSave(suiteInput(values, cases, current?.draft_definition.items))
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
    >
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

function CaseWorkflowVersion({
  form,
  workflows,
}: {
  form: ReturnType<typeof Form.useForm<CaseFormValues>>[0]
  workflows: Workflow[]
}) {
  const workflowId = Form.useWatch('workflowId', form)
  const workflow = workflows.find((item) => item.id === workflowId)
  return (
    <Form.Item
      name="workflowVersion"
      label="流程版本"
      extra="留空时在发布用例时固定最新已发布流程版本。"
      rules={[{ type: 'integer', min: 1 }]}
    >
      <InputNumber
        min={1}
        max={workflow?.current_version ?? undefined}
        disabled={!workflowId}
        placeholder="发布时固定最新"
      />
    </Form.Item>
  )
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
            name={['caseVersions', id]}
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
  if (!current) return { description: '', tags: [], isTemplate: false, workflowVersion: null }
  return {
    name: current.name,
    description: current.description,
    folderId: current.folder_id ?? undefined,
    tags: current.tags,
    isTemplate: current.is_template,
    workflowId: current.draft_definition.workflow_id,
    workflowVersion: current.draft_definition.workflow_version,
    environmentId: current.draft_definition.environment_id,
  }
}

function suiteDialogTitle(current: TestSuite | null) {
  return current ? '编辑测试套件草稿' : '新建测试套件'
}

function suiteDialogDefaults(current: TestSuite | null): Partial<SuiteFormValues> {
  if (!current) return { description: '', tags: [], caseIds: [] }
  return {
    name: current.name,
    description: current.description,
    folderId: current.folder_id ?? undefined,
    tags: current.tags,
    caseIds: current.draft_definition.items.map((item) => item.test_case_id),
    caseVersions: Object.fromEntries(
      current.draft_definition.items.map((item) => [item.test_case_id, item.test_case_version]),
    ),
  }
}
