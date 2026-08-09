import {
  CopyOutlined,
  DiffOutlined,
  EditOutlined,
  FolderOpenOutlined,
  PlusOutlined,
  RocketOutlined,
} from '@ant-design/icons'
import {
  Button,
  Card,
  Checkbox,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'

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
import type { Environment, Folder, TestCase, TestSuite, Workflow } from '../lib/api'

export default function TestAssetsPage() {
  const state = useTestAssets()
  const [caseEditor, setCaseEditor] = useState<TestCase | null | undefined>(undefined)
  const [suiteEditor, setSuiteEditor] = useState<TestSuite | null | undefined>(undefined)
  const [selectedCases, setSelectedCases] = useState<string[]>([])
  const [selectedSuites, setSelectedSuites] = useState<string[]>([])
  const [folderId, setFolderId] = useState<string | null>(null)
  const cases = pageItems(state.cases.data)
  const suites = pageItems(state.suites.data)
  const publishedCases = cases.filter((item) => item.current_version)

  return (
    <>
      <AssetHeading state={state} />
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
    </>
  )
}

type AssetState = ReturnType<typeof useTestAssets>
type EditorSetter<T> = (value: T | null | undefined) => void

function AssetHeading({ state }: { state: AssetState }) {
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
}) {
  return (
    <Card>
      <Tabs animated={false} items={[caseTab(props), suiteTab(props)]} />
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
          loading={state.cases.isLoading}
          selected={selectedCases}
          onSelect={setSelectedCases}
          onEdit={setCaseEditor}
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
  loading,
  selected,
  onSelect,
  onEdit,
  onPublish,
  onClone,
  onDiff,
}: {
  items: TestCase[]
  loading: boolean
  selected: string[]
  onSelect: (ids: string[]) => void
  onEdit: (item: TestCase) => void
  onPublish: (item: TestCase) => void
  onClone: (item: TestCase) => void
  onDiff: (item: TestCase) => void
}) {
  return (
    <Table
      rowKey="id"
      size="small"
      loading={loading}
      pagination={false}
      dataSource={items}
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

export function SuiteTable({
  items,
  loading,
  selected,
  onSelect,
  onEdit,
  onPublish,
  onClone,
  onDiff,
}: {
  items: TestSuite[]
  loading: boolean
  selected: string[]
  onSelect: (ids: string[]) => void
  onEdit: (item: TestSuite) => void
  onPublish: (item: TestSuite) => void
  onClone: (item: TestSuite) => void
  onDiff: (item: TestSuite) => void
}) {
  return (
    <Table
      rowKey="id"
      size="small"
      loading={loading}
      pagination={false}
      dataSource={items}
      rowSelection={{ selectedRowKeys: selected, onChange: (keys) => onSelect(keys.map(String)) }}
      columns={[
        { title: '名称', dataIndex: 'name' },
        {
          title: '用例数',
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
  return (
    <Modal
      title={caseDialogTitle(current)}
      open
      destroyOnHidden
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={() =>
        void form.validateFields().then((values) => onSave(caseInput(values, definition)))
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
          <Select options={workflows.map(option)} />
        </Form.Item>
        <Form.Item name="environmentId" label="运行环境" rules={[{ required: true }]}>
          <Select options={environments.map(option)} />
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
  return (
    <Modal
      title={suiteDialogTitle(current)}
      open
      destroyOnHidden
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={() => void form.validateFields().then((values) => onSave(suiteInput(values, cases)))}
    >
      <Form form={form} layout="vertical" initialValues={suiteDialogDefaults(current)}>
        <Form.Item name="name" label="套件名称" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item name="description" label="说明">
          <Input.TextArea rows={2} />
        </Form.Item>
        <Form.Item name="caseIds" label="已发布测试用例" rules={[{ required: true }]}>
          <Select mode="multiple" options={cases.map(option)} />
        </Form.Item>
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
  if (!current) return { description: '', tags: [], isTemplate: false }
  return {
    name: current.name,
    description: current.description,
    folderId: current.folder_id ?? undefined,
    tags: current.tags,
    isTemplate: current.is_template,
    workflowId: current.draft_definition.workflow_id,
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
  }
}
