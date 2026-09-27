import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, App, Button, Checkbox, Descriptions, InputNumber, Modal, Select, Space } from 'antd'
import { useEffect, useMemo, useState } from 'react'

import {
  apiErrorMessage,
  type WorkflowExecution,
  type WorkflowIterationDebugSession,
  type WorkflowNode,
} from '../../lib/api'
import {
  commandIterationDebug,
  findIterationDebugSession,
  listWorkflowVersions,
  startIterationDebug,
} from './workflow-service'

type Props = {
  open: boolean
  projectId: string | null
  workflowId: string | null
  environmentId: string | null
  version: number | null
  currentExecution: WorkflowExecution | null
  canStart: boolean
  onStarted: (execution: WorkflowExecution) => void
  onClose: () => void
}

type StartedExecution = { projectId: string; workflowId: string; executionId: string }

export default function IterationDebugDialog(props: Props) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [pauseBeforeIndex, setPauseBeforeIndex] = useState(0)
  const [pauseOnError, setPauseOnError] = useState(true)
  const [maxSessionSeconds, setMaxSessionSeconds] = useState(300)
  const published = usePublishedLoops(props)
  const debug = useDebugSession(props)
  const start = useMutation({
    mutationFn: () =>
      startIterationDebug(required(props.projectId), required(props.workflowId), {
        environment_id: required(props.environmentId),
        version: required(props.version),
        loop_node_id: required(published.selectedLoop),
        pause_before_index: pauseBeforeIndex,
        pause_on_error: pauseOnError,
        max_session_seconds: maxSessionSeconds,
        pause_scope: 'target_loop',
      }),
    onSuccess: (result) => {
      debug.remember(result.execution.id)
      queryClient.setQueryData(
        ['workflow-iteration-debug', props.projectId, result.execution.id],
        result.session,
      )
      props.onStarted(result.execution)
      void message.success('逐轮调试运行已启动')
    },
  })
  const command = useMutation({
    mutationFn: (action: 'step' | 'continue') =>
      commandIterationDebug(
        required(props.projectId),
        required(debug.executionId),
        action,
        required(debug.session.data?.revision),
      ),
    onSuccess: (result) => queryClient.setQueryData(debug.sessionKey, result),
    onError: () => void debug.session.refetch(),
  })
  const notice = pauseNotice(debug.session.data)
  useEffect(() => {
    if (props.open && notice) void message.info(notice)
  }, [message, notice, props.open])

  const error = published.versions.error ?? debug.session.error ?? start.error ?? command.error
  return (
    <Modal
      title="逐轮调试"
      open={props.open}
      footer={null}
      onCancel={props.onClose}
      destroyOnHidden
    >
      {error && <Alert type="error" showIcon title={apiErrorMessage(error)} />}
      {debug.session.data ? (
        <SessionView
          session={debug.session.data}
          pending={command.isPending}
          onCommand={command.mutate}
          onNewRun={debug.newRun}
          canStart={props.canStart}
        />
      ) : (
        <StartView
          loops={published.loops}
          selectedLoop={published.selectedLoop}
          onSelectLoop={published.setLoopNodeId}
          pauseBeforeIndex={pauseBeforeIndex}
          onPauseBeforeIndex={setPauseBeforeIndex}
          maxSessionSeconds={maxSessionSeconds}
          onMaxSessionSeconds={setMaxSessionSeconds}
          pauseOnError={pauseOnError}
          onPauseOnError={setPauseOnError}
          canStart={props.canStart && !debug.session.isLoading}
          loading={published.versions.isLoading || start.isPending}
          onStart={() => start.mutate()}
        />
      )}
    </Modal>
  )
}

function usePublishedLoops(props: Props) {
  const [loopNodeId, setLoopNodeId] = useState<string | null>(null)
  const versions = useQuery({
    queryKey: ['workflow-versions', props.projectId, props.workflowId],
    queryFn: () => listWorkflowVersions(required(props.projectId), required(props.workflowId)),
    enabled: props.open && Boolean(props.projectId && props.workflowId),
  })
  const published = versions.data?.find((item) => item.version === props.version)
  const loops = useMemo(
    () => published?.definition.nodes.filter(isSerialInlineLoop) ?? [],
    [published],
  )
  const selectedLoop = loops.find((node) => node.id === loopNodeId)?.id ?? loops[0]?.id ?? null
  return { versions, loops, selectedLoop, setLoopNodeId }
}

function useDebugSession(props: Props) {
  const [started, setStarted] = useState<StartedExecution | null>(null)
  const [fresh, setFresh] = useState(false)
  const executionId = resolveExecutionId(props, started, fresh)
  const sessionKey = ['workflow-iteration-debug', props.projectId, executionId]
  const session = useQuery({
    queryKey: sessionKey,
    queryFn: () => findIterationDebugSession(required(props.projectId), required(executionId)),
    enabled: props.open && Boolean(props.projectId && executionId),
    refetchInterval: (query) => (shouldPoll(query.state.data) ? 1000 : false),
  })
  const remember = (id: string) => {
    setStarted({
      projectId: required(props.projectId),
      workflowId: required(props.workflowId),
      executionId: id,
    })
    setFresh(false)
  }
  return { executionId, sessionKey, session, remember, newRun: () => setFresh(true) }
}

function resolveExecutionId(props: Props, started: StartedExecution | null, fresh: boolean) {
  if (fresh) return null
  if (started?.projectId === props.projectId && started.workflowId === props.workflowId) {
    return started.executionId
  }
  if (props.currentExecution?.workflow_id === props.workflowId) return props.currentExecution.id
  return null
}

function shouldPoll(session: WorkflowIterationDebugSession | null | undefined): boolean {
  return Boolean(session && !['completed', 'expired', 'cancelled'].includes(session.status))
}

function pauseNotice(session: WorkflowIterationDebugSession | null | undefined): string | null {
  if (session?.status !== 'paused' || session.paused_input_index === null) return null
  return `第 ${session.paused_input_index + 1} 轮已暂停（会话版本 ${session.revision}）`
}

function SessionView({
  session,
  pending,
  onCommand,
  onNewRun,
  canStart,
}: {
  session: WorkflowIterationDebugSession
  pending: boolean
  onCommand: (action: 'step' | 'continue') => void
  onNewRun: () => void
  canStart: boolean
}) {
  const stopped = ['completed', 'expired', 'cancelled'].includes(session.status)
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Descriptions column={1} size="small" items={sessionItems(session)} />
      <Alert
        type="info"
        showIcon
        title="仅暂停当前串行循环"
        description="调试暂停受会话时限和工作流运行时限约束；执行详情可在运行报告中查看。"
      />
      {session.status === 'paused' && (
        <Space>
          <Button loading={pending} onClick={() => onCommand('step')}>
            单步一轮
          </Button>
          <Button type="primary" loading={pending} onClick={() => onCommand('continue')}>
            继续运行
          </Button>
        </Space>
      )}
      {stopped && (
        <Button disabled={!canStart} onClick={onNewRun}>
          新建调试运行
        </Button>
      )}
    </Space>
  )
}

function sessionItems(session: WorkflowIterationDebugSession) {
  return [
    { key: 'status', label: '会话状态', children: statusText(session.status) },
    {
      key: 'iteration',
      label: '当前轮次',
      children:
        session.paused_input_index === null
          ? '尚未暂停'
          : `第 ${session.paused_input_index + 1} 轮`,
    },
    { key: 'completed', label: '已完成', children: `${session.last_completed_index + 1} 轮` },
    { key: 'reason', label: '暂停原因', children: pauseReason(session.pause_reason) },
    { key: 'deadline', label: '会话截止', children: new Date(session.expires_at).toLocaleString() },
  ]
}

type StartViewProps = {
  loops: WorkflowNode[]
  selectedLoop: string | null
  onSelectLoop: (value: string) => void
  pauseBeforeIndex: number
  onPauseBeforeIndex: (value: number) => void
  maxSessionSeconds: number
  onMaxSessionSeconds: (value: number) => void
  pauseOnError: boolean
  onPauseOnError: (value: boolean) => void
  canStart: boolean
  loading: boolean
  onStart: () => void
}

function StartView(props: StartViewProps) {
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Alert
        type="info"
        showIcon
        title="按已发布版本启动调试"
        description="目前支持主流程的串行内联循环。调试运行会创建独立执行记录。"
      />
      <Select
        aria-label="调试循环"
        placeholder="选择循环"
        style={{ width: '100%' }}
        value={props.selectedLoop}
        options={props.loops.map((node) => ({ value: node.id, label: node.name }))}
        onChange={props.onSelectLoop}
      />
      <Space wrap>
        <span>暂停前轮次（从 1 开始）</span>
        <InputNumber
          aria-label="暂停前轮次"
          min={1}
          max={1000}
          value={props.pauseBeforeIndex + 1}
          onChange={(value) => props.onPauseBeforeIndex((value ?? 1) - 1)}
        />
        <span>会话上限（秒）</span>
        <InputNumber
          aria-label="会话上限秒数"
          min={30}
          max={600}
          value={props.maxSessionSeconds}
          onChange={(value) => props.onMaxSessionSeconds(value ?? 300)}
        />
      </Space>
      <Checkbox
        checked={props.pauseOnError}
        onChange={(event) => props.onPauseOnError(event.target.checked)}
      >
        轮次失败时暂停
      </Checkbox>
      <Button
        type="primary"
        disabled={!props.canStart || !props.selectedLoop}
        loading={props.loading}
        onClick={props.onStart}
      >
        启动逐轮调试
      </Button>
      {!props.loading && props.loops.length === 0 && (
        <Alert type="warning" showIcon title="已发布版本没有可调试的串行内联循环" />
      )}
    </Space>
  )
}

function isSerialInlineLoop(node: WorkflowNode): boolean {
  return node.phase !== 'cleanup' && isLoopCapability(node) && hasInlineBody(node) && isSerial(node)
}

function isLoopCapability(node: WorkflowNode): boolean {
  return [
    'flow.control.foreach',
    'flow.control.repeat',
    'flow.control.while',
    'flow.control.do_while',
    'flow.control.until',
  ].includes(node.capability_id ?? '')
}

function hasInlineBody(node: WorkflowNode): boolean {
  const body = node.configuration?.body
  return typeof body === 'object' && body !== null && 'kind' in body && body.kind === 'inline'
}

function isSerial(node: WorkflowNode): boolean {
  const policy = node.configuration?.policy
  if (typeof policy !== 'object' || policy === null || !('concurrency' in policy)) return true
  return policy.concurrency === 1
}

function statusText(status: string): string {
  return (
    {
      armed: '等待指定轮次',
      running: '运行中',
      paused: '已暂停',
      completed: '已结束',
      expired: '已超时',
      cancelled: '已取消',
    }[status] ?? status
  )
}

function pauseReason(reason: string | null): string {
  return (
    {
      before_iteration: '指定轮次前',
      error: '轮次失败',
      step_completed: '单步完成',
    }[reason ?? ''] ?? '—'
  )
}

function required<T>(value: T | null | undefined): T {
  if (value === null || value === undefined) throw new Error('缺少逐轮调试所需的项目或工作流信息')
  return value
}
