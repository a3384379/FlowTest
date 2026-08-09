import { ApiOutlined, ImportOutlined, PlayCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { Button, Card, Empty, InputNumber, Select, Space, Table, Tag, Typography } from 'antd'
import { useState } from 'react'

import ArtifactPanel from '../features/api-console/ArtifactPanel'
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
  const consoleState = useApiConsole()

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
            items={consoleState.apis.data?.items ?? []}
            selectedId={consoleState.apiId}
            onSelect={consoleState.setApiSelection}
          />
        </Card>

        <Card
          title="请求运行器"
          extra={<RunnerActions state={consoleState} enabled={canExecute} />}
        >
          <RunnerContent
            enabled={canExecute}
            result={consoleState.result}
            history={consoleState.history.data?.items ?? []}
          />
        </Card>
      </div>

      <ArtifactPanel
        disabled={!canCreateAssets}
        loading={consoleState.artifacts.isLoading}
        uploading={consoleState.uploading}
        items={consoleState.artifacts.data?.items ?? []}
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
        artifacts={consoleState.artifacts.data?.items ?? []}
      />
      <ImportDialog
        open={importOpen}
        importing={consoleState.importing}
        result={consoleState.lastImport}
        onImport={consoleState.importDocument}
        onClose={() => {
          setImportOpen(false)
          consoleState.clearImportResult()
        }}
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
}

function ApiTable({ loading, items, selectedId, onSelect }: ApiTableProps) {
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
          render: () => <ApiOutlined className="table-action-icon" />,
        },
      ]}
    />
  )
}

function allSelected(values: Array<string | null>): boolean {
  return values.every(Boolean)
}

function projectOptions(items?: Array<{ id: string; name: string }>) {
  return items?.map((item) => ({ value: item.id, label: item.name }))
}
