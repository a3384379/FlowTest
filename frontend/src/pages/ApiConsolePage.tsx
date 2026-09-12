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
import { useSearchParams } from 'react-router-dom'
import { useState } from 'react'

import ArtifactPanel from '../features/api-console/ArtifactPanel'
import APIWorkbench from '../features/api-console/APIWorkbench'
import CreateDialogs from '../features/api-console/CreateDialogs'
import EnvironmentManager from '../features/api-console/EnvironmentManager'
import ExecutionResultPanel from '../features/api-console/ExecutionResultPanel'
import ImportDialog from '../features/api-console/ImportDialog'
import type {
  CreateApiInput,
  CreateEnvironmentInput,
  CreateProjectInput,
  HttpMethod,
} from '../features/api-console/api-service'
import { useApiConsole } from '../features/api-console/use-api-console'
import { useAuthStore } from '../features/auth/auth-store'
import type { ApiDefinition, Execution, ExecutionDetail } from '../lib/api'

type DialogState = 'project' | 'environment' | 'api' | null

export default function ApiConsolePage() {
  const [searchParams] = useSearchParams()
  const [dialog, setDialog] = useState<DialogState>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [renameTarget, setRenameTarget] = useState<ApiDefinition | null>(null)
  const [environmentManagerOpen, setEnvironmentManagerOpen] = useState(false)
  const consoleState = useApiConsole(searchParams.get('focus') ?? undefined)
  const userId = useAuthStore((state) => state.user?.id)
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
      <ApiConsoleHeading
        state={consoleState}
        canCreateAssets={canCreateAssets}
        onDialog={setDialog}
        onImport={() => setImportOpen(true)}
        onManageEnvironment={() => setEnvironmentManagerOpen(true)}
      />

      <div className="console-grid">
        <Card
          title="接口列表"
          extra={
            <Space wrap>
              <Input.Search
                aria-label="搜索接口"
                allowClear
                placeholder="搜索名称、路径或说明"
                value={consoleState.apiSearchInput}
                onChange={(event) => consoleState.setApiSearchInput(event.target.value)}
                style={{ width: 220 }}
              />
              <Select
                aria-label="接口方法筛选"
                allowClear
                placeholder="全部方法"
                value={consoleState.apiMethod ?? undefined}
                onChange={(value?: HttpMethod) => consoleState.setApiMethod(value ?? null)}
                options={httpMethods.map((method) => ({ value: method, label: method }))}
                style={{ width: 120 }}
              />
              <Button
                type="primary"
                icon={<PlusOutlined />}
                disabled={!canCreateAssets}
                onClick={() => setDialog('api')}
              >
                新建接口
              </Button>
            </Space>
          }
        >
          <ApiTable
            loading={consoleState.apis.isLoading}
            items={apis}
            selectedId={consoleState.apiId}
            onSelect={consoleState.setApiSelection}
            onRename={setRenameTarget}
            page={consoleState.apis.data?.page ?? consoleState.apiPage}
            pageSize={consoleState.apis.data?.page_size ?? 50}
            total={consoleState.apis.data?.total ?? 0}
            onPageChange={consoleState.setApiPage}
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
          redactionMode={consoleState.redactionMode}
          draftScope={apiDraftScope(userId, consoleState.projectId)}
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
      <EnvironmentManager
        open={environmentManagerOpen}
        environment={consoleState.environments.data?.find(
          (item) => item.id === consoleState.environmentId,
        )}
        saving={consoleState.updatingEnvironment}
        deleting={consoleState.deletingEnvironment}
        onClose={() => setEnvironmentManagerOpen(false)}
        onSave={async (input) => {
          await consoleState.editEnvironment(consoleState.environmentId ?? '', input)
          setEnvironmentManagerOpen(false)
        }}
        onDelete={async () => {
          await consoleState.archiveEnvironment(consoleState.environmentId ?? '')
          setEnvironmentManagerOpen(false)
        }}
      />
    </>
  )
}

function apiDraftScope(userId: string | undefined, projectId: string | null): string | undefined {
  return userId && projectId ? `${userId}:${projectId}` : undefined
}

type ConsoleState = ReturnType<typeof useApiConsole>

function ApiConsoleHeading({
  state,
  canCreateAssets,
  onDialog,
  onImport,
  onManageEnvironment,
}: {
  state: ConsoleState
  canCreateAssets: boolean
  onDialog: (dialog: DialogState) => void
  onImport: () => void
  onManageEnvironment: () => void
}) {
  return (
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
          loading={state.projects.isLoading}
          placeholder="选择项目"
          value={state.projectId}
          onChange={state.selectProject}
          options={projectOptions(state.projects.data?.items)}
        />
        <Button icon={<PlusOutlined />} onClick={() => onDialog('project')}>
          新建项目
        </Button>
        <Button icon={<ImportOutlined />} disabled={!canCreateAssets} onClick={onImport}>
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
            onClick: ({ key }) => state.exportApis(key as 'har' | 'curl' | 'bruno' | 'excel'),
          }}
        >
          <Button icon={<DownloadOutlined />} disabled={!canCreateAssets} loading={state.exporting}>
            导出
          </Button>
        </Dropdown>
        <Select
          aria-label="当前环境"
          className="context-select"
          loading={state.environments.isLoading}
          placeholder={state.environmentPlaceholder}
          status={state.environmentStatus}
          value={state.environmentId}
          onChange={state.setEnvironmentSelection}
          disabled={!canCreateAssets}
          options={projectOptions(state.environments.data)}
        />
        <Button
          icon={<PlusOutlined />}
          disabled={!canCreateAssets}
          onClick={() => onDialog('environment')}
        >
          新建环境
        </Button>
        <Button disabled={!state.environmentId} onClick={onManageEnvironment}>
          管理环境
        </Button>
      </Space>
    </div>
  )
}

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
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
}

function ApiTable({
  loading,
  items,
  selectedId,
  onSelect,
  onRename,
  page,
  pageSize,
  total,
  onPageChange,
}: ApiTableProps) {
  return (
    <Table
      rowKey="id"
      size="small"
      loading={loading}
      pagination={{
        current: page,
        pageSize,
        total,
        showSizeChanger: false,
        showTotal: (value) => `共 ${value} 个接口`,
        onChange: onPageChange,
      }}
      scroll={{ y: 440 }}
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

const httpMethods: HttpMethod[] = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']

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
