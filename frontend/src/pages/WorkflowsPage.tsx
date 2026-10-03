import WorkflowWorkspaceShell from '../flow/WorkflowWorkspaceShell'
import WorkflowWorkbenchHeader from '../flow/WorkflowWorkbenchHeader'
import WorkflowRuntimeDock from '../flow/WorkflowRuntimeDock'
import { workflowLayoutKey } from '../flow/editor/layout-preferences'
import {
  BugOutlined,
  BarChartOutlined,
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
  Pagination,
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
import { useEffect, useState, type ReactNode } from 'react'
import { useQueries } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'

import CreateWorkflowDialog from '../features/workflows/CreateWorkflowDialog'
import ExecutionCheckpointLog from '../features/workflows/ExecutionCheckpointLog'
import FailureRepairDialog from '../features/workflows/FailureRepairDialog'
import IterationDebugDialog from '../features/workflows/IterationDebugDialog'
import FlowSpecReviewDialog, {
  type FlowSpecReviewSeed,
} from '../features/workflows/FlowSpecReviewDialog'
import FlowProposalReviewDialog from '../features/workflows/FlowProposalReviewDialog'
import NativeWorkflowTransferDialog from '../features/workflows/NativeWorkflowTransferDialog'
import { useWorkflows } from '../features/workflows/use-workflows'
import {
  clearExecutionEvidence,
  executionAttempt,
  executionEvidence,
  reportExecutionPath,
  writeExecutionEvidence,
} from '../features/workflows/execution-navigation'
import { getWorkflow, listWorkflowControlRecords } from '../features/workflows/workflow-service'
import { useWorkflowTabs } from '../features/workflows/use-workflow-tabs'
import { useAuthStore } from '../features/auth/auth-store'
import WorkflowDesigner from '../flow/WorkflowDesigner'
import {
  apiErrorMessage,
  type Page,
  type WorkflowControlRecordSummary,
  type Workflow,
  type WorkflowExecution,
  type WorkflowNodeExecution,
} from '../lib/api'

export default function WorkflowsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const initialProposalId = searchParams.get('proposal') ?? undefined
  const [createOpen, setCreateOpen] = useState(false)
  const [flowSpecOpen, setFlowSpecOpen] = useState(false)
  const [flowSpecSeed, setFlowSpecSeed] = useState<FlowSpecReviewSeed>()
  const [flowProposalOpen, setFlowProposalOpen] = useState(false)
  const [nativeTransferOpen, setNativeTransferOpen] = useState(false)
  const [repairExecution, setRepairExecution] = useState<WorkflowExecution>()
  const [iterationDebugOpen, setIterationDebugOpen] = useState(false)
  const { initialWorkflowId, initialExecutionId } = workflowRouteSelection(searchParams)
  const workflows = useWorkflows(initialWorkflowId, initialExecutionId)
  const state = {
    ...workflows,
    showHistory: (executionId: string) => {
      const next = new URLSearchParams(searchParams)
      next.set('execution', executionId)
      next.delete('node')
      next.delete('attempt')
      setSearchParams(next)
      workflows.showHistory(executionId)
    },
    showDraft: () => {
      const next = new URLSearchParams(searchParams)
      next.delete('execution')
      next.delete('node')
      next.delete('attempt')
      setSearchParams(next)
      workflows.showDraft()
    },
  }
  useEffect(() => {
    const listed = state.workflows.data
    if (initialExecutionId) return
    if (!initialWorkflowId || !listed || !state.workflowCatalogComplete) return
    if (listed.items.some((workflow) => workflow.id === initialWorkflowId)) return
    const next = new URLSearchParams(searchParams)
    next.delete('focus')
    setSearchParams(next, { replace: true })
  }, [
    initialExecutionId,
    initialWorkflowId,
    searchParams,
    setSearchParams,
    state.workflows.data,
    state.workflowCatalogComplete,
  ])
  const userId = useAuthStore((store) => store.user?.id)
  const tabs = useWorkflowTabs({
    userId,
    projectId: state.projectId,
    workflowIds: state.workflows.data?.items.map((item) => item.id) ?? [],
    catalogComplete: state.workflowCatalogComplete,
    invalidWorkflowIds: state.deletedWorkflowIds,
    activeWorkflowId: state.workflowId,
    hasExplicitFocus: Boolean(initialWorkflowId || initialExecutionId),
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
        onNativeTransfer={() => setNativeTransferOpen(true)}
        onIterationDebug={() => setIterationDebugOpen(true)}
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
      <NativeWorkflowTransferDialog
        open={nativeTransferOpen}
        projectId={state.projectId ?? ''}
        workflowId={state.workflowId}
        canEdit={state.canEdit}
        onClose={() => setNativeTransferOpen(false)}
        onImported={async (imported) => {
          await state.workflows.refetch()
          tabs.activateWorkflow(imported.id)
        }}
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
      <IterationDebugDialog
        open={iterationDebugOpen}
        projectId={state.projectId}
        workflowId={state.workflowId}
        environmentId={state.environmentId}
        version={selectedPublishedVersion(state)}
        currentExecution={state.runtimeExecution}
        canStart={canExecute(state)}
        onStarted={state.beginIterationDebugExecution}
        onClose={() => setIterationDebugOpen(false)}
      />
      <WorkflowTabCloseModal tabs={tabs} />
    </div>
  )
}

function workflowRouteSelection(params: URLSearchParams) {
  return {
    initialWorkflowId: params.get('focus') ?? undefined,
    initialExecutionId: params.get('execution') ?? undefined,
  }
}

type WorkflowState = ReturnType<typeof useWorkflows>

function selectedPublishedVersion(state: WorkflowState): number | null {
  return state.selectedWorkflow?.current_version ?? null
}

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
      summary={<RuntimeDockSummary state={state} />}
    >
      <WorkflowRuntimeTabs key={preferredTab} initialKey={preferredTab} items={items} />
    </WorkflowRuntimeDock>
  )
}

function RuntimeDockSummary({ state }: { state: WorkflowState }) {
  if (!state.runtimeExecution)
    return (
      <Typography.Text type="secondary">选择执行记录，查看当次节点状态与证据。</Typography.Text>
    )
  const nodes = state.runtimeNodes
  const failed = nodes.filter((node) => node.status === 'failed').length
  const completed = nodes.filter((node) =>
    ['passed', 'failed', 'skipped', 'cancelled'].includes(node.status),
  ).length
  return (
    <Space wrap>
      <Tag>
        节点记录 {completed}/{nodes.length} 已结束
      </Tag>
      <Tag color={failed ? 'error' : 'default'}>失败 {failed} 步</Tag>
      <Typography.Text type="secondary">
        执行 {state.runtimeExecution.id.slice(0, 8)} · 点击节点查看证据
      </Typography.Text>
    </Space>
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
  const [showCheckpointLog, setShowCheckpointLog] = useState(false)
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
      <ExecutionEventHistoryWarning
        execution={state.runtimeExecution}
        incompleteId={state.eventHistoryIncompleteId}
      />
      {state.runtimeChildren.length ? (
        <DatasetRunSummary items={state.runtimeChildren} onView={state.showHistory} />
      ) : (
        <>
          <NodeTable
            nodes={state.runtimeNodes}
            replaying={state.replaying}
            onReplay={
              state.workspaceMode === 'run' && state.lastResult
                ? (nodeId) => void state.replayNode(nodeId)
                : undefined
            }
          />
          <FailedItemRerunAction state={state} />
        </>
      )}
      {state.runtimeExecution && state.projectId && (
        <>
          <Button onClick={() => setShowCheckpointLog((value) => !value)}>
            {showCheckpointLog ? '收起执行记录' : '查看执行记录'}
          </Button>
          {showCheckpointLog && (
            <ExecutionCheckpointLog
              key={state.runtimeExecution.id}
              projectId={state.projectId}
              executionId={state.runtimeExecution.id}
              running={['queued', 'running'].includes(state.runtimeExecution.status)}
            />
          )}
        </>
      )}
    </div>
  )
}

function ExecutionEventHistoryWarning({
  execution,
  incompleteId,
}: {
  execution: WorkflowExecution | null
  incompleteId: string | null
}) {
  if (!execution || execution.id !== incompleteId) return null
  return (
    <Alert
      type="warning"
      showIcon
      message="部分实时事件已超过保留范围"
      description="运行状态已从服务器记录重新核对；实时事件记录不完整。可打开执行记录查看已持久化的节点详情。"
    />
  )
}

type FailedLoopOption = { nodeId: string; name: string; indices: number[]; paged: boolean }

function canOfferFailedItemRerun(
  state: WorkflowState,
  source: WorkflowExecution | null,
  loops: FailedLoopOption[],
): source is WorkflowExecution {
  return Boolean(
    source &&
    !source.derived_from_execution_id &&
    source.run_purpose !== 'preview' &&
    state.canEdit &&
    loops.length > 0 &&
    source.status !== 'queued' &&
    source.status !== 'running',
  )
}

function rerunSubmitDisabled(
  loopNodeId: string | null,
  indices: number[],
  resourceStatus: string,
  writeStrategy: string,
  note: string,
): boolean {
  const requiresNote =
    resourceStatus === 'confirmed_valid' || writeStrategy === 'verified_safe_to_retry'
  return (
    !loopNodeId ||
    !indices.length ||
    resourceStatus === 'expired' ||
    (requiresNote && note.trim().length < 8)
  )
}

function failedLoopOptions(nodes: WorkflowNodeExecution[]): FailedLoopOption[] {
  return nodes.flatMap((node): FailedLoopOption[] => {
    const output = node.output
    if (!isRecord(output)) return []
    if (output.report_paged === true && output.report_kind === 'iteration') {
      return typeof output.failed_count === 'number' && output.failed_count > 0
        ? [{ nodeId: node.node_id, name: node.name, indices: [], paged: true }]
        : []
    }
    if (!Array.isArray(output.items)) return []
    const indices = output.items.flatMap((item: unknown) =>
      isRecord(item) && item.test_verdict === 'failed' && typeof item.input_index === 'number'
        ? [item.input_index]
        : [],
    )
    return indices.length ? [{ nodeId: node.node_id, name: node.name, indices, paged: false }] : []
  })
}

function FailedItemRerunAction({ state }: { state: WorkflowState }) {
  const loops = failedLoopOptions(state.runtimeNodes)
  const [open, setOpen] = useState(false)
  const source = state.runtimeExecution
  if (!canOfferFailedItemRerun(state, source, loops)) return null
  return (
    <>
      <Button icon={<RedoOutlined />} onClick={() => setOpen(true)}>
        派生重跑失败项
      </Button>
      {open && (
        <FailedItemRerunDialog
          state={state}
          source={source}
          loops={loops}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  )
}

function FailedItemRerunDialog({
  state,
  source,
  loops,
  onClose,
}: {
  state: WorkflowState
  source: WorkflowExecution
  loops: FailedLoopOption[]
  onClose: () => void
}) {
  const [loopNodeId, setLoopNodeId] = useState<string | null>(loops[0].nodeId)
  const [indices, setIndices] = useState<number[]>([])
  const [resourceStatus, setResourceStatus] = useState<
    'unverified' | 'confirmed_valid' | 'expired'
  >('unverified')
  const [writeStrategy, setWriteStrategy] = useState<'reject' | 'verified_safe_to_retry'>('reject')
  const [note, setNote] = useState('')
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [failedPageNumber, setFailedPageNumber] = useState(1)
  const selectedLoop = loops.find((loop) => loop.nodeId === loopNodeId)
  const { failedPage, failedPageError } = useFailedRecordPage(
    state.projectId,
    source.id,
    selectedLoop,
    failedPageNumber,
  )
  return (
    <Modal
      title="派生重跑失败项"
      open
      okText="创建派生运行"
      okButtonProps={{
        disabled: rerunSubmitDisabled(loopNodeId, indices, resourceStatus, writeStrategy, note),
        loading: state.rerunningFailedItems,
      }}
      onCancel={onClose}
      onOk={async () => {
        setSubmitError(null)
        try {
          await state.rerunFailedItems(source.id, {
            loop_node_id: loopNodeId ?? '',
            input_indices: indices,
            upstream_resource_status: resourceStatus,
            write_retry_strategy: writeStrategy,
            ...(note.trim() ? { verification_note: note.trim() } : {}),
          })
          onClose()
        } catch (error) {
          setSubmitError(apiErrorMessage(error))
        }
      }}
    >
      <Space orientation="vertical" className="workflow-more-content">
        {submitError && <Alert type="error" showIcon title={submitError} />}
        <Alert
          type="info"
          showIcon
          title="原报告保留，使用原冻结输入和已成功步骤的输出。请先确认外部资源状态。"
        />
        <FailedItemSelection
          loops={loops}
          loopNodeId={loopNodeId}
          indices={indices}
          selectedLoop={selectedLoop}
          failedPage={failedPage}
          failedPageError={failedPageError}
          failedPageNumber={failedPageNumber}
          onLoopChange={(value) => {
            setLoopNodeId(value)
            setIndices([])
            setFailedPageNumber(1)
          }}
          onIndicesChange={setIndices}
          onPageChange={setFailedPageNumber}
        />
        <FailedItemVerificationFields
          resourceStatus={resourceStatus}
          writeStrategy={writeStrategy}
          note={note}
          onResourceStatusChange={setResourceStatus}
          onWriteStrategyChange={setWriteStrategy}
          onNoteChange={setNote}
        />
      </Space>
    </Modal>
  )
}

function useFailedRecordPage(
  projectId: string | null,
  executionId: string,
  selectedLoop: FailedLoopOption | undefined,
  page: number,
) {
  const [response, setResponse] = useState<{
    key: string
    value?: Page<WorkflowControlRecordSummary>
    error?: string
  } | null>(null)
  const nodeId = selectedLoop?.nodeId
  const paged = selectedLoop?.paged
  const key = `${projectId}:${executionId}:${nodeId}:${page}`
  useEffect(() => {
    if (!paged || !projectId || !nodeId) return
    let active = true
    void listWorkflowControlRecords(projectId, executionId, nodeId, 'iteration', page, 'failed')
      .then((value) => {
        if (active) setResponse({ key, value })
      })
      .catch((reason: unknown) => {
        if (active) setResponse({ key, error: apiErrorMessage(reason) })
      })
    return () => {
      active = false
    }
  }, [paged, projectId, executionId, nodeId, page, key])
  return {
    failedPage: response?.key === key ? response.value : undefined,
    failedPageError: response?.key === key ? response.error : undefined,
  }
}

function FailedItemSelection({
  loops,
  loopNodeId,
  indices,
  selectedLoop,
  failedPage,
  failedPageError,
  failedPageNumber,
  onLoopChange,
  onIndicesChange,
  onPageChange,
}: {
  loops: FailedLoopOption[]
  loopNodeId: string | null
  indices: number[]
  selectedLoop: FailedLoopOption | undefined
  failedPage: Page<WorkflowControlRecordSummary> | undefined
  failedPageError: string | undefined
  failedPageNumber: number
  onLoopChange: (value: string) => void
  onIndicesChange: (value: number[]) => void
  onPageChange: (value: number) => void
}) {
  const options = failedInputOptions(selectedLoop, indices, failedPage)
  return (
    <>
      <Select
        aria-label="选择失败循环"
        value={loopNodeId}
        options={loops.map((loop) => ({ value: loop.nodeId, label: loop.name }))}
        onChange={onLoopChange}
      />
      {failedPageError && <Alert type="error" title={failedPageError} />}
      {selectedLoop?.paged && failedPage?.total === 0 && (
        <Alert type="error" title="执行摘要显示失败轮次，但持久化记录缺失" />
      )}
      <Select
        mode="multiple"
        aria-label="选择失败轮次"
        value={indices}
        options={options}
        onChange={onIndicesChange}
      />
      <FailedItemPagination
        selectedLoop={selectedLoop}
        failedPage={failedPage}
        failedPageNumber={failedPageNumber}
        onPageChange={onPageChange}
      />
    </>
  )
}

function failedInputOptions(
  selectedLoop: FailedLoopOption | undefined,
  indices: number[],
  failedPage: Page<WorkflowControlRecordSummary> | undefined,
) {
  return [
    ...new Set([
      ...(selectedLoop?.indices ?? []),
      ...indices,
      ...(failedPage?.items.map((item) => item.ordinal) ?? []),
    ]),
  ].map((index) => ({ value: index, label: `第 ${index + 1} 项（input_index ${index}）` }))
}

function FailedItemPagination({
  selectedLoop,
  failedPage,
  failedPageNumber,
  onPageChange,
}: {
  selectedLoop: FailedLoopOption | undefined
  failedPage: Page<WorkflowControlRecordSummary> | undefined
  failedPageNumber: number
  onPageChange: (value: number) => void
}) {
  if (!selectedLoop?.paged || (failedPage?.total ?? 0) <= 20) return null
  return (
    <Pagination
      aria-label="失败轮次分页"
      current={failedPageNumber}
      total={failedPage?.total ?? 0}
      pageSize={20}
      showSizeChanger={false}
      onChange={onPageChange}
    />
  )
}

function FailedItemVerificationFields({
  resourceStatus,
  writeStrategy,
  note,
  onResourceStatusChange,
  onWriteStrategyChange,
  onNoteChange,
}: {
  resourceStatus: 'unverified' | 'confirmed_valid' | 'expired'
  writeStrategy: 'reject' | 'verified_safe_to_retry'
  note: string
  onResourceStatusChange: (value: 'unverified' | 'confirmed_valid' | 'expired') => void
  onWriteStrategyChange: (value: 'reject' | 'verified_safe_to_retry') => void
  onNoteChange: (value: string) => void
}) {
  return (
    <>
      <Select
        aria-label="上游资源状态"
        value={resourceStatus}
        options={[
          { value: 'unverified', label: '尚未查证' },
          { value: 'confirmed_valid', label: '已确认资源仍有效' },
          { value: 'expired', label: '资源已过期，暂停重跑' },
        ]}
        onChange={onResourceStatusChange}
      />
      <Select
        aria-label="失败写操作策略"
        value={writeStrategy}
        options={[
          { value: 'reject', label: '不重试失败写操作' },
          { value: 'verified_safe_to_retry', label: '查证后允许重试失败写操作' },
        ]}
        onChange={onWriteStrategyChange}
      />
      <Input.TextArea
        aria-label="外部状态查证说明"
        placeholder="如确认了资源有效或写操作可安全重试，请写明查证依据（至少 8 字）"
        value={note}
        onChange={(event) => onNoteChange(event.target.value)}
      />
    </>
  )
}

function WorkbenchMore({
  state,
  onCreate,
  onFlowSpec,
  onFlowProposal,
  onNativeTransfer,
}: {
  state: WorkflowState
  onCreate: () => void
  onFlowSpec: () => void
  onFlowProposal: () => void
  onNativeTransfer: () => void
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
          <Button icon={<ImportOutlined />} disabled={!state.projectId} onClick={onNativeTransfer}>
            原生定义导入 / 导出
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

function HeaderPrimaryActions({
  state,
  onIterationDebug,
}: {
  state: WorkflowState
  onIterationDebug: () => void
}) {
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
        保存草稿
      </Button>
      <Button
        icon={<CloudUploadOutlined />}
        aria-label="发布版本"
        disabled={disabled}
        loading={state.publishing}
        onClick={() => void state.publish()}
      >
        发布版本
      </Button>
      <Button
        type="primary"
        icon={<PlayCircleOutlined />}
        aria-label="运行已发布版本"
        disabled={!canExecute(state)}
        loading={state.executing || Boolean(state.activeExecutionId)}
        onClick={() => void state.execute()}
      >
        执行
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
      {state.workspaceMode === 'draft' && (
        <Button
          icon={<BugOutlined />}
          aria-label="逐轮调试"
          title="逐轮调试"
          disabled={!state.selectedWorkflow?.current_version || !state.canEdit}
          onClick={onIterationDebug}
        />
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
  const workflows = state.knownWorkflows
  const byId = new Map(workflows.map((workflow) => [workflow.id, workflow]))
  const details = useQueries({
    queries: workflowIds.map((id) => ({
      queryKey: ['workflow', state.projectId, id],
      queryFn: () => getWorkflow(state.projectId!, id),
      enabled:
        Boolean(state.projectId && state.workflows.data) &&
        !byId.has(id) &&
        !state.workflowCatalogComplete,
      retry: false,
    })),
  })
  const items = workflowIds.map((id, index) => {
    const workflow = byId.get(id) ?? details[index]?.data
    const dirty = dirtyIds.includes(id)
    return {
      key: id,
      label: (
        <span>
          {workflow?.name ?? `流程 ${id.slice(0, 8)}`}
          {details[index]?.error && <Typography.Text type="danger"> · 读取失败</Typography.Text>}
          {dirty && <Typography.Text type="warning"> ·</Typography.Text>}
        </span>
      ),
      closable: true,
    }
  })
  const execution = state.runtimeExecution ?? state.lastResult?.execution
  if (!items.length && !execution) {
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
        <ExecutionReportTab projectId={state.projectId} execution={execution} />
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

function ExecutionReportTab({
  projectId,
  execution,
}: {
  projectId: string | null
  execution: WorkflowExecution | null | undefined
}) {
  if (!projectId || !execution) return null
  return (
    <Link
      className="execution-report-tab"
      to={reportExecutionPath(projectId, { executionId: execution.id })}
    >
      <BarChartOutlined /> 执行报告{' '}
      <span className="workflow-volatile-value">{execution.id.slice(0, 8)}</span>
    </Link>
  )
}

function WorkflowWorkspace({
  state,
  onSelectWorkflow,
  onCreate,
  onFlowSpec,
  onFlowProposal,
  onNativeTransfer,
  onIterationDebug,
  onRepair,
}: {
  state: WorkflowState
  onSelectWorkflow: (workflowId: string) => void
  onCreate: () => void
  onFlowSpec: () => void
  onFlowProposal: () => void
  onNativeTransfer: () => void
  onIterationDebug: () => void
  onRepair: (execution: WorkflowExecution) => void
}) {
  const userId = useAuthStore((store) => store.user?.id)
  const [historyDockOpen, setHistoryDockOpen] = useState(false)
  const [params] = useSearchParams()
  return (
    <WorkflowWorkspaceShell
      key={workflowLayoutKey(userId, state.projectId)}
      preferenceKey={workflowLayoutKey(userId, state.projectId)}
      catalogRequested={params.get('directory') === '1'}
      header={
        <WorkflowWorkbenchHeader
          left={workspaceTitle(state)}
          center={
            <Space wrap>
              <WorkspaceModeSwitch state={state} />
              <WorkflowEnvironmentSelect state={state} />
            </Space>
          }
          right={
            <Space>
              {state.workspaceMode !== 'history' && (
                <HeaderPrimaryActions state={state} onIterationDebug={onIterationDebug} />
              )}
              <WorkflowReportLink state={state} />
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
                onNativeTransfer={onNativeTransfer}
              />
            </Space>
          }
        />
      }
      list={
        <WorkflowCatalog state={state} onCreate={onCreate} onSelectWorkflow={onSelectWorkflow} />
      }
      runtimeDock={
        <WorkflowExecutionPanels state={state} onRepair={onRepair} forceOpen={historyDockOpen} />
      }
    >
      <Card
        className="workflow-workbench-card"
        loading={state.workspaceMode === 'history' && state.historyLoading}
      >
        <DraftEditor state={state} onIterationDebug={onIterationDebug} />
      </Card>
    </WorkflowWorkspaceShell>
  )
}

function WorkflowEnvironmentSelect({ state }: { state: WorkflowState }) {
  if (state.workspaceMode !== 'draft' && state.runtimeExecution)
    return <Tag>执行环境：{executionEnvironmentLabel(state.runtimeExecution)}</Tag>
  return (
    <Select
      aria-label="工作流环境"
      id="workflow-environment-select"
      className="workflow-environment-select"
      placeholder={state.environmentPlaceholder}
      status={state.environmentStatus}
      value={state.environmentId}
      loading={state.environments.isLoading}
      disabled={!state.projectId}
      options={options(state.environments.data)}
      onChange={state.setEnvironmentSelection}
    />
  )
}

function WorkflowReportLink({ state }: { state: WorkflowState }) {
  const [params] = useSearchParams()
  const execution = state.runtimeExecution
  if (!execution || !state.projectId) return null
  return (
    <Link
      className="workflow-report-link"
      aria-label="查看完整报告"
      to={reportExecutionPath(state.projectId, {
        executionId: execution.id,
        nodeId: params.get('node'),
        attempt: executionAttempt(params),
        ...executionEvidence(params),
      })}
    >
      <BarChartOutlined /> 查看完整报告
    </Link>
  )
}

function executionEnvironmentLabel(execution: WorkflowExecution): string {
  const environment = execution.snapshot.environment
  if (
    environment &&
    typeof environment === 'object' &&
    'name' in environment &&
    typeof environment.name === 'string'
  )
    return environment.name
  return execution.environment_id
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
        <Typography.Title level={1} className="workflow-page-title">
          流程编排
        </Typography.Title>
        <span className="workflow-workspace-name">
          {executionSnapshotName(state.runtimeExecution) ?? '历史执行快照'}
        </span>
        <Space size={4} wrap>
          <Tag icon={<LockOutlined />} color="gold">
            历史快照 · 不可修改
          </Tag>
          <Tag>{executionSnapshotVersion(state.runtimeExecution)}</Tag>
        </Space>
      </div>
    )
  }
  return (
    <div className="workflow-workspace-title">
      <Typography.Title level={1} className="workflow-page-title">
        流程编排
      </Typography.Title>
      <span className="workflow-workspace-name">{workflow?.name ?? '流程工作区'}</span>
      {workflow && <DraftMetadata state={state} workflow={workflow} />}
    </div>
  )
}

function executionSnapshotVersion(execution: WorkflowExecution | null | undefined): string {
  const workflow = execution?.snapshot.workflow
  if (
    workflow &&
    typeof workflow === 'object' &&
    'version' in workflow &&
    typeof workflow.version === 'number'
  )
    return `执行版本 v${workflow.version}`
  return '未提供执行版本'
}

function executionSnapshotName(execution: WorkflowExecution | null | undefined): string | null {
  const workflow = execution?.snapshot.workflow
  if (
    workflow &&
    typeof workflow === 'object' &&
    'name' in workflow &&
    typeof workflow.name === 'string'
  )
    return workflow.name
  return null
}

function FocusDraftActions({
  state,
  onIterationDebug,
}: {
  state: WorkflowState
  onIterationDebug: () => void
}) {
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
      <Button
        icon={<BugOutlined />}
        aria-label="逐轮调试"
        title="逐轮调试"
        disabled={!state.selectedWorkflow?.current_version || !state.canEdit}
        onClick={onIterationDebug}
      />
    </Space>
  )
}

function DraftEditor({
  state,
  onIterationDebug,
}: {
  state: WorkflowState
  onIterationDebug: () => void
}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const workflow = state.selectedWorkflow
  if (!workflow && state.workspaceMode === 'draft')
    return <Empty description="请选择或新建工作流" />
  const workflowId = designerWorkflowId(state)
  const resources = workflowDesignerResources(state, workflowId)
  return (
    <>
      <DraftAlerts state={state} />
      <WorkflowDesigner
        key={`${workflowId}:${state.workspaceMode}:${state.historyExecutionId ?? ''}`}
        surface="workspace"
        workflowId={workflowId}
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
        runtimeExecutionId={state.runtimeExecution?.id}
        runtimeNodes={state.runtimeNodes}
        runtimeContext={state.runtimeContext}
        {...designerFocusProps(state.workspaceMode, searchParams, setSearchParams)}
        focusActions={<FocusDraftActions state={state} onIterationDebug={onIterationDebug} />}
        onChange={state.setDraftDefinition}
      />
    </>
  )
}

function designerWorkflowId(state: WorkflowState): string {
  return state.runtimeExecution?.workflow_id ?? state.workflowId ?? 'historical'
}

function designerFocusProps(
  mode: WorkflowState['workspaceMode'],
  params: URLSearchParams,
  setParams: ReturnType<typeof useSearchParams>[1],
) {
  if (mode === 'draft') return {}
  return {
    focusNodeId: params.get('node') ?? undefined,
    runtimeAttempt: executionAttempt(params),
    runtimeEvidence: executionEvidence(params),
    onEvidenceFocus: (evidence: ReturnType<typeof executionEvidence>) => {
      const next = new URLSearchParams(params)
      writeExecutionEvidence(next, evidence)
      setParams(next, { replace: true })
    },
    onNodeFocus: (nodeId: string | null) => {
      const next = new URLSearchParams(params)
      if (nodeId) next.set('node', nodeId)
      else next.delete('node')
      if (!nodeId || nodeId !== params.get('node')) {
        next.delete('attempt')
        clearExecutionEvidence(next)
      }
      setParams(next, { replace: true })
    },
    onAttemptFocus: (nodeId: string, attempt: number) => {
      const next = new URLSearchParams(params)
      next.set('node', nodeId)
      next.set('attempt', String(attempt))
      setParams(next, { replace: true })
    },
  }
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
      {historyAlert && state.historyError && (
        <Alert
          type="error"
          showIcon
          title="历史执行快照加载失败"
          description={state.historyError}
          action={<Button onClick={state.reloadHistory}>重试</Button>}
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
  const workflows = state.knownWorkflows
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
  canDelete,
  query,
  onSearch,
  page,
  total,
  onPage,
  loading,
  error,
  onReload,
}: {
  items: Workflow[]
  selectedId: string | null
  onSelect: (id: string) => void
  deleting: boolean
  onDelete: (id: string) => void
  canDelete: boolean
  query: string
  onSearch: (value: string) => void
  page: number
  total: number
  onPage: (page: number) => void
  loading: boolean
  error: Error | null
  onReload: () => void
}) {
  return (
    <div className="workflow-compact-list">
      <Input.Search
        aria-label="搜索工作流"
        placeholder="搜索工作流"
        value={query}
        onChange={(event) => onSearch(event.target.value)}
      />
      <WorkflowCatalogStatus
        loading={loading}
        error={error}
        empty={!items.length}
        onReload={onReload}
      />
      {items.map((record) => (
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
                disabled={!canDelete || deleting}
              />
            </Popconfirm>
          </Space>
        </div>
      ))}
      <Typography.Text type="secondary">匹配 {total} 个流程，每页 100 项</Typography.Text>
      <nav aria-label="流程目录分页">
        <Pagination
          size="small"
          current={page}
          pageSize={100}
          total={total}
          showSizeChanger={false}
          onChange={onPage}
        />
      </nav>
    </div>
  )
}

function WorkflowCatalogStatus({
  loading,
  error,
  empty,
  onReload,
}: {
  loading: boolean
  error: Error | null
  empty: boolean
  onReload: () => void
}) {
  if (error)
    return (
      <Alert
        type="error"
        title="流程目录读取失败"
        description={apiErrorMessage(error)}
        action={<Button onClick={onReload}>重新读取目录</Button>}
      />
    )
  if (loading)
    return <Typography.Paragraph type="secondary">正在读取流程目录…</Typography.Paragraph>
  if (empty) return <Empty description="当前搜索没有匹配的工作流" />
  return null
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

export function DatasetRunSummary({
  items,
  onView,
}: {
  items: WorkflowExecution[]
  onView: (executionId: string) => void
}) {
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
          {
            title: '操作',
            width: 110,
            render: (_value: unknown, item: WorkflowExecution) => (
              <Button type="link" size="small" onClick={() => onView(item.id)}>
                查看子执行
              </Button>
            ),
          },
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

function WorkflowCatalog({
  state,
  onCreate,
  onSelectWorkflow,
}: {
  state: WorkflowState
  onCreate: () => void
  onSelectWorkflow: (id: string) => void
}) {
  return (
    <Card
      className="workflow-list-card"
      title={<WorkflowListTitle onCreate={onCreate} disabled={!canCreateCatalogWorkflow(state)} />}
    >
      <WorkflowTable
        items={state.workflows.data?.items ?? []}
        selectedId={state.workflowId}
        onSelect={onSelectWorkflow}
        deleting={state.deleting}
        onDelete={(id) => void state.deleteWorkflow(id)}
        canDelete={state.canEdit}
        query={state.workflowSearch}
        onSearch={state.setWorkflowSearch}
        page={state.workflowPage}
        total={state.workflows.data?.total ?? 0}
        onPage={state.setWorkflowPage}
        loading={state.workflows.isFetching}
        error={state.workflows.error}
        onReload={() => void state.workflows.refetch()}
      />
    </Card>
  )
}

function canCreateCatalogWorkflow(state: WorkflowState): boolean {
  return Boolean(state.projectId && state.canEdit && state.apis.data?.items.length)
}
