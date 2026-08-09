import {
  ApartmentOutlined,
  BugOutlined,
  CloudUploadOutlined,
  DiffOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  RedoOutlined,
  SaveOutlined,
} from '@ant-design/icons'
import { Button, Card, Empty, Modal, Select, Space, Table, Tag, Typography } from 'antd'
import { useState } from 'react'

import CreateWorkflowDialog from '../features/workflows/CreateWorkflowDialog'
import { useWorkflows } from '../features/workflows/use-workflows'
import WorkflowDesigner from '../flow/WorkflowDesigner'
import type { Workflow, WorkflowExecution, WorkflowNodeExecution } from '../lib/api'

export default function WorkflowsPage() {
  const [createOpen, setCreateOpen] = useState(false)
  const state = useWorkflows()

  async function create(input: Parameters<typeof state.addWorkflow>[0]) {
    await state.addWorkflow(input)
    setCreateOpen(false)
  }

  return (
    <>
      <WorkflowHeading state={state} onCreate={() => setCreateOpen(true)} />
      <WorkflowWorkspace state={state} />
      <LatestRunCard state={state} />
      <DebugResultCard result={state.debugResult} />
      <Card title="工作流执行历史" className="workflow-result-card">
        <ExecutionTable items={state.executions.data?.items ?? []} />
      </Card>
      <VersionDiffDialog state={state} />
      <CreateWorkflowDialog
        open={createOpen}
        submitting={state.creating}
        apis={state.apis.data?.items ?? []}
        onClose={() => setCreateOpen(false)}
        onCreate={create}
      />
    </>
  )
}

type WorkflowState = ReturnType<typeof useWorkflows>

function LatestRunCard({ state }: { state: WorkflowState }) {
  const result = state.lastResult
  const datasetChildren = result?.children ?? []
  return (
    <Card title="最近一次运行" className="workflow-result-card">
      {datasetChildren.length ? (
        <DatasetRunSummary items={datasetChildren} />
      ) : (
        <NodeTable
          nodes={result?.nodes ?? []}
          replaying={state.replaying}
          onReplay={(nodeId) => void state.replayNode(nodeId)}
        />
      )}
    </Card>
  )
}

function WorkflowHeading({ state, onCreate }: { state: WorkflowState; onCreate: () => void }) {
  return (
    <div className="page-heading">
      <div>
        <Typography.Title level={2}>流程编排</Typography.Title>
        <Typography.Text type="secondary">
          管理草稿和不可变发布版本，验证 DAG 并运行固定快照。
        </Typography.Text>
      </div>
      <Space wrap>
        <Select
          aria-label="工作流项目"
          className="context-select"
          placeholder="选择项目"
          value={state.projectId}
          loading={state.projects.isLoading}
          options={options(state.projects.data?.items)}
          onChange={state.selectProject}
        />
        <Select
          aria-label="工作流环境"
          className="context-select"
          placeholder="选择环境"
          value={state.environmentId}
          loading={state.environments.isLoading}
          disabled={!state.projectId}
          options={options(state.environments.data)}
          onChange={state.setEnvironmentSelection}
        />
        <Button
          type="primary"
          icon={<PlusOutlined />}
          disabled={!state.projectId || !state.apis.data?.items.length}
          onClick={onCreate}
        >
          新建工作流
        </Button>
      </Space>
    </div>
  )
}

function WorkflowWorkspace({ state }: { state: WorkflowState }) {
  return (
    <div className="workflow-grid">
      <Card title="工作流" loading={state.workflows.isLoading}>
        <WorkflowTable
          items={state.workflows.data?.items ?? []}
          selectedId={state.workflowId}
          onSelect={state.setWorkflowSelection}
        />
      </Card>
      <Card title="可视化草稿" extra={<DraftActions state={state} />}>
        <DraftEditor state={state} />
      </Card>
    </div>
  )
}

function DraftActions({ state }: { state: WorkflowState }) {
  return (
    <Space wrap>
      <Button
        icon={<SaveOutlined />}
        disabled={!state.selectedWorkflow || Boolean(state.activeExecutionId)}
        loading={state.saving}
        onClick={() => void state.saveDraft()}
      >
        保存草稿
      </Button>
      <Button
        icon={<CloudUploadOutlined />}
        disabled={!state.selectedWorkflow || Boolean(state.activeExecutionId)}
        loading={state.publishing}
        onClick={() => void state.publish()}
      >
        发布版本
      </Button>
      <Button
        type="primary"
        icon={<PlayCircleOutlined />}
        disabled={!canExecute(state)}
        loading={state.executing || Boolean(state.activeExecutionId)}
        onClick={() => void state.execute()}
      >
        运行
      </Button>
      <Select
        aria-label="调试断点"
        className="workflow-breakpoint-select"
        value={state.breakpointNodeId}
        disabled={!state.selectedWorkflow || Boolean(state.activeExecutionId)}
        options={state.breakpointNodes.map((node) => ({ value: node.id, label: node.name }))}
        onChange={state.setBreakpointSelection}
      />
      <Button
        icon={<BugOutlined />}
        disabled={!canExecute(state) || !state.breakpointNodeId}
        loading={state.debugging}
        onClick={() => void state.debugToBreakpoint()}
      >
        调试至断点
      </Button>
      <Button
        icon={<DiffOutlined />}
        disabled={(state.selectedWorkflow?.current_version ?? 0) < 2}
        loading={state.comparing}
        onClick={() => void state.compareLatestVersions()}
      >
        版本 Diff
      </Button>
    </Space>
  )
}

function DraftEditor({ state }: { state: WorkflowState }) {
  const workflow = state.selectedWorkflow
  if (!workflow) return <Empty description="请选择或新建工作流" />
  return (
    <>
      <Space className="workflow-meta" wrap>
        <Tag color="blue">草稿 r{workflow.draft_revision}</Tag>
        <PublishedTag version={workflow.current_version} />
      </Space>
      <WorkflowDesigner
        key={workflow.id}
        definition={state.designerDefinition}
        apis={state.apis.data?.items ?? []}
        artifacts={state.artifacts.data?.items ?? []}
        workflows={(state.workflows.data?.items ?? []).filter((item) => item.id !== workflow.id)}
        statuses={state.nodeStatuses}
        editable={!state.activeExecutionId}
        onChange={state.setDraftDefinition}
      />
    </>
  )
}

function PublishedTag({ version }: { version: number | null }) {
  return (
    <Tag color={version ? 'green' : 'default'}>{version ? `已发布 v${version}` : '未发布'}</Tag>
  )
}

function canExecute(state: WorkflowState): boolean {
  return (
    [
      state.projectId,
      state.environmentId,
      state.workflowId,
      state.selectedWorkflow?.current_version,
    ].every(Boolean) && !state.activeExecutionId
  )
}

function WorkflowTable({
  items,
  selectedId,
  onSelect,
}: {
  items: Workflow[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  return (
    <Table
      rowKey="id"
      size="small"
      pagination={false}
      dataSource={items}
      locale={{ emptyText: '暂无工作流' }}
      rowClassName={(record) => (record.id === selectedId ? 'selected-row' : '')}
      onRow={(record) => ({ onClick: () => onSelect(record.id) })}
      columns={[
        { title: '名称', dataIndex: 'name' },
        {
          title: '发布版本',
          dataIndex: 'current_version',
          width: 100,
          render: (version: number | null) => (version ? <Tag color="green">v{version}</Tag> : '-'),
        },
        {
          title: '',
          width: 40,
          render: () => <ApartmentOutlined className="table-action-icon" />,
        },
      ]}
    />
  )
}

type DisplayNode = Pick<
  WorkflowNodeExecution,
  'node_id' | 'node_type' | 'name' | 'status' | 'attempts' | 'error_message'
>

function NodeTable({
  nodes,
  replaying = false,
  onReplay,
}: {
  nodes: DisplayNode[]
  replaying?: boolean
  onReplay?: (nodeId: string) => void
}) {
  return (
    <Table
      rowKey="node_id"
      size="small"
      pagination={false}
      dataSource={nodes}
      locale={{ emptyText: '尚未运行工作流' }}
      columns={[
        { title: '节点', dataIndex: 'name' },
        { title: '类型', dataIndex: 'node_type', width: 100 },
        {
          title: '状态',
          dataIndex: 'status',
          width: 100,
          render: (status: string) => <StatusTag status={status} />,
        },
        { title: '尝试次数', dataIndex: 'attempts', width: 100 },
        { title: '错误', dataIndex: 'error_message' },
        ...(onReplay
          ? [
              {
                title: '操作',
                width: 100,
                render: (_value: unknown, node: DisplayNode) => (
                  <Button
                    type="link"
                    size="small"
                    icon={<RedoOutlined />}
                    loading={replaying}
                    onClick={() => onReplay(node.node_id)}
                  >
                    重放
                  </Button>
                ),
              },
            ]
          : []),
      ]}
    />
  )
}

function DebugResultCard({ result }: { result: WorkflowState['debugResult'] }) {
  if (!result) return null
  return (
    <Card
      title={result.mode === 'breakpoint' ? '断点调试结果' : '节点重放结果'}
      className="workflow-result-card"
      extra={<Tag color={result.status === 'passed' ? 'green' : 'red'}>{result.status}</Tag>}
    >
      <NodeTable nodes={result.nodes} />
    </Card>
  )
}

function VersionDiffDialog({ state }: { state: WorkflowState }) {
  return (
    <Modal
      title="工作流版本 Diff"
      open={Boolean(state.versionDiff)}
      footer={null}
      destroyOnHidden
      onCancel={state.closeVersionDiff}
    >
      {state.versionDiff && (
        <pre className="workflow-version-diff">
          {JSON.stringify(state.versionDiff.changes, null, 2)}
        </pre>
      )}
    </Modal>
  )
}

function DatasetRunSummary({ items }: { items: WorkflowExecution[] }) {
  if (!items.length) return null
  return (
    <div className="dataset-run-summary">
      <Typography.Title level={5}>数据集子执行</Typography.Title>
      <Table
        rowKey="id"
        size="small"
        pagination={false}
        dataSource={items}
        columns={[
          {
            title: '数据行',
            dataIndex: 'dataset_row_index',
            width: 100,
            render: (value: number) => value + 1,
          },
          {
            title: '状态',
            dataIndex: 'status',
            width: 100,
            render: (status: string) => <StatusTag status={status} />,
          },
          { title: '错误', dataIndex: 'error_message' },
        ]}
      />
    </div>
  )
}

function ExecutionTable({ items }: { items: WorkflowExecution[] }) {
  return (
    <Table
      rowKey="id"
      size="small"
      pagination={false}
      dataSource={items}
      locale={{ emptyText: '暂无执行记录' }}
      columns={[
        { title: '执行 ID', dataIndex: 'id', ellipsis: true },
        {
          title: '状态',
          dataIndex: 'status',
          width: 100,
          render: (status: string) => <StatusTag status={status} />,
        },
        {
          title: '开始时间',
          dataIndex: 'started_at',
          render: (value: string) => new Date(value).toLocaleString('zh-CN'),
        },
      ]}
    />
  )
}

function StatusTag({ status }: { status: string }) {
  const colors: Record<string, string> = {
    passed: 'success',
    failed: 'error',
    running: 'processing',
    skipped: 'default',
    cancelled: 'warning',
  }
  return <Tag color={colors[status] ?? 'default'}>{status}</Tag>
}

function options(items?: Array<{ id: string; name: string }>) {
  return items?.map((item) => ({ value: item.id, label: item.name }))
}
