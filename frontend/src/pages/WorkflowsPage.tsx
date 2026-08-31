import {
  ApartmentOutlined,
  BugOutlined,
  CloudUploadOutlined,
  DiffOutlined,
  EyeOutlined,
  LockOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  RedoOutlined,
  SaveOutlined,
} from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Empty,
  Modal,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import CreateWorkflowDialog from '../features/workflows/CreateWorkflowDialog'
import FlowSpecReviewDialog, {
  type FlowSpecReviewSeed,
} from '../features/workflows/FlowSpecReviewDialog'
import FlowProposalReviewDialog from '../features/workflows/FlowProposalReviewDialog'
import { useWorkflows } from '../features/workflows/use-workflows'
import WorkflowDesigner from '../flow/WorkflowDesigner'
import type { Workflow, WorkflowExecution, WorkflowNodeExecution } from '../lib/api'

export default function WorkflowsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const initialProposalId = searchParams.get('proposal') ?? undefined
  const [createOpen, setCreateOpen] = useState(false)
  const [flowSpecOpen, setFlowSpecOpen] = useState(false)
  const [flowSpecSeed, setFlowSpecSeed] = useState<FlowSpecReviewSeed>()
  const [flowProposalOpen, setFlowProposalOpen] = useState(false)
  const state = useWorkflows()

  async function create(input: Parameters<typeof state.addWorkflow>[0]) {
    await state.addWorkflow(input)
    setCreateOpen(false)
  }

  return (
    <>
      <WorkflowHeading
        state={state}
        onCreate={() => setCreateOpen(true)}
        onFlowSpec={() => {
          setFlowSpecSeed(undefined)
          setFlowSpecOpen(true)
        }}
        onFlowProposal={() => setFlowProposalOpen(true)}
      />
      <WorkflowWorkspace state={state} />
      <RunConsoleCard state={state} />
      <DebugResultCard result={state.debugResult} />
      <Card title="工作流执行历史" className="workflow-result-card">
        <ExecutionTable
          items={(state.executions.data?.items ?? []).filter(
            (item) => item.workflow_id === state.workflowId,
          )}
          selectedId={state.historyExecutionId}
          loading={state.historyLoading}
          onView={state.showHistory}
        />
      </Card>
      <VersionDiffDialog state={state} />
      <CreateWorkflowDialog
        open={createOpen}
        submitting={state.creating}
        apis={state.apis.data?.items ?? []}
        onClose={() => setCreateOpen(false)}
        onCreate={create}
      />
      <FlowDialogs
        state={state}
        flowSpecOpen={flowSpecOpen}
        flowSpecSeed={flowSpecSeed}
        flowProposalOpen={flowProposalOpen || Boolean(initialProposalId)}
        initialProposalId={initialProposalId}
        onFlowSpecClose={() => setFlowSpecOpen(false)}
        onFlowProposalClose={() => {
          setFlowProposalOpen(false)
          if (searchParams.has('proposal')) {
            const next = new URLSearchParams(searchParams)
            next.delete('proposal')
            setSearchParams(next, { replace: true })
          }
        }}
        onOpenRawMapping={(seed) => {
          setFlowProposalOpen(false)
          setFlowSpecSeed(seed)
          setFlowSpecOpen(true)
        }}
      />
    </>
  )
}

type WorkflowState = ReturnType<typeof useWorkflows>

function FlowDialogs({
  state,
  flowSpecOpen,
  flowSpecSeed,
  flowProposalOpen,
  initialProposalId,
  onFlowSpecClose,
  onFlowProposalClose,
  onOpenRawMapping,
}: FlowDialogsProps) {
  return (
    <>
      <WorkflowFlowSpecDialog
        state={state}
        open={flowSpecOpen}
        seed={flowSpecSeed}
        onClose={onFlowSpecClose}
      />
      <WorkflowProposalDialog
        state={state}
        open={flowProposalOpen}
        initialProposalId={initialProposalId}
        onClose={onFlowProposalClose}
        onOpenRawMapping={onOpenRawMapping}
      />
    </>
  )
}

type FlowDialogsProps = {
  state: WorkflowState
  flowSpecOpen: boolean
  flowSpecSeed: FlowSpecReviewSeed | undefined
  flowProposalOpen: boolean
  initialProposalId: string | undefined
  onFlowSpecClose: () => void
  onFlowProposalClose: () => void
  onOpenRawMapping: (seed: FlowSpecReviewSeed) => void
}

function WorkflowFlowSpecDialog({
  state,
  open,
  seed,
  onClose,
}: {
  state: WorkflowState
  open: boolean
  seed: FlowSpecReviewSeed | undefined
  onClose: () => void
}) {
  if (!state.projectId) return null
  const workflowId = flowSpecTargetWorkflowId(seed, state.workflowId)
  if (!workflowId && !seed) return null
  return (
    <FlowSpecReviewDialog
      key={flowSpecDialogKey(seed, workflowId)}
      open={open}
      projectId={state.projectId}
      workflowId={workflowId}
      apis={pageItems(state.apis.data)}
      initial={seed}
      onClose={onClose}
    />
  )
}

function flowSpecTargetWorkflowId(
  seed: FlowSpecReviewSeed | undefined,
  selectedWorkflowId: string | null,
): string | undefined {
  if (seed) return seed.targetWorkflowId ?? undefined
  return selectedWorkflowId ?? undefined
}

function flowSpecDialogKey(
  seed: FlowSpecReviewSeed | undefined,
  workflowId: string | undefined,
): string | undefined {
  return seed ? seed.proposalId : workflowId
}

function WorkflowProposalDialog({
  state,
  open,
  initialProposalId,
  onClose,
  onOpenRawMapping,
}: {
  state: WorkflowState
  open: boolean
  initialProposalId: string | undefined
  onClose: () => void
  onOpenRawMapping: (seed: FlowSpecReviewSeed) => void
}) {
  if (!state.projectId) return null
  return (
    <FlowProposalReviewDialog
      key={initialProposalId ?? 'manually-opened-proposal'}
      open={open}
      projectId={state.projectId}
      initialProposalId={initialProposalId}
      resources={workflowDesignerResources(state, state.workflowId ?? '')}
      onClose={onClose}
      onApplied={(workflowId) => {
        state.setWorkflowSelection(workflowId)
        state.showDraft()
        onClose()
      }}
      onOpenRawMapping={(proposal) => {
        onOpenRawMapping({
          proposalId: proposal.proposal.id,
          targetWorkflowId: proposal.proposal.target_workflow_id,
          spec: proposal.proposal.spec,
          serviceMappings: proposal.service_mappings,
          operationMappings: proposal.operation_mappings,
          operationVersionMappings: proposal.operation_version_mappings,
        })
      }}
    />
  )
}

function RunConsoleCard({ state }: { state: WorkflowState }) {
  return (
    <Card
      title="最近一次运行"
      className="workflow-result-card"
      extra={
        state.runtimeExecution && (
          <Space wrap>
            <StatusTag status={state.runtimeExecution.status} />
            <Typography.Text type="secondary">
              {state.runtimeExecution.id} · {executionDuration(state.runtimeExecution)}
            </Typography.Text>
          </Space>
        )
      }
    >
      {state.runtimeChildren.length ? (
        <DatasetRunSummary items={state.runtimeChildren} />
      ) : (
        <NodeTable
          nodes={state.runtimeNodes}
          replaying={state.replaying}
          onReplay={
            state.workspaceMode === 'run' && state.lastResult
              ? (nodeId) => void state.replayNode(nodeId)
              : undefined
          }
        />
      )}
    </Card>
  )
}

function WorkflowHeading({
  state,
  onCreate,
  onFlowSpec,
  onFlowProposal,
}: {
  state: WorkflowState
  onCreate: () => void
  onFlowSpec: () => void
  onFlowProposal: () => void
}) {
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
        <Button disabled={!state.workflowId} onClick={onFlowSpec}>
          FlowSpec 导入 / 映射
        </Button>
        <Button disabled={!state.projectId} onClick={onFlowProposal}>
          MCP 流程提案
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
      <Card
        title={workspaceTitle(state)}
        loading={state.workspaceMode === 'history' && state.historyLoading}
        extra={
          <Space wrap>
            <WorkspaceModeSwitch state={state} />
            {state.workspaceMode !== 'history' &&
              (state.workspaceMode === 'draft' ||
                Boolean(state.activeExecutionId) ||
                Boolean(state.lastResult)) && <DraftActions state={state} />}
          </Space>
        }
      >
        <DraftEditor state={state} />
      </Card>
    </div>
  )
}

function WorkspaceModeSwitch({ state }: { state: WorkflowState }) {
  return (
    <Segmented
      aria-label="工作流视图模式"
      value={state.workspaceMode}
      options={[
        { label: '编排', value: 'draft' },
        {
          label: '运行视图',
          value: 'run',
          disabled: !state.lastResult && !state.activeExecutionId,
        },
        {
          label: '历史快照',
          value: 'history',
          disabled: !state.historyExecutionId,
        },
      ]}
      onChange={(value) => {
        if (value === 'draft') state.showDraft()
        if (value === 'run') state.showLatestRun()
        if (value === 'history' && state.historyExecutionId) {
          state.showHistory(state.historyExecutionId)
        }
      }}
    />
  )
}

function workspaceTitle(state: WorkflowState) {
  if (state.workspaceMode === 'history') {
    return (
      <Space>
        历史执行快照
        <Tag icon={<LockOutlined />} color="gold">
          不可修改
        </Tag>
      </Space>
    )
  }
  return state.workspaceMode === 'run' ? '实时运行视图' : '可视化草稿'
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
  const resources = workflowDesignerResources(state, workflow.id)
  return (
    <>
      {state.workspaceMode === 'history' && (
        <Alert
          showIcon
          type="warning"
          title="正在查看历史执行快照"
          description="画布、节点配置、接口版本和运行结果均来自当次执行，不会随当前草稿变化。"
          className="workflow-snapshot-alert"
        />
      )}
      {state.workspaceMode === 'run' && state.activeExecutionId && (
        <Alert
          showIcon
          type="info"
          title="工作流正在运行"
          description="节点状态和结果会实时更新，点击画布节点查看请求与响应。"
          className="workflow-snapshot-alert"
        />
      )}
      <Space className="workflow-meta" wrap>
        <Tag color="blue">草稿 r{workflow.draft_revision}</Tag>
        <PublishedTag version={workflow.current_version} />
        {state.runtimeExecution && state.workspaceMode !== 'draft' && (
          <Tag>执行 {state.runtimeExecution.id.slice(0, 8)}</Tag>
        )}
      </Space>
      <WorkflowDesigner
        key={`${workflow.id}:${state.workspaceMode}:${state.historyExecutionId ?? ''}`}
        projectId={state.projectId}
        environmentId={state.environmentId}
        definition={state.designerDefinition}
        apis={resources.apis}
        artifacts={resources.artifacts}
        workflows={resources.workflows}
        credentials={resources.credentials}
        graphqlSchemas={resources.graphqlSchemas}
        grpcDescriptors={resources.grpcDescriptors}
        eventSources={resources.eventSources}
        statuses={state.nodeStatuses}
        editable={state.workspaceMode === 'draft' && !state.activeExecutionId}
        runtimeMode={state.workspaceMode === 'draft' ? undefined : state.workspaceMode}
        runtimeNodes={state.runtimeNodes}
        runtimeContext={state.runtimeContext}
        onChange={state.setDraftDefinition}
      />
    </>
  )
}

function workflowDesignerResources(state: WorkflowState, workflowId: string) {
  const workflows = pageItems(state.workflows.data)
  return {
    environments: state.environments.data ?? [],
    apis: pageItems(state.apis.data),
    artifacts: pageItems(state.artifacts.data),
    workflows: workflows.filter((item) => item.id !== workflowId),
    credentials: listItems(state.credentials.data),
    graphqlSchemas: pageItems(state.graphqlSchemas.data),
    grpcDescriptors: pageItems(state.grpcDescriptors.data),
    eventSources: pageItems(state.eventSources.data),
  }
}

function pageItems<T>(page: { items: T[] } | undefined): T[] {
  if (page) return page.items
  return []
}

function listItems<T>(items: T[] | undefined): T[] {
  if (items) return items
  return []
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
  'node_id' | 'node_type' | 'name' | 'phase' | 'status' | 'attempts' | 'error_message'
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
        {
          title: '阶段',
          dataIndex: 'phase',
          width: 90,
          render: (phase: WorkflowNodeExecution['phase']) =>
            phase === 'cleanup' ? <Tag color="purple">Cleanup</Tag> : <Tag>Main</Tag>,
        },
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
                    重放节点
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

function ExecutionTable({
  items,
  selectedId,
  loading,
  onView,
}: {
  items: WorkflowExecution[]
  selectedId: string | null
  loading: boolean
  onView: (executionId: string) => void
}) {
  return (
    <Table
      rowKey="id"
      size="small"
      pagination={false}
      dataSource={items}
      loading={loading}
      locale={{ emptyText: '暂无执行记录' }}
      rowClassName={(record) => (record.id === selectedId ? 'selected-row' : '')}
      columns={[
        { title: '执行 ID', dataIndex: 'id', ellipsis: true },
        {
          title: '版本',
          width: 80,
          render: (_value: unknown, item: WorkflowExecution) => `v${executionVersion(item)}`,
        },
        {
          title: '状态',
          dataIndex: 'status',
          width: 100,
          render: (status: string) => <StatusTag status={status} />,
        },
        {
          title: 'Main',
          width: 90,
          render: (_value: unknown, item: WorkflowExecution) =>
            item.main_status ? <StatusTag status={item.main_status} /> : '—',
        },
        {
          title: 'Cleanup',
          width: 100,
          render: (_value: unknown, item: WorkflowExecution) =>
            item.cleanup_status ? <StatusTag status={item.cleanup_status} /> : '—',
        },
        {
          title: '开始时间',
          dataIndex: 'started_at',
          render: (value: string) => new Date(value).toLocaleString('zh-CN'),
        },
        {
          title: '耗时',
          width: 110,
          render: (_value: unknown, item: WorkflowExecution) => executionDuration(item),
        },
        {
          title: '操作',
          width: 120,
          render: (_value: unknown, item: WorkflowExecution) => (
            <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => onView(item.id)}>
              查看快照
            </Button>
          ),
        },
      ]}
    />
  )
}

function executionVersion(execution: WorkflowExecution): number | string {
  const workflow = execution.snapshot.workflow
  if (isRecord(workflow) && typeof workflow.version === 'number') return workflow.version
  return '—'
}

function executionDuration(execution: WorkflowExecution): string {
  if (!execution.completed_at) return '运行中'
  const duration =
    new Date(execution.completed_at).getTime() - new Date(execution.started_at).getTime()
  if (duration < 1000) return `${duration} ms`
  return `${Math.round(duration / 10) / 100} s`
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function StatusTag({ status }: { status: string }) {
  const colors: Record<string, string> = {
    passed: 'success',
    failed: 'error',
    queued: 'default',
    running: 'processing',
    skipped: 'default',
    cancelled: 'warning',
  }
  return <Tag color={colors[status] ?? 'default'}>{status}</Tag>
}

function options(items?: Array<{ id: string; name: string }>) {
  return items?.map((item) => ({ value: item.id, label: item.name }))
}
