import {
  DownloadOutlined,
  EditOutlined,
  ImportOutlined,
  PlayCircleOutlined,
  PlusOutlined,
} from '@ant-design/icons'
import {
  Button,
  Card,
  Dropdown,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'

import ArtifactPanel from '../features/api-console/ArtifactPanel'
import APIWorkbench from '../features/api-console/APIWorkbench'
import CreateDialogs from '../features/api-console/CreateDialogs'
import ExecutionResultPanel from '../features/api-console/ExecutionResultPanel'
import ImportDialog from '../features/api-console/ImportDialog'
import type {
  CreateApiInput,
  CreateEnvironmentInput,
  CreateProjectInput,
} from '../features/api-console/api-service'
import { useApiConsole } from '../features/api-console/use-api-console'
import type { ApiDefinition, Execution, ExecutionDetail } from '../lib/api'

type DialogState = 'project' | 'environment' | 'api' | null

export default function ApiConsolePage() {
  const [dialog, setDialog] = useState<DialogState>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [renameTarget, setRenameTarget] = useState<ApiDefinition | null>(null)
  const consoleState = useApiConsole()
  const currentDefinition = selectedApiDefinition(consoleState)
  const artifacts = artifactItems(consoleState)
  const apis = apiItems(consoleState)
  const history = historyItems(consoleState)

  async function addProject(input: CreateProjectInput) {
    await consoleState.addProject(input)
    setDialog(null)
  }

  async function addEnvironment(input: CreateEnvironmentInput) {
    await consoleState.addEnvironment(input)
    setDialog(null)
  }

  async function addApi(input: CreateApiInput) {
    await consoleState.addApi(input)
    setDialog(null)
  }

  const canCreateAssets = Boolean(consoleState.projectId)
  const canExecute = allSelected([
    consoleState.projectId,
    consoleState.environmentId,
    consoleState.apiId,
  ])

  return (
    <>
      <div className="page-heading">
        <div>
          <Typography.Title level={2}>接口管理</Typography.Title>
          <Typography.Text type="secondary">
            创建接口、发送真实请求，并检查断言和历史记录。
          </Typography.Text>
        </div>
        <Space wrap>
          <Select
            aria-label="当前项目"
            className="context-select"
            loading={consoleState.projects.isLoading}
            placeholder="选择项目"
            value={consoleState.projectId}
            onChange={consoleState.selectProject}
            options={projectOptions(consoleState.projects.data?.items)}
          />
          <Button icon={<PlusOutlined />} onClick={() => setDialog('project')}>
            新建项目
          </Button>
          <Button
            icon={<ImportOutlined />}
            disabled={!canCreateAssets}
            onClick={() => setImportOpen(true)}
          >
            导入接口
          </Button>
          <Dropdown
            menu={{
              items: [
                { key: 'har', label: '导出 HAR' },
                { key: 'curl', label: '导出 cURL' },
                { key: 'bruno', label: '导出 Bruno' },
                { key: 'excel', label: '导出 Excel' },
              ],
              onClick: ({ key }) =>
                consoleState.exportApis(key as 'har' | 'curl' | 'bruno' | 'excel'),
            }}
          >
            <Button
              icon={<DownloadOutlined />}
              disabled={!canCreateAssets}
              loading={consoleState.exporting}
            >
              导出
            </Button>
          </Dropdown>
          <Select
            aria-label="当前环境"
            className="context-select"
            loading={consoleState.environments.isLoading}
            placeholder="选择环境"
            value={consoleState.environmentId}
            onChange={consoleState.setEnvironmentSelection}
            disabled={!canCreateAssets}
            options={projectOptions(consoleState.environments.data)}
          />
          <Button
            icon={<PlusOutlined />}
            disabled={!canCreateAssets}
            onClick={() => setDialog('environment')}
          >
            新建环境
          </Button>
        </Space>
      </div>

      <div className="console-grid">
        <Card
          title="接口列表"
          extra={
            <Button
              type="primary"
              icon={<PlusOutlined />}
              disabled={!canCreateAssets}
              onClick={() => setDialog('api')}
            >
              新建接口
            </Button>
          }
        >
          <ApiTable
            loading={consoleState.apis.isLoading}
            items={apis}
            selectedId={consoleState.apiId}
            onSelect={consoleState.setApiSelection}
            onRename={setRenameTarget}
          />
        </Card>

        <APIWorkbench
          detail={consoleState.apiDetail.data}
          loading={consoleState.apiDetail.isLoading}
          saving={consoleState.savingVersion}
          previewing={consoleState.previewing}
          onSave={consoleState.saveVersion}
          onPreview={consoleState.previewRequest}
          onRename={() => setRenameTarget(currentDefinition)}
          artifacts={artifacts}
        />
      </div>

      <Card
        title="请求运行器"
        className="runner-card"
        extra={<RunnerActions state={consoleState} enabled={canExecute} />}
      >
        <RunnerContent enabled={canExecute} result={consoleState.result} history={history} />
      </Card>

      <ArtifactPanel
        disabled={!canCreateAssets}
        loading={consoleState.artifacts.isLoading}
        uploading={consoleState.uploading}
        items={artifacts}
        onUpload={consoleState.uploadFile}
        onDownload={consoleState.downloadFile}
      />

      <CreateDialogs
        open={dialog}
        submitting={consoleState.submitting}
        onClose={() => setDialog(null)}
        onCreateProject={addProject}
        onCreateEnvironment={addEnvironment}
        onCreateApi={addApi}
        artifacts={artifacts}
      />
      <ImportDialog
        open={importOpen}
        importing={consoleState.importing}
        result={consoleState.lastImport}
        onDiscover={consoleState.discoverImport}
        onPreview={consoleState.previewImport}
        onMerge={consoleState.mergeImport}
        onClose={() => {
          setImportOpen(false)
          consoleState.clearImportResult()
        }}
      />
      <RenameApiDialogContainer
        target={renameTarget}
        saving={consoleState.renamingApi}
        onClose={() => setRenameTarget(null)}
        onRename={consoleState.renameApi}
      />
    </>
  )
}

type ConsoleState = ReturnType<typeof useApiConsole>

function RunnerActions({ state, enabled }: { state: ConsoleState; enabled: boolean }) {
  return (
    <Space>
      <Typography.Text type="secondary">预期状态码</Typography.Text>
      <InputNumber
        aria-label="预期状态码"
        min={100}
        max={599}
        value={state.expectedStatus}
        onChange={(value) => state.setExpectedStatus(value ?? 200)}
      />
      <Button
        type="primary"
        icon={<PlayCircleOutlined />}
        disabled={!enabled}
        loading={state.executing}
        onClick={() => state.execute()}
      >
        发送请求
      </Button>
    </Space>
  )
}

function RunnerContent({
  enabled,
  result,
  history,
}: {
  enabled: boolean
  result: ExecutionDetail | null
  history: Execution[]
}) {
  if (!enabled) {
    return <Empty description="请先准备项目、环境和接口" className="console-empty" />
  }
  return <ExecutionResultPanel result={result} history={history} />
}

type ApiTableProps = {
  loading: boolean
  items: ApiDefinition[]
  selectedId: string | null
  onSelect: (id: string) => void
  onRename: (definition: ApiDefinition) => void
}

function ApiTable({ loading, items, selectedId, onSelect, onRename }: ApiTableProps) {
  return (
    <Table
      rowKey="id"
      size="small"
      loading={loading}
      pagination={false}
      dataSource={items}
      locale={{ emptyText: '暂无接口' }}
      rowClassName={(record) => (record.id === selectedId ? 'selected-row' : '')}
      onRow={(record) => ({ onClick: () => onSelect(record.id) })}
      columns={[
        { title: '名称', dataIndex: 'name' },
        {
          title: '版本',
          dataIndex: 'current_version',
          width: 80,
          render: (version: number) => <Tag color="blue">v{version}</Tag>,
        },
        {
          title: '',
          width: 40,
          render: (_: unknown, definition: ApiDefinition) => (
            <Button
              type="text"
              size="small"
              icon={<EditOutlined />}
              aria-label={`重命名接口 ${definition.name}`}
              onClick={(event) => {
                event.stopPropagation()
                onRename(definition)
              }}
            />
          ),
        },
      ]}
    />
  )
}

function RenameApiDialogContainer({
  target,
  saving,
  onClose,
  onRename,
}: {
  target: ApiDefinition | null
  saving: boolean
  onClose: () => void
  onRename: (targetId: string, name: string) => Promise<ApiDefinition>
}) {
  if (!target) return null

  return (
    <RenameApiDialog
      target={target}
      saving={saving}
      onClose={onClose}
      onRename={(name) => onRename(target.id, name)}
    />
  )
}

function RenameApiDialog({
  target,
  saving,
  onClose,
  onRename,
}: {
  target: ApiDefinition
  saving: boolean
  onClose: () => void
  onRename: (name: string) => Promise<ApiDefinition>
}) {
  const [form] = Form.useForm<{ name: string }>()
  const name = Form.useWatch('name', form)

  async function submit(values: { name: string }) {
    try {
      await onRename(values.name.trim())
      onClose()
    } catch {
      // Mutation errors are rendered by the shared API error message handler.
    }
  }

  return (
    <Modal
      title="重命名接口"
      open
      okText="保存"
      cancelText="取消"
      confirmLoading={saving}
      okButtonProps={{ disabled: !name?.trim() || name.trim() === target.name }}
      onOk={() => form.submit()}
      onCancel={onClose}
    >
      <Form form={form} layout="vertical" initialValues={{ name: target.name }} onFinish={submit}>
        <Form.Item
          name="name"
          label="接口名称"
          rules={[
            { required: true, whitespace: true, message: '请输入接口名称' },
            { max: 200, message: '接口名称不能超过 200 位' },
          ]}
        >
          <Input autoFocus maxLength={200} />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function allSelected(values: Array<string | null>): boolean {
  return values.every(Boolean)
}

function selectedApiDefinition(state: ConsoleState): ApiDefinition | null {
  return state.apiDetail.data ? state.apiDetail.data.definition : null
}

function artifactItems(state: ConsoleState) {
  return state.artifacts.data?.items ?? []
}

function apiItems(state: ConsoleState) {
  return state.apis.data?.items ?? []
}

function historyItems(state: ConsoleState) {
  return state.history.data?.items ?? []
}

function projectOptions(items?: Array<{ id: string; name: string }>) {
  return items?.map((item) => ({ value: item.id, label: item.name }))
}
