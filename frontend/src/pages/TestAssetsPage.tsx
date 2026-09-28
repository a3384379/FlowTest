import {
  CopyOutlined,
  DiffOutlined,
  EditOutlined,
  FolderOpenOutlined,
  MinusCircleOutlined,
  MoreOutlined,
  PlusOutlined,
  RocketOutlined,
} from '@ant-design/icons'
import {
  Button,
  Card,
  Dropdown,
  Form,
  Input,
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

import {
  addCaseToPlan,
  getTestCase,
  getTestSuite,
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
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const state = useTestAssets()
  const [caseEditor, setCaseEditor] = useState<TestCase | null | undefined>(undefined)
  const [suiteEditor, setSuiteEditor] = useState<TestSuite | null | undefined>(undefined)
  const [runCase, setRunCase] = useState<TestCase | null>(null)
  const [planCase, setPlanCase] = useState<TestCase | null>(null)
  const [recentRun, setRecentRun] = useState<TestCaseRun | null>(null)
  const [focusError, setFocusError] = useState<string | null>(null)
  const [selectedCases, setSelectedCases] = useState<string[]>([])
  const [selectedSuites, setSelectedSuites] = useState<string[]>([])
  const [folderId, setFolderId] = useState<string | null>(null)
  const cases = pageItems(state.cases.data)
  const suites = pageItems(state.suites.data)
  const publishedCases = pageItems(state.suiteCaseOptions.data).filter(
    (item) => item.current_version,
  )
  const focusedId = searchParams.get('focus') ?? undefined
  const focusedType = searchParams.get('type')
  const projectId = state.projectId
  const setSearch = state.setSearch
  const setCasePage = state.setCasePage
  const setSuitePage = state.setSuitePage
  useEffect(() => {
    if (!focusedId || !projectId || focusedType === 'contracts') return
    let active = true
    const request =
      focusedType === 'suite'
        ? getTestSuite(projectId, focusedId)
        : getTestCase(projectId, focusedId)
    void request
      .then((item) => {
        if (!active) return
        setFocusError(null)
        setSearch(item.name)
        setCasePage(1)
        setSuitePage(1)
      })
      .catch((reason: unknown) => {
        if (active) setFocusError(`无法定位深链目标：${apiErrorMessage(reason)}`)
      })
    return () => {
      active = false
    }
  }, [focusedId, focusedType, projectId, setCasePage, setSearch, setSuitePage])
  useEffect(() => {
    if (focusedType === 'contracts' && state.projectId) {
      navigate(`/projects/${state.projectId}/contracts?tab=automation`, { replace: true })
    }
  }, [focusedType, navigate, state.projectId])

  return (
    <>
      <AssetHeading state={state} />
      {focusError && <Typography.Text type="danger">{focusError}</Typography.Text>}
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
        onRunCase={setRunCase}
        onPlanCase={setPlanCase}
        onViewRun={(run) => {
          if (state.projectId)
            navigate(
              `/projects/${state.projectId}/workflows?focus=${run.workflow_id}&execution=${run.execution_id}`,
            )
        }}
        focusedId={focusedId}
        focusedType={focusedType}
      />
      <AssetDialogs
        state={state}
        caseEditor={caseEditor}
        suiteEditor={suiteEditor}
        publishedCases={publishedCases}
        setCaseEditor={setCaseEditor}
        setSuiteEditor={setSuiteEditor}
      />
      {state.diff && <DiffDialog diff={state.diff} onClose={() => state.setDiff(null)} />}
      {runCase && state.projectId && (
        <RunCaseDialog
          key={runCase.id}
          item={runCase}
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
          projectId={state.projectId}
          onClose={() => setPlanCase(null)}
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

type AssetState = ReturnType<typeof useTestAssets>
type EditorSetter<T> = (value: T | null | undefined) => void

function AssetHeading({ state }: { state: AssetState }) {
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
          defaultValue={state.search}
          onSearch={state.setSearch}
        />
        <Input
          aria-label="标签筛选"
          allowClear
          placeholder="标签筛选"
          value={state.tag}
          onChange={(event) => state.setTag(event.target.value)}
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
}) {
  return (
    <Card>
      <Tabs
        animated={false}
        defaultActiveKey={props.focusedType === 'suite' ? 'suites' : 'cases'}
        items={[caseTab(props), suiteTab(props)]}
      />
    </Card>
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
          !pageItems(state.workflows.data).some((workflow) => workflow.current_version !== null) ||
          !state.environments.data?.length
        }
        onFolderChange={setFolderId}
        onCreate={() => setCaseEditor(null)}
        onMove={() =>
          void state.moveCases({ ids: selectedCases, folderId }).then(() => setSelectedCases([]))
        }
      >
        <CaseTable
          items={cases}
          workflows={pageItems(state.workflows.data)}
          environments={state.environments.data ?? []}
          latestRuns={state.latestRuns.data}
          latestLoading={state.latestRuns.isLoading}
          latestError={state.latestRuns.isError}
          total={state.cases.data?.total}
          page={state.casePage}
          onPageChange={state.setCasePage}
          focusedId={props.focusedId}
          loading={state.cases.isLoading}
          selected={selectedCases}
          onSelect={setSelectedCases}
          onEdit={setCaseEditor}
          onRun={props.onRunCase}
          onPlan={props.onPlanCase}
          onViewRun={props.onViewRun}
          onPublish={(item) => void state.publishCase(item.id)}
          onClone={(item) => void state.cloneCase(item)}
          onDiff={(item) => void state.loadCaseDiff(item)}
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
        createDisabled={!publishedCases.length}
        onFolderChange={setFolderId}
        onCreate={() => setSuiteEditor(null)}
        onMove={() =>
          void state.moveSuites({ ids: selectedSuites, folderId }).then(() => setSelectedSuites([]))
        }
      >
        <SuiteTable
          items={suites}
          total={state.suites.data?.total}
          page={state.suitePage}
          onPageChange={state.setSuitePage}
          focusedId={props.focusedId}
          loading={state.suites.isLoading}
          selected={selectedSuites}
          onSelect={setSelectedSuites}
          onEdit={setSuiteEditor}
          onPublish={(item) => void state.publishSuite(item.id)}
          onClone={(item) => void state.cloneSuite(item)}
          onDiff={(item) => void state.loadSuiteDiff(item)}
        />
      </AssetPane>
    ),
  }
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
        <Button icon={<FolderOpenOutlined />} disabled={!selected.length} onClick={onMove}>
          批量移动 ({selected.length})
        </Button>
      </Space>
      {children}
    </>
  )
}

export function CaseTable({
  items,
  workflows = [],
  environments = [],
  latestRuns,
  latestLoading = false,
  latestError = false,
  total,
  page,
  onPageChange,
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
}: {
  items: TestCase[]
  workflows?: Workflow[]
  environments?: Environment[]
  latestRuns?: TestCaseRun[]
  latestLoading?: boolean
  latestError?: boolean
  total?: number
  page?: number
  onPageChange?: (page: number) => void
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
}) {
  return (
    <Table
      rowKey="id"
      size="small"
      loading={loading}
      pagination={
        onPageChange ? { current: page, pageSize: 20, total, onChange: onPageChange } : false
      }
      dataSource={items}
      rowClassName={(item) => (item.id === focusedId ? 'selected-row' : '')}
      rowSelection={{ selectedRowKeys: selected, onChange: (keys) => onSelect(keys.map(String)) }}
      columns={[
        { title: '名称', dataIndex: 'name' },
        {
          title: '标签',
          dataIndex: 'tags',
          render: (tags: string[]) => tags.map((tag) => <Tag key={tag}>{tag}</Tag>),
        },
        {
          title: '类型',
          render: (_, item) => (item.is_template ? <Tag color="purple">模板</Tag> : '用例'),
        },
        {
          title: '关联流程',
          render: (_, item) =>
            workflows.find((workflow) => workflow.id === item.draft_definition.workflow_id)?.name ??
            '流程不可用',
        },
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
}: {
  item: TestCase
  onRun?: (item: TestCase) => void
  onEdit: (item: TestCase) => void
  onPlan?: (item: TestCase) => void
  onPublish: (item: TestCase) => void
  onClone: (item: TestCase) => void
  onDiff: (item: TestCase) => void
}) {
  return (
    <Space size={0}>
      <Button type="link" disabled={!onRun} onClick={() => onRun?.(item)}>
        运行
      </Button>
      <Button type="link" onClick={() => onEdit(item)}>
        编辑
      </Button>
      <Dropdown
        trigger={['click']}
        menu={{
          items: [
            { key: 'plan', label: '加入测试计划', disabled: !item.current_version || !onPlan },
            { key: 'publish', label: '发布新版本' },
            { key: 'clone', label: '克隆' },
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
  total,
  page,
  onPageChange,
  loading,
  selected,
  onSelect,
  onEdit,
  onPublish,
  onClone,
  onDiff,
  focusedId,
}: {
  items: TestSuite[]
  total?: number
  page?: number
  onPageChange?: (page: number) => void
  loading: boolean
  selected: string[]
  onSelect: (ids: string[]) => void
  onEdit: (item: TestSuite) => void
  onPublish: (item: TestSuite) => void
  onClone: (item: TestSuite) => void
  onDiff: (item: TestSuite) => void
  focusedId?: string
}) {
  return (
    <Table
      rowKey="id"
      size="small"
      loading={loading}
      pagination={
        onPageChange ? { current: page, pageSize: 20, total, onChange: onPageChange } : false
      }
      dataSource={items}
      rowClassName={(item) => (item.id === focusedId ? 'selected-row' : '')}
      rowSelection={{ selectedRowKeys: selected, onChange: (keys) => onSelect(keys.map(String)) }}
      columns={[
        { title: '名称', dataIndex: 'name' },
        {
          title: '用例数',
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
          width: 310,
          render: (_, item) => (
            <RowActions
              version={item.current_version}
              onEdit={() => onEdit(item)}
              onPublish={() => onPublish(item)}
              onClone={() => onClone(item)}
              onDiff={() => onDiff(item)}
            />
          ),
        },
      ]}
    />
  )
}

function RowActions({
  version,
  onEdit,
  onPublish,
  onClone,
  onDiff,
}: {
  version: number | null
  onEdit: () => void
  onPublish: () => void
  onClone: () => void
  onDiff: () => void
}) {
  return (
    <Space size={0}>
      <Button type="link" icon={<EditOutlined />} onClick={onEdit}>
        编辑
      </Button>
      <Button type="link" icon={<RocketOutlined />} onClick={onPublish}>
        发布
      </Button>
      <Button type="link" icon={<CopyOutlined />} onClick={onClone}>
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
  return (
    <Modal
      title={caseDialogTitle(current)}
      open
      width={720}
      destroyOnHidden
      confirmLoading={submitting}
      onCancel={close}
      onOk={() =>
        void form
          .validateFields()
          .then((values) => onSave(caseInput(values, definition, current?.is_template ?? false)))
      }
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
  projectId,
  workflow,
  environment,
  submitting,
  onClose,
  onRun,
}: {
  item: TestCase
  projectId: string
  workflow?: Workflow
  environment?: Environment
  submitting: boolean
  onClose: () => void
  onRun: (input: RunCaseInput) => Promise<void>
}) {
  const { versions, loading, loadError } = useCaseVersions(projectId, item.id)
  const [source, setSource] = useState<RunCaseSource | undefined>(
    item.current_version ? undefined : 'draft',
  )
  const [version, setVersion] = useState(item.current_version ?? undefined)
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
  projectId,
  onClose,
}: {
  item: TestCase
  projectId: string
  onClose: () => void
}) {
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
    if (!item.current_version || !planId) return
    setSaving(true)
    try {
      await addCaseToPlan(projectId, planId, item.id, item.current_version)
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
      okButtonProps={{ disabled: !planId || !item.current_version }}
      confirmLoading={saving}
    >
      <Space direction="vertical" style={{ width: '100%' }}>
        <Typography.Text>
          {item.name} · 固定用例 v{item.current_version}。加入计划不会立即执行。
        </Typography.Text>
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
        {error && <Typography.Text type="danger">{error}</Typography.Text>}
      </Space>
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
  const selectedCaseIds = Form.useWatch('caseIds', form) as string[] | undefined
  return (
    <Modal
      title={suiteDialogTitle(current)}
      open
      destroyOnHidden
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={() =>
        void form
          .validateFields()
          .then((values) => onSave(suiteInput(values, cases, current ?? undefined)))
      }
    >
      <Form form={form} layout="vertical" initialValues={suiteDialogDefaults(current)}>
        <Form.Item name="name" label="套件名称" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item name="description" label="说明">
          <Input.TextArea rows={2} />
        </Form.Item>
        <Form.Item name="caseIds" label="已发布测试用例" rules={[{ required: true }]}>
          <Select mode="multiple" showSearch optionFilterProp="label" options={cases.map(option)} />
        </Form.Item>
        {selectedCaseIds?.map((caseId) => {
          const member = cases.find((candidate) => candidate.id === caseId)
          return (
            <Form.Item
              key={caseId}
              name={['memberVersions', caseId]}
              label={`${member?.name ?? caseId} 的用例版本`}
            >
              <Select
                options={[
                  { value: null, label: '发布套件时使用最新用例版本' },
                  ...Array.from({ length: member?.current_version ?? 0 }, (_, index) => ({
                    value: index + 1,
                    label: `固定 v${index + 1}`,
                  })),
                ]}
              />
            </Form.Item>
          )
        })}
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
    </Modal>
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
