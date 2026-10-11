import {
  DownloadOutlined,
  EditOutlined,
  ImportOutlined,
  FolderOutlined,
  PlayCircleOutlined,
  PlusOutlined,
} from '@ant-design/icons'
import {
  Button,
  Card,
  Dropdown,
  Drawer,
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
import ApiFolderDirectory from '../features/api-console/ApiFolderDirectory'
import RequestTargetSummary from '../features/api-console/RequestTargetSummary'
import QueryFailureNotice from '../components/QueryFailureNotice'
import { WorkflowResourceReturn } from '../flow/WorkflowResourceNavigation'
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
import type { ApiDefinition } from '../lib/api'

type DialogState = 'project' | 'environment' | 'api' | null

export default function ApiConsolePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [dialog, setDialog] = useState<DialogState>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [renameTarget, setRenameTarget] = useState<ApiDefinition | null>(null)
  const [environmentManagerOpen, setEnvironmentManagerOpen] = useState(false)
  const [artifactsOpen, setArtifactsOpen] = useState(searchParams.get('panel') === 'files')
  const consoleState = useConsoleFromRoute(searchParams)
  const userId = useAuthStore((state) => state.user?.id)
  const currentDefinition = selectedApiDefinition(consoleState)
  const artifacts = artifactItems(consoleState)
  const apis = apiItems(consoleState)

  function selectExecution(executionId: string | null) {
    const next = new URLSearchParams(searchParams)
    if (consoleState.apiId) next.set('focus', consoleState.apiId)
    if (executionId) next.set('execution', executionId)
    else next.delete('execution')
    setSearchParams(next)
  }

  function selectApi(apiId: string) {
    const next = new URLSearchParams(searchParams)
    next.set('focus', apiId)
    next.delete('execution')
    setSearchParams(next)
  }

  async function addProject(input: CreateProjectInput) {
    await consoleState.addProject(input)
    setDialog(null)
  }

  async function addEnvironment(input: CreateEnvironmentInput) {
    await consoleState.addEnvironment(input)
    setDialog(null)
  }

  async function addApi(input: CreateApiInput) {
    const folder = consoleState.apiFolder
    await consoleState.addApi({
      ...input,
      folder_id: ['all', 'unfiled'].includes(folder) ? null : folder,
    })
    setDialog(null)
  }

  const canCreateAssets = consoleState.canEdit
  const canExecute = canExecuteCurrentApi(consoleState)

  return (
    <div className="api-console-page">
      <ApiConsoleHeading
        state={consoleState}
        canCreateAssets={canCreateAssets}
        onDialog={setDialog}
        onImport={() => setImportOpen(true)}
        onArtifacts={() => setArtifactsOpen(true)}
      />
      <QueryFailureNotice
        queries={[
          consoleState.apis,
          consoleState.apiDetail,
          consoleState.environments,
          consoleState.versions,
          consoleState.services,
          consoleState.endpoints,
        ]}
      />
      <div className="api-workspace">
        <aside className="api-workspace-directory" aria-label="接口目录与环境">
          <Card
            className="api-directory-card"
            title="接口集合"
            extra={
              <Button
                type="text"
                icon={<PlusOutlined />}
                aria-label="新建接口"
                disabled={!canCreateAssets}
                onClick={() => setDialog('api')}
              />
            }
          >
            <ApiFolderSection
              state={consoleState}
              onSelect={(folder) => {
                consoleState.setApiFolder(folder)
                const next = new URLSearchParams(searchParams)
                next.delete('focus')
                next.delete('execution')
                setSearchParams(next)
              }}
            />
            <div className="api-directory-filters">
              <Input.Search
                aria-label="搜索接口"
                allowClear
                placeholder="搜索名称、路径或说明"
                value={consoleState.apiSearchInput}
                onChange={(event) => consoleState.setApiSearchInput(event.target.value)}
              />
              <Select
                aria-label="接口方法筛选"
                allowClear
                placeholder="全部方法"
                value={consoleState.apiMethod ?? undefined}
                onChange={(value?: HttpMethod) => consoleState.setApiMethod(value ?? null)}
                options={httpMethods.map((method) => ({ value: method, label: method }))}
                style={{ width: '100%' }}
              />
            </div>
            <ApiTable
              editable={consoleState.canEdit}
              loading={consoleState.apis.isLoading}
              items={apis}
              selectedId={consoleState.apiId}
              onSelect={selectApi}
              onRename={setRenameTarget}
              page={consoleState.apis.data?.page ?? consoleState.apiPage}
              pageSize={consoleState.apis.data?.page_size ?? 50}
              total={consoleState.apis.data?.total ?? 0}
              onPageChange={consoleState.setApiPage}
            />
          </Card>
          <Card title="环境管理" className="api-environment-card">
            <Typography.Paragraph type="secondary">
              在请求区选择发送环境、Service 和地址版本。
            </Typography.Paragraph>
            <Space wrap>
              <Button
                type="text"
                disabled={!canCreateAssets}
                onClick={() => setDialog('environment')}
              >
                新建环境
              </Button>
              <Button
                type="text"
                disabled={!consoleState.environmentId}
                onClick={() => setEnvironmentManagerOpen(true)}
              >
                管理环境
              </Button>
            </Space>
          </Card>
        </aside>
        <div className="api-workspace-main">
          <APIWorkbench
            key={apiWorkbenchKey(consoleState)}
            detail={consoleState.apiDetail.data}
            editable={apiWorkbenchEditable(consoleState)}
            loading={consoleState.apiDetail.isLoading}
            saving={consoleState.savingVersion}
            previewing={consoleState.previewing}
            onSave={consoleState.saveVersion}
            onPreview={consoleState.previewRequest}
            onRename={() => setRenameTarget(currentDefinition)}
            artifacts={artifacts}
            redactionMode={consoleState.redactionMode}
            draftScope={
              consoleState.selectedVersion === null
                ? apiDraftScope(userId, consoleState.projectId)
                : undefined
            }
            versionActions={<ApiVersionSelector state={consoleState} />}
            requestActions={<RunnerActions state={consoleState} enabled={canExecute} />}
            targetActions={<ApiTargetControls state={consoleState} />}
          />
          <Card
            title="响应与验证"
            aria-label="接口响应与验证"
            className="api-response-panel"
            extra={
              <Space>
                <Typography.Text type="secondary">预期状态码</Typography.Text>
                <InputNumber
                  aria-label="预期状态码"
                  min={100}
                  max={599}
                  value={consoleState.expectedStatus}
                  onChange={(value) => consoleState.setExpectedStatus(value ?? 200)}
                />
              </Space>
            }
          >
            <RunnerContent state={consoleState} onSelectExecution={selectExecution} />
          </Card>
        </div>
      </div>
      <Drawer
        title="文件仓库"
        open={artifactsOpen}
        onClose={() => setArtifactsOpen(false)}
        size={760}
      >
        <ArtifactPanel
          disabled={!canCreateAssets}
          loading={consoleState.artifacts.isLoading}
          uploading={consoleState.uploading}
          items={artifacts}
          onUpload={consoleState.uploadFile}
          onDownload={consoleState.downloadFile}
        />
        <WorkflowResourceReturn projectId={consoleState.projectId} />
      </Drawer>
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
    </div>
  )
}

function apiDraftScope(userId: string | undefined, projectId: string | null): string | undefined {
  return userId && projectId ? `${userId}:${projectId}` : undefined
}

type ConsoleState = ReturnType<typeof useApiConsole>

function useConsoleFromRoute(params: URLSearchParams) {
  return useApiConsole(params.get('focus') ?? undefined, params.get('execution') ?? undefined)
}

function canExecuteCurrentApi(state: ConsoleState): boolean {
  return (
    state.canEdit &&
    state.selectedVersion === null &&
    Boolean(state.apiDetail.data) &&
    !state.viewingHistory &&
    allSelected([state.projectId, state.environmentId, state.apiId])
  )
}

function apiWorkbenchKey(state: ConsoleState): string {
  return `${state.projectId}:${state.apiId}:${state.selectedVersion ?? 'current'}`
}
function apiWorkbenchEditable(state: ConsoleState): boolean {
  return state.canEdit && state.selectedVersion === null
}

function ApiFolderSection({
  state,
  onSelect,
}: {
  state: ConsoleState
  onSelect: (folder: string) => void
}) {
  if (!state.projectId) return null
  return (
    <ApiFolderDirectory
      key={state.projectId}
      projectId={state.projectId}
      editable={state.canEdit}
      selected={state.apiFolder}
      definition={selectedApiDefinition(state) ?? undefined}
      onSelect={onSelect}
    />
  )
}

function ApiVersionSelector({ state }: { state: ConsoleState }) {
  return (
    <Select
      aria-label="接口版本"
      value={state.selectedVersion ?? 'current'}
      onChange={(value) => state.setSelectedVersion(value === 'current' ? null : Number(value))}
      options={[
        { value: 'current', label: '最新版本（编辑）' },
        ...(state.versions.data ?? []).map((version) => ({
          value: version.version,
          label: `v${version.version}（只读）`,
        })),
      ]}
    />
  )
}

function ApiTargetControls({ state }: { state: ConsoleState }) {
  const inheritedService =
    state.apiDetail.data?.version.service_id ??
    state.environments.data?.find((item) => item.id === state.environmentId)?.default_service_id
  const service = state.services.data?.find((item) =>
    state.serviceOverride
      ? item.service_key === state.serviceOverride
      : item.id === inheritedService,
  )
  return (
    <div className="api-target-controls">
      <Space wrap>
        <Select
          aria-label="发送环境"
          value={state.environmentId}
          placeholder={state.environmentPlaceholder}
          status={state.environmentStatus}
          onChange={state.setEnvironmentSelection}
          options={projectOptions(state.environments.data)}
        />
        <Select
          aria-label="临时 Service"
          allowClear
          placeholder="继承接口／环境 Service"
          value={state.serviceOverride}
          onChange={state.setServiceOverride}
          options={(state.services.data ?? [])
            .filter((item) => item.enabled)
            .map((item) => ({ value: item.service_key, label: item.name }))}
        />
        <Select
          aria-label="Endpoint Variant"
          allowClear
          placeholder="默认 Endpoint"
          value={state.endpointVariant}
          onChange={state.setEndpointVariant}
          options={(state.endpoints.data ?? [])
            .filter((item) => item.enabled && item.service_id === service?.id)
            .map((item) => ({ value: item.variant, label: item.variant }))}
        />
      </Space>
      <QueryFailureNotice queries={[state.targetPreview]} />
      <RequestTargetSummary compact preview={state.targetPreview.data} />
    </div>
  )
}

function ApiConsoleHeading({
  state,
  canCreateAssets,
  onDialog,
  onImport,
  onArtifacts,
}: {
  state: ConsoleState
  canCreateAssets: boolean
  onDialog: (dialog: DialogState) => void
  onImport: () => void
  onArtifacts: () => void
}) {
  return (
    <div className="page-heading">
      <div>
        <Typography.Title level={2}>接口管理</Typography.Title>
        <Typography.Text type="secondary">
          编辑请求，发送已保存版本，并查看响应与断言证据。
        </Typography.Text>
      </div>
      <Space wrap>
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
          <Button icon={<DownloadOutlined />} disabled={!state.projectId} loading={state.exporting}>
            导出
          </Button>
        </Dropdown>
        <Button icon={<FolderOutlined />} disabled={!state.projectId} onClick={onArtifacts}>
          文件仓库
        </Button>
      </Space>
    </div>
  )
}

function RunnerActions({ state, enabled }: { state: ConsoleState; enabled: boolean }) {
  return (
    <div className="api-send-action">
      <Button
        type="primary"
        icon={<PlayCircleOutlined />}
        disabled={!enabled}
        loading={state.executing}
        onClick={() => state.execute()}
        aria-label="发送请求"
        title="发送当前接口的已保存版本"
      >
        发送
      </Button>
    </div>
  )
}

function RunnerContent({
  state,
  onSelectExecution,
}: {
  state: ConsoleState
  onSelectExecution: (id: string | null) => void
}) {
  if (!state.projectId || !state.apiId) {
    return <Empty description="请选择接口查看响应与历史" className="console-empty" />
  }
  return (
    <ExecutionResultPanel
      result={state.result}
      history={state.history.data?.items ?? []}
      historyLoading={state.history.isPending}
      historyError={state.history.error}
      onRetryHistory={() => void state.history.refetch()}
      page={state.historyPage}
      total={state.history.data?.total ?? 0}
      onPageChange={state.setHistoryPage}
      onSelectExecution={onSelectExecution}
      viewingHistory={state.viewingHistory}
      detailLoading={state.viewingHistory && state.selectedExecution.isPending}
      detailError={state.selectedExecution.error}
      onRetryDetail={() => void state.selectedExecution.refetch()}
    />
  )
}

type ApiTableProps = {
  editable: boolean
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
  editable,
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
      className="api-directory-table"
      showHeader={false}
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
        {
          title: '名称',
          dataIndex: 'name',
          render: (name: string, definition: ApiDefinition) => (
            <Button
              type="text"
              className="api-directory-select"
              aria-label={`选择接口 ${name}`}
              aria-pressed={definition.id === selectedId}
              onClick={(event) => {
                event.stopPropagation()
                onSelect(definition.id)
              }}
            >
              {name}
            </Button>
          ),
        },
        {
          title: '版本',
          dataIndex: 'current_version',
          width: 50,
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
              disabled={!editable}
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

function projectOptions(items?: Array<{ id: string; name: string }>) {
  return items?.map((item) => ({ value: item.id, label: item.name }))
}
