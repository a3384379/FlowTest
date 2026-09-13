import WorkflowWorkspaceShell from '../flow/WorkflowWorkspaceShell'
import WorkflowWorkbenchHeader from '../flow/WorkflowWorkbenchHeader'
import WorkflowRuntimeDock from '../flow/WorkflowRuntimeDock'
import { workflowLayoutKey } from '../flow/editor/layout-preferences'
import {
  BugOutlined,
  CloudUploadOutlined,
  DeleteOutlined,
  DiffOutlined,
  EyeOutlined,
  HistoryOutlined,
  ImportOutlined,
  LockOutlined,
  MoreOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  RedoOutlined,
  RobotOutlined,
  SaveOutlined,
} from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  Modal,
  Popconfirm,
  Popover,
  Segmented,
  Select,
  Space,
  Dropdown,
  Tabs,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'

import CreateWorkflowDialog from '../features/workflows/CreateWorkflowDialog'
import FailureRepairDialog from '../features/workflows/FailureRepairDialog'
import FlowSpecReviewDialog, {
  type FlowSpecReviewSeed,
} from '../features/workflows/FlowSpecReviewDialog'
import FlowProposalReviewDialog from '../features/workflows/FlowProposalReviewDialog'
import { useWorkflows } from '../features/workflows/use-workflows'
import { useWorkflowTabs } from '../features/workflows/use-workflow-tabs'
import { useAuthStore } from '../features/auth/auth-store'
import WorkflowDesigner from '../flow/WorkflowDesigner'
import type { Workflow, WorkflowExecution, WorkflowNodeExecution } from '../lib/api'

export default function WorkflowsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const initialProposalId = searchParams.get('proposal') ?? undefined
  const [createOpen, setCreateOpen] = useState(false)
  const [flowSpecOpen, setFlowSpecOpen] = useState(false)
  const [flowSpecSeed, setFlowSpecSeed] = useState<FlowSpecReviewSeed>()
  const [flowProposalOpen, setFlowProposalOpen] = useState(false)
  const [repairExecution, setRepairExecution] = useState<WorkflowExecution>()
  const initialWorkflowId = searchParams.get('focus') ?? undefined
  const state = useWorkflows(initialWorkflowId)
  const userId = useAuthStore((store) => store.user?.id)
  const tabs = useWorkflowTabs({
    userId,
    projectId: state.projectId,
    workflowIds: state.workflows.data?.items.map((item) => item.id) ?? [],
    activeWorkflowId: state.workflowId,
    hasExplicitFocus: Boolean(initialWorkflowId),
    selectWorkflow: state.setWorkflowSelection,
    saveWorkflowDraft: state.saveWorkflowDraft,
    discardWorkflowDraft: state.discardWorkflowDraft,
    memoryDraftIds: state.memoryDraftIds,
    searchParams,
    setSearchParams,
  })

  async function create(input: Parameters<typeof state.addWorkflow>[0]) {
    await state.addWorkflow(input)
    setCreateOpen(false)
  }

  return (
    <div className="workflow-workspace-page" data-testid="workflow-page">
      <WorkflowTabs
        state={state}
        workflowIds={tabs.workflowIds}
        dirtyIds={tabs.dirtyIds}
        storageError={tabs.storageError}
        onActivate={tabs.activateWorkflow}
        onClose={tabs.requestCloseTabs}
        onCloseOthers={() =>
          tabs.requestCloseTabs(tabs.workflowIds.filter((id) => id !== state.workflowId))
        }
        onCloseAll={() => tabs.requestCloseTabs(tabs.workflowIds)}
      />
      <WorkflowWorkspace
        state={state}
        onSelectWorkflow={tabs.activateWorkflow}
        onCreate={() => setCreateOpen(true)}
        onFlowSpec={() => {
          setFlowSpecSeed(undefined)
          setFlowSpecOpen(true)
        }}
        onFlowProposal={() => setFlowProposalOpen(true)}
        onRepair={setRepairExecution}
      />
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
          const next = new URLSearchParams(searchParams)
          next.delete('proposal')
          setSearchParams(next, { replace: true })
        }}
        onOpenRawMapping={(seed) => {
          setFlowProposalOpen(false)
          setFlowSpecSeed(seed)
          setFlowSpecOpen(true)
        }}
      />
      <RepairDialog
        projectId={state.projectId}
        execution={repairExecution}
        searchParams={searchParams}
        setSearchParams={setSearchParams}
        onClose={() => setRepairExecution(undefined)}
      />
      <WorkflowTabCloseModal tabs={tabs} />
    </div>
  )
}

type WorkflowState = ReturnType<typeof useWorkflows>

type WorkflowTabsState = ReturnType<typeof useWorkflowTabs>
type RuntimeDockMode = 'run' | 'history' | 'debug'

function WorkflowExecutionPanels({
  state,
  onRepair,
  forceOpen = false,
}: {
  state: WorkflowState
  onRepair: (execution: WorkflowExecution) => void
  forceOpen?: boolean
}) {
  if (!forceOpen && !showExecutionPanels(state)) return null
  const mode = executionDockMode(state)
  const preferredTab = preferredExecutionTab(state, mode, forceOpen)
  const items = executionDockItems(state, onRepair)
  return (
    <WorkflowRuntimeDock
      mode={mode}
      status={state.runtimeExecution && <StatusTag status={state.runtimeExecution.status} />}
    >
      <WorkflowRuntimeTabs key={preferredTab} initialKey={preferredTab} items={items} />
    </WorkflowRuntimeDock>
  )
}

function executionDockMode(state: WorkflowState): RuntimeDockMode {
  if (state.workspaceMode === 'draft') return state.debugResult ? 'debug' : 'run'
  if (state.workspaceMode === 'history') return 'history'
  return 'run'
}

function preferredExecutionTab(
  state: WorkflowState,
  mode: RuntimeDockMode,
  forceOpen: boolean,
): string {
  if (mode === 'history') return 'history'
  if (state.debugResult || mode === 'debug') return 'debug'
  if (forceOpen && state.workspaceMode === 'draft') return 'history'
  return 'run'
}

function executionDockItems(
  state: WorkflowState,
  onRepair: (execution: WorkflowExecution) => void,
): Array<{ key: string; label: string; children: ReactNode }> {
  return [
    {
      key: 'run',
      label: state.workspaceMode === 'history' ? '执行详情' : '最近运行',
      children: <RunConsolePanel state={state} />,
    },
    ...(state.debugResult
      ? [
          {
            key: 'debug',
            label: '调试结果',
            children: <DebugResultPanel result={state.debugResult} />,
          },
        ]
      : []),
    {
      key: 'history',
      label: '执行历史',
      children: (
        <div className="workflow-runtime-panel">
          <ExecutionTable
            items={(state.executions.data?.items ?? []).filter(
              (item) => item.workflow_id === state.workflowId,
            )}
            selectedId={state.historyExecutionId}
            loading={state.historyLoading}
            onView={state.showHistory}
            onRepair={onRepair}
          />
        </div>
      ),
    },
  ]
}

function WorkflowRuntimeTabs({
  initialKey,
  items,
}: {
  initialKey: string
  items: Array<{ key: string; label: string; children: ReactNode }>
}) {
  const [activeKey, setActiveKey] = useState(initialKey)
  const activeItem = items.find((item) => item.key === activeKey) ?? items[0]
  return (
    <div className="workflow-runtime-tabs">
      <div className="workflow-runtime-tab-list" role="tablist" aria-label="运行面板视图">
        {items.map((item) => (
          <Button
            key={item.key}
            type="text"
            role="tab"
            data-testid={`workflow-runtime-tab-${item.key}`}
            aria-selected={item.key === activeItem?.key}
            className={item.key === activeItem?.key ? 'is-active' : ''}
            onClick={() => setActiveKey(item.key)}
          >
            {item.label}
          </Button>
        ))}
      </div>
      <div className="workflow-runtime-tab-panel" role="tabpanel">
        {activeItem?.children}
      </div>
    </div>
  )
}

function WorkflowTabCloseModal({ tabs }: { tabs: WorkflowTabsState }) {
  const dirtyCount = tabs.pendingClose?.dirtyIds.length ?? 0
  return (
    <Modal
      open={Boolean(tabs.pendingClose)}
      title="关闭未保存页签"
      onCancel={tabs.cancelPendingClose}
      closable={!tabs.closingTabs}
      maskClosable={!tabs.closingTabs}
      footer={
        <Space>
          <Button disabled={tabs.closingTabs} onClick={tabs.cancelPendingClose}>
            取消
          </Button>
          <Button
            danger
            loading={tabs.closingTabs}
            onClick={() => void tabs.resolvePendingClose('discard')}
          >
            丢弃并关闭
          </Button>
          <Button
            type="primary"
            loading={tabs.closingTabs}
            onClick={() => void tabs.resolvePendingClose('save')}
          >
            保存并关闭
          </Button>
        </Space>
      }
    >
      {dirtyCount === 1 ? '当前页签有未保存修改。' : `${dirtyCount} 个页签有未保存修改。`}
    </Modal>
  )
}

function RepairDialog({
  projectId,
  execution,
  searchParams,
  setSearchParams,
  onClose,
}: {
  projectId: string | null
  execution: WorkflowExecution | undefined
  searchParams: URLSearchParams
  setSearchParams: (params: URLSearchParams, options?: { replace?: boolean }) => void
  onClose: () => void
}) {
  if (!projectId || !execution) return null
  return (
    <FailureRepairDialog
      key={execution.id}
      open
      projectId={projectId}
      execution={execution}
      onClose={onClose}
      onCreated={(proposalId) => {
        onClose()
        const next = new URLSearchParams(searchParams)
        next.set('proposal', proposalId)
        setSearchParams(next, { replace: true })
      }}
    />
  )
}

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

function RunConsolePanel({ state }: { state: WorkflowState }) {
  return (
    <div className="workflow-runtime-panel">
      <div className="workflow-runtime-panel-heading">
        <Typography.Text strong>
          {state.workspaceMode === 'history' ? '历史执行详情' : '最近一次运行'}
        </Typography.Text>
        {state.runtimeExecution && (
          <Space wrap>
            <StatusTag status={state.runtimeExecution.status} />
            <Typography.Text type="secondary">
              {state.runtimeExecution.id} · {executionDuration(state.runtimeExecution)}
            </Typography.Text>
          </Space>
        )}
      </div>
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
    </div>
  )
}

function WorkbenchMore({
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
  const disabled = !state.canEdit || !state.selectedWorkflow || Boolean(state.activeExecutionId)
  return (
    <Popover
      title="工作流与版本"
      trigger="click"
      content={
        <Space className="workflow-more-content" orientation="vertical" align="start">
          <Typography.Text type="secondary">项目与环境</Typography.Text>
          <Select
            aria-label="工作流项目"
            placeholder="选择项目"
            value={state.projectId}
            loading={state.projects.isLoading}
            options={options(state.projects.data?.items)}
            onChange={state.selectProject}
          />
          <Select
            aria-label="工作流环境"
            placeholder={state.environmentPlaceholder}
            status={state.environmentStatus}
            value={state.environmentId}
            loading={state.environments.isLoading}
            disabled={!state.projectId}
            options={options(state.environments.data)}
            onChange={state.setEnvironmentSelection}
          />
          <Button
            icon={<PlusOutlined />}
            disabled={!state.projectId || !state.apis.data?.items.length}
            onClick={onCreate}
          >
            新建工作流
          </Button>
          <Button
            icon={<CloudUploadOutlined />}
            disabled={disabled}
            loading={state.publishing}
            onClick={() => void state.publish()}
          >
            发布服务器草稿
          </Button>
          <Select
            aria-label="调试断点"
            className="workflow-breakpoint-select"
            value={state.breakpointNodeId}
            disabled={disabled}
            placeholder="选择调试断点"
            options={state.breakpointNodes.map((node) => ({ value: node.id, label: node.name }))}
            onChange={state.setBreakpointSelection}
          />
          <Button
            icon={<DiffOutlined />}
            disabled={(state.selectedWorkflow?.current_version ?? 0) < 2}
            loading={state.comparing}
            onClick={() => void state.compareLatestVersions()}
          >
            版本 Diff
          </Button>
          <Button icon={<ImportOutlined />} disabled={!state.workflowId} onClick={onFlowSpec}>
            FlowSpec 导入 / 映射
          </Button>
          <Button icon={<RobotOutlined />} disabled={!state.projectId} onClick={onFlowProposal}>
            MCP 流程提案
          </Button>
        </Space>
      }
    >
      <Button icon={<MoreOutlined />} aria-label="工作流更多操作">
        更多
      </Button>
    </Popover>
  )
}

function HeaderPrimaryActions({ state }: { state: WorkflowState }) {
  const disabled = !state.canEdit || !state.selectedWorkflow || Boolean(state.activeExecutionId)
  const canDebug = canExecute(state) && Boolean(state.breakpointNodeId)
  return (
    <Space className="workflow-header-primary-actions">
      <Button
        icon={<SaveOutlined />}
        aria-label="保存草稿"
        disabled={disabled}
        loading={state.saving}
        onClick={() => void state.saveDraft()}
      >
        保存
      </Button>
      <Button
        type="primary"
        icon={<PlayCircleOutlined />}
        aria-label="运行已发布版本"
        disabled={!canExecute(state)}
        loading={state.executing || Boolean(state.activeExecutionId)}
        onClick={() => void state.execute()}
      >
        运行
      </Button>
      {state.breakpointNodeId && (
        <Button
          icon={<BugOutlined />}
          aria-label="调试至断点"
          disabled={!canDebug}
          loading={state.debugging}
          onClick={() => void state.debugToBreakpoint()}
        >
          调试
        </Button>
      )}
    </Space>
  )
}

function WorkflowListTitle({ onCreate, disabled }: { onCreate: () => void; disabled: boolean }) {
  return (
    <div className="workflow-list-title">
      <span>工作流</span>
      <Button
        type="text"
        icon={<PlusOutlined />}
        aria-label="新建工作流"
        disabled={disabled}
        onClick={onCreate}
      />
    </div>
  )
}

function WorkflowTabs({
  state,
  workflowIds,
  dirtyIds,
  storageError,
  onActivate,
  onClose,
  onCloseOthers,
  onCloseAll,
}: {
  state: WorkflowState
  workflowIds: string[]
  dirtyIds: string[]
  storageError: string | null
  onActivate: (workflowId: string) => void
  onClose: (workflowIds: string[]) => void
  onCloseOthers: () => void
  onCloseAll: () => void
}) {
  const workflows = state.workflows.data?.items ?? []
  const byId = new Map(workflows.map((workflow) => [workflow.id, workflow]))
  const items = workflowIds.flatMap((id) => {
    const workflow = byId.get(id)
    if (!workflow) return []
    const dirty = dirtyIds.includes(workflow.id)
    return [
      {
        key: workflow.id,
        label: (
          <span>
            {workflow.name}
            {dirty && <Typography.Text type="warning"> ·</Typography.Text>}
          </span>
        ),
        closable: true,
      },
    ]
  })
  if (items.length < 2) {
    return storageError ? (
      <Alert
        showIcon
        type="warning"
        title="工作区页签保存失败"
        description={storageError}
        className="workflow-tabs-alert"
      />
    ) : null
  }
  return (
    <div className="workflow-tabs">
      <Space align="center" wrap>
        <Tabs
          type="editable-card"
          hideAdd
          activeKey={state.workflowId ?? undefined}
          items={items}
          onChange={onActivate}
          onEdit={(targetKey, action) => {
            if (action === 'remove' && typeof targetKey === 'string') onClose([targetKey])
          }}
        />
        <Dropdown
          menu={{
            items: [
              { key: 'others', label: '关闭其他页签', disabled: items.length < 2 },
              { key: 'all', label: '关闭全部页签' },
            ],
            onClick: ({ key }) => {
              if (key === 'others') onCloseOthers()
              if (key === 'all') onCloseAll()
            },
          }}
          trigger={['click']}
        >
          <Button type="text" icon={<MoreOutlined />} aria-label="页签操作" />
        </Dropdown>
      </Space>
      {storageError && (
        <Alert
          showIcon
          type="warning"
          title="工作区页签保存失败"
          description={storageError}
          className="workflow-tabs-alert"
        />
      )}
    </div>
  )
}

function WorkflowWorkspace({
  state,
  onSelectWorkflow,
  onCreate,
  onFlowSpec,
  onFlowProposal,
  onRepair,
}: {
  state: WorkflowState
  onSelectWorkflow: (workflowId: string) => void
  onCreate: () => void
  onFlowSpec: () => void
  onFlowProposal: () => void
  onRepair: (execution: WorkflowExecution) => void
}) {
  const userId = useAuthStore((store) => store.user?.id)
  const [historyDockOpen, setHistoryDockOpen] = useState(false)
  return (
    <WorkflowWorkspaceShell
      key={workflowLayoutKey(userId, state.projectId)}
      preferenceKey={workflowLayoutKey(userId, state.projectId)}
      header={
        <WorkflowWorkbenchHeader
          left={workspaceTitle(state)}
          center={<WorkspaceModeSwitch state={state} />}
          right={
            <Space>
              {state.workspaceMode !== 'history' && <HeaderPrimaryActions state={state} />}
              {state.workspaceMode === 'draft' && !state.debugResult && (
                <Button
                  icon={<HistoryOutlined />}
                  aria-label={historyDockOpen ? '关闭执行历史' : '打开执行历史'}
                  onClick={() => setHistoryDockOpen((open) => !open)}
                >
                  执行历史
                </Button>
              )}
              <WorkbenchMore
                state={state}
                onCreate={onCreate}
                onFlowSpec={onFlowSpec}
                onFlowProposal={onFlowProposal}
              />
            </Space>
          }
        />
      }
      list={
        <Card
          className="workflow-list-card"
          title={
            <WorkflowListTitle
              onCreate={onCreate}
              disabled={!state.projectId || !state.apis.data?.items.length}
            />
          }
          loading={state.workflows.isLoading}
        >
          <WorkflowTable
            items={state.workflows.data?.items ?? []}
            selectedId={state.workflowId}
            onSelect={onSelectWorkflow}
            deleting={state.deleting}
            onDelete={(id) => void state.deleteWorkflow(id)}
          />
        </Card>
      }
      runtimeDock={
        <WorkflowExecutionPanels state={state} onRepair={onRepair} forceOpen={historyDockOpen} />
      }
    >
      <Card
        className="workflow-workbench-card"
        loading={state.workspaceMode === 'history' && state.historyLoading}
      >
        <DraftEditor state={state} />
      </Card>
    </WorkflowWorkspaceShell>
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
  const workflow = state.selectedWorkflow
  if (state.workspaceMode === 'history') {
    return (
      <div className="workflow-workspace-title">
        <span className="workflow-workspace-name">{workflow?.name ?? '历史执行快照'}</span>
        <Space size={4} wrap>
          <Tag icon={<LockOutlined />} color="gold">
            历史快照 · 不可修改
          </Tag>
        </Space>
      </div>
    )
  }
  return (
    <div className="workflow-workspace-title">
      <span className="workflow-workspace-name">{workflow?.name ?? '流程工作区'}</span>
      {workflow && <DraftMetadata state={state} workflow={workflow} />}
    </div>
  )
}

function FocusDraftActions({ state }: { state: WorkflowState }) {
  const disabled = !state.canEdit || !state.selectedWorkflow || Boolean(state.activeExecutionId)
  return (
    <Space className="workflow-focus-commands">
      <Button
        icon={<SaveOutlined />}
        aria-label="保存草稿"
        disabled={disabled}
        loading={state.saving}
        onClick={() => void state.saveDraft()}
      >
        保存草稿
      </Button>
      <Button
        type="primary"
        icon={<PlayCircleOutlined />}
        aria-label="运行已发布版本"
        disabled={!canExecute(state)}
        loading={state.executing || Boolean(state.activeExecutionId)}
        onClick={() => void state.execute()}
      >
        运行已发布版本
      </Button>
      <Button
        icon={<BugOutlined />}
        aria-label="调试至断点"
        disabled={!canExecute(state) || !state.breakpointNodeId}
        loading={state.debugging}
        onClick={() => void state.debugToBreakpoint()}
      >
        调试至断点
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
      <DraftAlerts state={state} />
      <WorkflowDesigner
        key={`${workflow.id}:${state.workspaceMode}:${state.historyExecutionId ?? ''}`}
        surface="workspace"
        workflowId={workflow.id}
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
        editable={state.canEdit && state.workspaceMode === 'draft' && !state.activeExecutionId}
        runtimeMode={state.workspaceMode === 'draft' ? undefined : state.workspaceMode}
        runtimeNodes={state.runtimeNodes}
        runtimeContext={state.runtimeContext}
        focusActions={<FocusDraftActions state={state} />}
        onChange={state.setDraftDefinition}
      />
    </>
  )
}

function DraftAlerts({ state }: { state: WorkflowState }) {
  const historyAlert = state.workspaceMode === 'history'
  const runningAlert = state.workspaceMode === 'run' && Boolean(state.activeExecutionId)
  return (
    <>
      {historyAlert && (
        <Alert
          showIcon
          type="warning"
          title="正在查看历史执行快照"
          description="画布、节点配置、接口版本和运行结果均来自当次执行，不会随当前草稿变化。"
          className="workflow-snapshot-alert"
        />
      )}
      {runningAlert && (
        <Alert
          showIcon
          type="info"
          title="工作流正在运行"
          description="节点状态和结果会实时更新，点击画布节点查看请求与响应。"
          className="workflow-snapshot-alert"
        />
      )}
      {state.draftStorageError && (
        <Alert
          showIcon
          type="warning"
          title="本地保存失败"
          description={state.draftStorageError}
          className="workflow-snapshot-alert"
        />
      )}
    </>
  )
}

function DraftMetadata({ state, workflow }: { state: WorkflowState; workflow: Workflow }) {
  return (
    <Space className="workflow-meta" wrap>
      <Tag color="blue">草稿 r{workflow.draft_revision}</Tag>
      <PublishedTag version={workflow.current_version} />
      {state.draftRestored && <Tag color="orange">本地草稿已恢复</Tag>}
      {state.runtimeExecution && state.workspaceMode !== 'draft' && (
        <Tag>执行 {state.runtimeExecution.id.slice(0, 8)}</Tag>
      )}
    </Space>
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
    ].every(Boolean) &&
    state.canEdit &&
    !state.activeExecutionId
  )
}

function WorkflowTable({
  items,
  selectedId,
  onSelect,
  deleting,
  onDelete,
}: {
  items: Workflow[]
  selectedId: string | null
  onSelect: (id: string) => void
  deleting: boolean
  onDelete: (id: string) => void
}) {
  const [query, setQuery] = useState('')
  const visible = items.filter((item) => item.name.toLowerCase().includes(query.toLowerCase()))
  return (
    <div className="workflow-compact-list">
      <Input.Search
        aria-label="搜索工作流"
        placeholder="搜索工作流"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      {visible.length === 0 && <Empty description="暂无工作流" />}
      {visible.map((record) => (
        <div
          key={record.id}
          className={
            record.id === selectedId ? 'workflow-list-item selected-row' : 'workflow-list-item'
          }
        >
          <Button
            type="text"
            className="workflow-list-select"
            onClick={() => onSelect(record.id)}
            title={record.name}
            aria-pressed={record.id === selectedId}
          >
            <span>{record.name}</span>
          </Button>
          <Space>
            <Tag color={record.current_version ? 'green' : 'default'}>
              {record.current_version ? `v${record.current_version}` : '草稿'}
            </Tag>
            <Popconfirm
              title="删除工作流？"
              description="历史执行和快照会保留，未保存的本地草稿会清理。"
              okText="删除"
              cancelText="取消"
              onConfirm={() => onDelete(record.id)}
            >
              <Button
                type="text"
                danger
                size="small"
                icon={<DeleteOutlined />}
                loading={deleting && record.id === selectedId}
                aria-label={`删除工作流 ${record.name}`}
              />
            </Popconfirm>
          </Space>
        </div>
      ))}
    </div>
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
                    data-testid={`workflow-replay-${node.node_id}`}
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

function DebugResultPanel({ result }: { result: WorkflowState['debugResult'] }) {
  if (!result) return null
  return (
    <div className="workflow-runtime-panel">
      <div className="workflow-runtime-panel-heading">
        <Typography.Text strong>
          {result.mode === 'breakpoint' ? '断点调试结果' : '节点重放结果'}
        </Typography.Text>
        <Tag color={result.status === 'passed' ? 'green' : 'red'}>{result.status}</Tag>
      </div>
      <NodeTable nodes={result.nodes} />
    </div>
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
  onRepair,
}: {
  items: WorkflowExecution[]
  selectedId: string | null
  loading: boolean
  onView: (executionId: string) => void
  onRepair: (execution: WorkflowExecution) => void
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
          width: 220,
          render: (_value: unknown, item: WorkflowExecution) => (
            <Space size={0}>
              <Button
                type="link"
                size="small"
                icon={<EyeOutlined />}
                data-testid={`workflow-history-${item.id}`}
                onClick={() => onView(item.id)}
              >
                查看快照
              </Button>
              {item.status === 'failed' && (
                <Button
                  type="link"
                  size="small"
                  icon={<BugOutlined />}
                  onClick={() => onRepair(item)}
                >
                  失败诊断
                </Button>
              )}
            </Space>
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

function showExecutionPanels(state: WorkflowState): boolean {
  return (
    state.workspaceMode === 'run' ||
    state.workspaceMode === 'history' ||
    (state.workspaceMode === 'draft' && Boolean(state.debugResult))
  )
}
